"""Finite actual-source SDIO reset ownership qualification; no device access."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import tarfile

from kernel_sources import locked

DRIVER = 'drivers/net/wireless/broadcom/brcm80211/brcmfmac/'
CANDIDATE = 'kernel/candidates/0073-brcmfmac-reset-ownership.patch'
SOURCE_FILES = tuple(sorted((
    'drivers/base/dd.c', 'drivers/mmc/core/core.c',
    'drivers/mmc/core/sdio.c', 'drivers/mmc/core/sdio_bus.c',
    'include/linux/klist.h', 'lib/klist.c',
    *(DRIVER + name for name in
      ('bcmsdh.c', 'bus.h', 'cfg80211.c', 'cfg80211.h', 'core.c',
       'core.h', 'sdio.c', 'sdio.h')),
)))
FUNCTIONS = (
    ('lib/klist.c', 'int klist_node_attached('),
    ('drivers/base/dd.c', 'bool device_is_bound('),
    ('drivers/mmc/core/core.c', 'void _mmc_detect_change('),
    ('drivers/mmc/core/sdio.c', 'static int mmc_sdio_hw_reset('),
    ('drivers/mmc/core/core.c', 'int mmc_hw_reset('),
    ('drivers/mmc/core/sdio_bus.c', 'static int sdio_bus_probe('),
    ('drivers/mmc/core/sdio_bus.c', 'static void sdio_bus_remove('),
    (DRIVER + 'bcmsdh.c', 'int brcmf_sdiod_remove('),
    (DRIVER + 'bcmsdh.c', 'static void brcmf_ops_sdio_remove('),
    (DRIVER + 'core.c', 'void brcmf_bus_change_state('),
    (DRIVER + 'sdio.c', 'static int brcmf_sdio_bus_reset('),
)
TYPES = (
    ('include/linux/klist.h', 'struct klist_node {'),
    (DRIVER + 'bus.h', 'enum brcmf_bus_state {'),
    (DRIVER + 'sdio.h', 'enum brcmf_sdiod_state {'),
)
CASES = (
    'mmc_multifunc_schedule', 'mmc_multifunc_already_removed',
    'mmc_after_f2_unbind_sync', 'mmc_after_f2_unbind_eio',
    'mmc_after_f2_unbind_timeout', 'reset_bound_async',
    'reset_bound_already_removed', 'reset_unbound_f2_sync_refused',
    'reset_unbound_f2_eio_refused', 'reset_unbound_f2_timeout_refused',
    'f2_remove_preserves_shared', 'reset_lifecycle_busy', 'reset_pm_failed',
    'reset_pm_retained', 'reset_pm_powered_off', 'reset_no_transport',
)
METRICS = (
    'ret', 'teardown', 'irq', 'host', 'lock', 'lock_get', 'lock_put',
    'bound', 'removed', 'rescan', 'power', 'reinit', 'warnings',
    'transport', 'drvr', 'f2_bound', 'f2_driver', 'f2_data', 'f1_data',
    'host_calls', 'probes', 'disable', 'freezer', 'sg', 'pm_allow',
)
UNBOUND = frozenset(name for name in CASES if name.startswith('reset_unbound_'))
GUARD = (
    '\t/* F2 owns the shared transport; an unbound function cannot reset it. */\n'
    '\tif (!device_is_bound(f2dev)) {\n'
    '\t\tret = -ENODEV;\n'
    '\t\tgoto unlock;\n'
    '\t}\n'
)
RESET = 'static int brcmf_sdio_bus_reset('
MAINTAINED = (
    CANDIDATE, 'kernel/tests/brcmfmac_reset_test.c',
    'tools/brcmfmac_reset_checks.py', 'tools/check-brcmfmac-reset.py',
    'tools/tests/test_brcmfmac_reset.py', 'tools/kernel-inputs.py',
    'tools/kernel_sources.py', 'build/sources.lock.json', 'Taskfile.yml',
    'tools/managed_container.py', 'tools/docker-stage.py',
    'tools/build-bin/docker', 'tools/run-logged.sh', 'tools/check-kernel-config.py',
    'tools/keypad_supply.py', 'kernel/gameshellneo.config',
)


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def inputs(root):
    return {name: file_hash(root / name) for name in MAINTAINED}


def extract(text, declaration, end='\n}'):
    matches = list(re.finditer(r'^' + re.escape(declaration), text, re.M))
    if len(matches) != 1:
        raise ValueError('Expected one actual-source declaration: ' + declaration)
    start = matches[0].start()
    return text[start:text.index(end, start) + len(end)] + '\n'


def projection(source):
    types = ''.join(extract((source / name).read_text(), declaration, '\n};')
                    for name, declaration in TYPES)
    functions = ''.join(extract((source / name).read_text(), declaration)
                        for name, declaration in FUNCTIONS)
    return types, functions


def kernel_inputs(root):
    spec = importlib.util.spec_from_file_location(
        'brcmfmac_reset_kernel_inputs', root / 'tools/kernel-inputs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def selected_queue(queue):
    selected = []
    for name, data in queue:
        targets = {item.decode() for item in
                   re.findall(rb'^\+\+\+ b/([^\t\n]+)', data, re.M)}
        if targets & set(SOURCE_FILES):
            if not targets <= set(SOURCE_FILES):
                raise ValueError('Whole selected patch changes an unprojected file: ' + name)
            selected.append((name, data))
    if not selected:
        raise ValueError('No production driver patches selected')
    return selected


def prepare(root, archive, destination):
    """Verify an existing archive and project at most 2 MiB of named members."""
    lock = json.loads((root / 'build/sources.lock.json').read_text())
    if archive.is_symlink() or not archive.is_file():
        raise ValueError('Supply an existing regular locked archive with --archive')
    archive_sha = file_hash(archive)
    if archive_sha != lock['linux']['tarball_sha256']:
        raise ValueError('Locked archive identity mismatch')
    module = kernel_inputs(root)
    queue = list(module.patches())
    selected = selected_queue(queue)
    upstream = destination / 'upstream'
    upstream.mkdir()
    prefix = 'linux-' + lock['linux']['tag'].removeprefix('v') + '/'
    remaining = {prefix + name: name for name in SOURCE_FILES}
    original = {}
    selected_bytes = 0
    with tarfile.open(archive, 'r|xz') as stream:
        for member in stream:
            stream.members.clear()
            if member.name not in remaining:
                continue
            name = remaining.pop(member.name)
            if not member.isfile() or member.size < 0:
                raise ValueError('Expected regular source member: ' + name)
            selected_bytes += member.size
            if selected_bytes > 2 * 1024 * 1024:
                raise ValueError('Selected source projection exceeds 2 MiB')
            data = stream.extractfile(member).read()
            if len(data) != member.size:
                raise ValueError('Incomplete source member: ' + name)
            path = upstream / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            original[name] = digest(data)
            if not remaining:
                break
    if remaining:
        raise ValueError('Locked archive lacks selected members')
    baseline = destination / 'baseline-source'
    candidate = destination / 'candidate-source'
    shutil.copytree(upstream, baseline)
    module.apply_queue(baseline, selected)
    shutil.copytree(baseline, candidate)
    patch = (root / CANDIDATE).read_bytes()
    module.apply_queue(candidate, [(Path(CANDIDATE).name, patch)])
    return baseline, candidate, dict(
        archive=str(archive), archive_sha256=archive_sha,
        selected_bytes=selected_bytes, upstream=original,
        production_queue=[dict(name=name, sha256=digest(data)) for name, data in queue],
        selected_patches=[dict(name=name, sha256=digest(data)) for name, data in selected],
        baseline={name: file_hash(baseline / name) for name in SOURCE_FILES},
        candidate={name: file_hash(candidate / name) for name in SOURCE_FILES},
        candidate_patch_sha256=digest(patch),
    )


def expected_metrics(case):
    if case not in CASES:
        raise ValueError('Unknown case: ' + case)
    expected = dict.fromkeys(METRICS, 0)
    expected.update(bound=2, transport=1, drvr=1, f2_bound=1, f2_driver=1,
                    f2_data=1, f1_data=1, probes=2)
    if case.startswith('mmc_multifunc_'):
        expected.update(ret=1, removed=1, host_calls=1,
                        rescan=int(case == 'mmc_multifunc_schedule'))
    elif case.startswith('mmc_after_f2_unbind_'):
        expected.update(bound=1, f2_bound=0, f2_driver=0, f2_data=0,
                        irq=1, lock_get=1, lock_put=1, host_calls=1,
                        power=1, reinit=1)
        if case.endswith('_eio'):
            expected.update(ret=-5, warnings=1)
        if case.endswith('_timeout'):
            expected.update(ret=-110, warnings=1)
    elif case in ('reset_bound_async', 'reset_bound_already_removed'):
        expected.update(transport=0, drvr=0, teardown=1, irq=1,
                        lock_get=1, lock_put=1, host_calls=2, removed=1,
                        rescan=int(case == 'reset_bound_async'),
                        disable=2, freezer=1, sg=1, pm_allow=1)
    elif case in UNBOUND or case == 'f2_remove_preserves_shared':
        expected.update(ret=-19, bound=1, f2_bound=0, f2_driver=0, f2_data=0,
                        irq=1, lock_get=2, lock_put=2)
        if case == 'f2_remove_preserves_shared':
            expected.update(ret=0, lock_get=1, lock_put=1)
    elif case == 'reset_lifecycle_busy':
        expected['ret'] = -16
    else:
        expected.update(ret=-16, lock_get=1, lock_put=1)
        if case == 'reset_pm_failed':
            expected['ret'] = -112
        if case == 'reset_no_transport':
            expected.update(ret=-19, transport=0)
    return expected


def baseline_metrics(case):
    observed = expected_metrics(case)
    if case in UNBOUND:
        observed.update(ret=0, teardown=1, irq=2, host_calls=2, power=1, reinit=1,
                        warnings=int(not case.endswith('_sync_refused')),
                        transport=0, drvr=0, disable=2, freezer=1, sg=1, pm_allow=1)
    return observed


# Every control must compile and fail exactly this case/assertion/value tuple.
# Observation overrides fix the complete numeric line; they are not substrings.
CONTROLS = {
    'omit_f2_guard': dict(case='reset_unbound_f2_sync_refused',
                         failure=('reset_errno', -19, 0)),
    'invert_f2_guard': dict(case='reset_bound_async',
                           failure=('reset_errno', 0, -19)),
    'wrong_owner_errno': dict(case='reset_unbound_f2_sync_refused',
                             failure=('reset_errno', -19, -5)),
    'late_irq_guard': dict(case='reset_unbound_f2_sync_refused',
                          failure=('irq_retirement', 1, 2)),
    'late_transport_guard': dict(case='reset_unbound_f2_sync_refused',
                                failure=('transport_retirement', 0, 1)),
    'missing_unlock': dict(case='reset_unbound_f2_sync_refused',
                          failure=('f2_lock', 0, 1)),
    'missing_host_release': dict(case='reset_bound_async',
                                failure=('host_balance', 0, 1)),
    'duplicate_rescan': dict(case='mmc_multifunc_schedule',
                            failure=('rescan_requests', 1, 2)),
}


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Expected one control target')
    return text.replace(before, after, 1)


def control_source(functions, name):
    declaration = ('static int mmc_sdio_hw_reset(' if name == 'duplicate_rescan'
                   else RESET)
    body = extract(functions, declaration)
    if name == 'omit_f2_guard':
        changed = replace_once(body, GUARD, '')
    elif name == 'invert_f2_guard':
        changed = replace_once(body, '!device_is_bound(f2dev)', 'device_is_bound(f2dev)')
    elif name == 'wrong_owner_errno':
        changed = replace_once(body, GUARD, GUARD.replace('-ENODEV', '-EIO'))
    elif name in ('late_irq_guard', 'late_transport_guard'):
        changed = replace_once(body, GUARD, '')
        call = ('\tbrcmf_sdiod_intr_unregister(sdiodev);\n' if name == 'late_irq_guard'
                else '\tbrcmf_sdiod_remove(sdiodev);\n')
        changed = replace_once(changed, call, call + GUARD)
    elif name == 'missing_unlock':
        changed = replace_once(body, '\tdevice_unlock(f2dev);',
                               '\t/* compiling control: omit unlock */')
    elif name == 'missing_host_release':
        changed = replace_once(body, '\tsdio_release_host(sdiodev->func1);',
                               '\t/* compiling control: omit host release */')
    elif name == 'duplicate_rescan':
        call = '\t\t_mmc_detect_change(host, 0, false);\n'
        changed = replace_once(body, call, call + call)
    else:
        raise ValueError('Unknown control')
    return replace_once(functions, body, changed)


def control_metrics(name):
    case = CONTROLS[name]['case']
    observed = expected_metrics(case)
    if name == 'omit_f2_guard':
        observed = baseline_metrics(case)
    elif name == 'invert_f2_guard':
        observed = expected_metrics('reset_pm_failed')
        observed['ret'] = -19
    elif name == 'wrong_owner_errno':
        observed['ret'] = -5
    elif name == 'late_irq_guard':
        observed['irq'] = 2
    elif name == 'late_transport_guard':
        observed.update(teardown=1, irq=2, transport=0, drvr=0, host_calls=1,
                        disable=2, freezer=1, sg=1, pm_allow=1)
    elif name == 'missing_unlock':
        observed.update(lock=1, lock_put=1)
    elif name == 'missing_host_release':
        observed['host'] = 1
    elif name == 'duplicate_rescan':
        observed['rescan'] = 2
    return observed


def formatted_output(case, metrics, failure=None):
    observation = 'OBSERVE case=' + case
    observation += ''.join(f' {name}={metrics[name]}' for name in METRICS)
    if failure is None:
        outcome = 'PASS case=' + case
    else:
        assertion, expected, observed = failure
        outcome = (f'FAIL case={case} assertion={assertion} '
                   f'expected={expected} observed={observed}')
    return observation + '\n' + outcome + '\n'


def admit_output(case, result, stdout, stderr, *, metrics=None, failure=None):
    raw_expected = 1 if failure is not None else 0
    if type(result['exit_code']) is not int or result['exit_code'] != raw_expected:
        raise ValueError('Unexpected original exit status')
    expected = formatted_output(case, metrics or expected_metrics(case), failure).encode()
    if stderr or stdout != expected:
        raise ValueError('Output differs from complete named numeric observation/result')
    return dict(case=case, expected_failure=failure, raw_exit_code=result['exit_code'],
                stdout_sha256=digest(stdout), stderr_sha256=digest(stderr))


def run_command(directory, label, command, *, environment=None):
    result = subprocess.run(command, cwd=directory, capture_output=True, env=environment)
    for suffix, data in (('stdout', result.stdout), ('stderr', result.stderr)):
        with (directory / (label + '.' + suffix)).open('xb') as stream:
            stream.write(data)
    record = dict(command=command, exit_code=result.returncode,
                  stdout_sha256=digest(result.stdout), stderr_sha256=digest(result.stderr))
    save(directory / (label + '.json'), record)
    return record, result.stdout, result.stderr


def observe(binary, case, directory, *, metrics=None, failure=None, environment=None):
    record, stdout, stderr = run_command(
        directory, case, [str(binary), case], environment=environment)
    # Raw output and its command result exist before any admission assertion.
    return admit_output(case, record, stdout, stderr, metrics=metrics, failure=failure)


def admit_saved(directory, case, *, metrics=None, failure=None):
    record = json.loads((directory / (case + '.json')).read_text())
    stdout = (directory / (case + '.stdout')).read_bytes()
    stderr = (directory / (case + '.stderr')).read_bytes()
    if record['stdout_sha256'] != digest(stdout) or record['stderr_sha256'] != digest(stderr):
        raise ValueError('Saved original output identity changed')
    return admit_output(case, record, stdout, stderr, metrics=metrics, failure=failure)


def compile_fixture(root, source, destination, *, sanitizer=False, control=None):
    destination.mkdir()
    types, functions = projection(source)
    if control is not None:
        functions = control_source(functions, control)
    (destination / 'reset-types.h').write_text(types)
    (destination / 'reset-functions.h').write_text(functions)
    shutil.copyfile(root / 'kernel/tests/brcmfmac_reset_test.c', destination / 'fixture.c')
    command = ['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
               '-Wno-unused-function', '-O0', '-g']
    if sanitizer:
        command += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    '-fno-pie', '-no-pie']
    command += ['fixture.c', '-o', 'fixture']
    record, _, _ = run_command(destination, 'compile', command)
    if record['exit_code'] != 0:
        raise RuntimeError('Original fixture compile failed; retained, not source qualification')
    save(destination / 'projection.json', dict(types_sha256=digest(types.encode()),
         functions_sha256=digest(functions.encode()),
         fixture_sha256=file_hash(destination / 'fixture.c'),
         binary_sha256=file_hash(destination / 'fixture'), command=command))
    return destination / 'fixture'


def qualify(root, baseline, candidate, destination, *, reference_only=False):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    output = {}
    baseline_dir = destination / 'baseline'
    binary = compile_fixture(root, baseline, baseline_dir)
    output['baseline'] = [
        observe(binary, case, baseline_dir, metrics=baseline_metrics(case),
                failure=('reset_errno', -19, 0) if case in UNBOUND else None)
        for case in CASES
    ]
    if not reference_only:
        for label, sanitizer in (('native', False), ('sanitizer', True)):
            directory = destination / label
            binary = compile_fixture(root, candidate, directory, sanitizer=sanitizer)
            environment = dict(os.environ)
            if sanitizer:
                environment.update(ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                                   UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
            output[label] = [observe(binary, case, directory, environment=environment)
                             for case in CASES]
        output['controls'] = {}
        for name, control in CONTROLS.items():
            directory = destination / ('control-' + name)
            binary = compile_fixture(root, candidate, directory, control=name)
            output['controls'][name] = observe(
                binary, control['case'], directory, metrics=control_metrics(name),
                failure=control['failure'])
    output['maximum_child_rss_kib'] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    if output['maximum_child_rss_kib'] > 256 * 1024:
        raise RuntimeError('Original native qualification exceeded 256 MiB child RSS budget')
    return output


# This bounded retained profile is production33+0057 from report314. Read-only
# file mounts remove0057 and add0073, without changing the retained tree.
RETAINED_TREE_SHA256 = '0cceb01121f80d4280114743c735e2fb3f8e6b37a88cb2f49f70a6032a617fa4'
OVERLAY_MEMBERS = frozenset(DRIVER + name for name in ('core.c', 'cfg80211.c', 'sdio.c'))
PHASE_LIMIT = 128 * 1024 ** 2
FREE_FLOOR = 3 * 1024 ** 3
NATIVE_FUNCTIONS = (
    'file_hash', 'digest', 'save', 'extract', 'projection', 'kernel_inputs',
    'selected_queue', 'prepare', 'expected_metrics', 'baseline_metrics',
    'replace_once', 'control_source', 'control_metrics', 'formatted_output',
    'admit_output', 'run_command', 'observe', 'admit_saved', 'compile_fixture', 'qualify',
)
NATIVE_CONSTANTS = (
    'DRIVER', 'CANDIDATE', 'SOURCE_FILES', 'FUNCTIONS', 'TYPES', 'CASES',
    'METRICS', 'UNBOUND', 'GUARD', 'RESET', 'CONTROLS',
)


def native_equivalence(root, original, revision, destination):
    """Admit unchanged genuine binaries/source, without rewriting old receipts."""
    import ast
    from kernel_sources import checked_file
    previous = json.loads(checked_file(original, 'result.json').read_text())
    recorded = json.loads(checked_file(original, 'inputs.json').read_text())
    source = json.loads(checked_file(original, 'sources.json').read_text())
    if previous['status'] != 'qualified-offline-candidate':
        raise ValueError('Require original complete native/sanitizer/control qualification')
    for name, expected in previous['artifacts'].items():
        if file_hash(checked_file(original, name)) != expected:
            raise ValueError('Original native artifact changed: ' + name)
    helper_name = 'tools/brcmfmac_reset_checks.py'
    old_helper = subprocess.check_output(['git', 'show', revision + ':' + helper_name], cwd=root)
    if digest(old_helper) != recorded['maintained'][helper_name]:
        raise ValueError('Native source revision does not identify original helper bytes')

    def nodes(text):
        result = {}
        for node in ast.parse(text).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result[node.name] = ast.dump(node, include_attributes=False)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        result[target.id] = ast.dump(node.value, include_attributes=False)
        return result

    old_nodes = nodes(old_helper)
    current_nodes = nodes((root / helper_name).read_text())
    if any(old_nodes[name] != current_nodes[name] for name in NATIVE_FUNCTIONS + NATIVE_CONSTANTS):
        raise ValueError('Native executable helper function/contract changed; new qualification required')
    if file_hash(root / 'kernel/tests/brcmfmac_reset_test.c') != recorded['maintained']['kernel/tests/brcmfmac_reset_test.c']:
        raise ValueError('Native C fixture changed')
    if file_hash(root / CANDIDATE) != source['candidate_patch_sha256']:
        raise ValueError('Native candidate patch changed')
    queue = list(kernel_inputs(root).patches())
    if source['production_queue'] != [dict(name=name, sha256=digest(data)) for name, data in queue]:
        raise ValueError('Native production queue differs')
    for label in ('baseline', 'native', 'sanitizer'):
        directory = original / label
        selected = original / ('baseline-source' if label == 'baseline' else 'candidate-source')
        types, functions = projection(selected)
        if ((directory / 'reset-types.h').read_text() != types or
                (directory / 'reset-functions.h').read_text() != functions):
            raise ValueError('Original generated native projection differs')
        for case in CASES:
            baseline = label == 'baseline'
            admit_saved(directory, case,
                        metrics=baseline_metrics(case) if baseline else None,
                        failure=('reset_errno', -19, 0) if baseline and case in UNBOUND else None)
    for name, control in CONTROLS.items():
        admit_saved(original / ('control-' + name), control['case'],
                    metrics=control_metrics(name), failure=control['failure'])
    save(destination / 'native-equivalence.json', dict(
        original_attempt=str(original), original_revision=revision,
        original_result_sha256=file_hash(original / 'result.json'),
        original_inputs=recorded['maintained'], current_inputs=inputs(root),
        native_helper_functions_unchanged=list(NATIVE_FUNCTIONS),
        native_contract_constants_unchanged=list(NATIVE_CONSTANTS),
        source_receipt_sha256=file_hash(original / 'sources.json'),
        current_saved_outputs_readmitted=56, historical_receipts_rewritten=False,
        note='Managed-only helper/CLI/tests/dependencies change; native bodies/types/fixture and raw executions stay historical.'))
    return original / 'candidate-source'


def derived_view_inventory(entries, replacement_hashes):
    expected = set(OVERLAY_MEMBERS) | {'.gameshellneo-patches.json'}
    if set(replacement_hashes) != expected:
        raise ValueError('Source view requires exactly three C files and the truthful patch stamp')
    view = dict(entries)
    for name, value in replacement_hashes.items():
        original = entries.get(name)
        if original is None or original[0] != 'file':
            raise ValueError('Readonly override must replace an existing regular member')
        if not re.fullmatch(r'[0-9a-f]{64}', value):
            raise ValueError('Invalid source-view hash')
        view[name] = ['file', original[1], value]
    return view


def prepare_source_view(root, receipt_path, candidate, destination):
    """Call while holding the existing retained source lock; never write it."""
    from kernel_sources import checked_file, digest as inventory_digest, inventory, source_spec
    retained = json.loads(receipt_path.read_text())
    source = Path(retained['path'])
    lock = json.loads((root / 'build/sources.lock.json').read_text())
    queue = list(kernel_inputs(root).patches())
    old_extra = root / 'kernel/candidates/0057-brcmfmac-eapol-ownership.patch'
    previous_queue = queue + [(old_extra.name, old_extra.read_bytes())]
    previous_manifest = [dict(name=name, sha256=digest(data)) for name, data in previous_queue]
    expected_spec = source_spec(lock, previous_manifest)
    metadata = json.loads(checked_file(source.parent, 'metadata.json').read_text())
    if (metadata != retained['metadata'] or metadata['spec'] != expected_spec or
            metadata['tree_sha256'] != RETAINED_TREE_SHA256):
        raise ValueError('Retained full source profile/identity differs')
    entries = inventory(source)
    if inventory_digest(entries) != metadata['tree_sha256']:
        raise ValueError('Retained source actual inventory changed')
    if json.loads(checked_file(source, '.gameshellneo-patches.json').read_text()) != previous_manifest:
        raise ValueError('Retained source stamp differs from its verified original profile')
    patch = (root / CANDIDATE).read_bytes()
    removed_targets = {item.decode() for item in re.findall(
        rb'^\+\+\+ b/([^\t\n]+)', old_extra.read_bytes(), re.M)}
    new_targets = {item.decode() for item in re.findall(rb'^\+\+\+ b/([^\t\n]+)', patch, re.M)}
    if removed_targets != {DRIVER + 'core.c', DRIVER + 'cfg80211.c'} or new_targets != {DRIVER + 'sdio.c'}:
        raise ValueError('Unexpected removed/new candidate target set')
    replacements = destination / 'source-overrides'
    replacements.mkdir()
    mounts = {}
    for name in sorted(OVERLAY_MEMBERS):
        original = checked_file(candidate, name)
        target = replacements / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        mounts[name] = target
    manifest = [dict(name=name, sha256=digest(data)) for name, data in
                queue + [(Path(CANDIDATE).name, patch)]]
    target = replacements / '.gameshellneo-patches.json'
    target.write_text(json.dumps(manifest, indent=2) + '\n')
    mounts['.gameshellneo-patches.json'] = target
    replacement_hashes = {name: file_hash(path) for name, path in mounts.items()}
    effective = derived_view_inventory(entries, replacement_hashes)
    selected_hashes = {name: file_hash(checked_file(candidate, name)) for name in SOURCE_FILES}
    if any(effective[name][2] != value for name, value in selected_hashes.items()):
        raise ValueError('Readonly source view differs from qualified native source')
    proof = dict(
        retained_source=str(source), retained_receipt=str(receipt_path),
        retained_receipt_sha256=file_hash(receipt_path), retained_metadata=metadata,
        base_inventory_sha256=inventory_digest(entries), effective_inventory_sha256=inventory_digest(effective),
        inventory_entries=len(entries), profile=source_spec(lock, manifest),
        replacement_hashes=replacement_hashes, selected_source_sha256=selected_hashes,
        overrides={name: str(path) for name, path in mounts.items()},
        old_objects_or_generated_headers_reused=False, source_cache_mutated=False)
    save(destination / 'source-view.json', proof)
    return source, mounts, proof


def stage_arguments(root, destination, source, mounts, lock):
    if set(mounts) != set(OVERLAY_MEMBERS) | {'.gameshellneo-patches.json'}:
        raise ValueError('Require exactly four readonly source overrides')
    builder = lock['builder']
    if builder['cross_compile'] != 'arm-linux-gnueabihf-' or builder['jobs'] != 1:
        raise ValueError('Require the pinned serial ARM builder')
    arguments = ['--pull=never', '--network', 'none', '--cpus=1', '--memory=3g',
                 '--user', f'{os.getuid()}:{os.getgid()}', '--platform', builder['platform'],
                 '--entrypoint', 'bash', '-v', f'{root}:/project:ro',
                 '-v', f'{source}:/kernel-source:ro',
                 '-v', f'{destination}:/qualification']
    for name in sorted(mounts):
        arguments += ['-v', f'{mounts[name]}:/kernel-source/{name}:ro']
    arguments += ['-e', 'KBUILD_BUILD_USER=gameshellneo', '-e', 'KBUILD_BUILD_HOST=builder',
                  '-e', 'LOCALVERSION=' + lock['linux']['localversion'],
                  '-w', '/qualification', builder['image'], '/qualification/stage.sh']
    return arguments


def check_arm_elf(text):
    for pattern in (r'Class:\s+ELF32\b', r'Data:\s+2.s complement, little endian\b',
                    r'Machine:\s+ARM\b', r'Flags:.*Version5 EABI'):
        if not re.search(pattern, text):
            raise ValueError('Wrong ARM32/LE/EABI5 ELF identity')


def check_driver_diagnostics(text):
    if re.search(r'(?im)\b(?:warning:|error:|AddressSanitizer|UndefinedBehaviorSanitizer)|runtime error:', text):
        raise ValueError('Original managed phase contains unexpected diagnostics')


def qualify_drivers(root, original, revision, reuse_receipt, destination):
    """One positive-only original managed operation; all inputs frozen."""
    from kernel_sources import digest as inventory_digest, inventory
    from managed_container import execute
    if shutil.disk_usage(root).free < FREE_FLOOR + PHASE_LIMIT:
        raise RuntimeError('Require 3 GiB free plus the full 128 MiB phase reservation')
    candidate = native_equivalence(root, original, revision, destination)
    retained = json.loads(reuse_receipt.read_text())
    source = Path(retained['path'])
    with locked(source.parents[2] / '.source-lock', existing=True):
        source, mounts, proof = prepare_source_view(root, reuse_receipt, candidate, destination)
        arm = destination / 'arm'
        arm.mkdir()
        types, functions = projection(candidate)
        (arm / 'reset-types.h').write_text(types)
        (arm / 'reset-functions.h').write_text(functions)
        for variant, debug in (('board', 'n'), ('debug', 'y')):
            directory = destination / variant
            directory.mkdir()
            (directory / 'extra.config').write_text('CONFIG_BRCMDBG=' + debug + '\n')
        (destination / 'capacity.py').write_text(
            'import os\nfrom pathlib import Path\n'
            'root=Path("/qualification")\n'
            'used=sum(p.lstat().st_blocks*512 for p in root.rglob("*"))\n'
            'free=os.statvfs(root).f_bavail*os.statvfs(root).f_frsize\n'
            'assert used<=134217728, "New phase exceeds128MiB"\n'
            'assert free>=3221225472+(134217728-used), "3GiB floor plus remaining reservation"\n')
        (destination / 'verify-view.py').write_text(
            'import hashlib,json\nfrom pathlib import Path\n'
            'root=Path("/kernel-source")\n'
            'proof=json.loads(Path("/qualification/source-view.json").read_text())\n'
            'pins=dict(proof["selected_source_sha256"]);pins.update(proof["replacement_hashes"])\n'
            'actual={}\n'
            'for name,value in pins.items():\n'
            '    with (root/name).open("rb") as stream: actual[name]=hashlib.file_digest(stream,"sha256").hexdigest()\n'
            'assert actual==pins, "Actual mounted source view differs"\n'
            'assert json.loads((root/".gameshellneo-patches.json").read_text())==proof["profile"]["patches"]\n'
            'Path("/qualification/mounted-source-observation.json").write_text(json.dumps(actual,sort_keys=True)+"\\n")\n')
        shell = (
            'set -euo pipefail\nulimit -c 0\n'
            'python3 /qualification/capacity.py\npython3 /qualification/verify-view.py\n'
            'cross=arm-linux-gnueabihf-\n'
            '"${cross}gcc" --version > /qualification/arm/compiler.txt\n'
            '"${cross}gcc" -std=gnu11 -O0 -g -Wall -Wextra -Werror -Wno-unused-function '
            '-static -I /qualification/arm /project/kernel/tests/brcmfmac_reset_test.c '
            '-o /qualification/arm/fixture\n'
            '"${cross}readelf" -h /qualification/arm/fixture > /qualification/arm/elf-info.txt\n'
            'for name in ' + ' '.join(CASES) + '; do\n'
            '  set +e\n'
            '  qemu-arm /qualification/arm/fixture "$name" > "/qualification/arm/$name.stdout" '
            '2> "/qualification/arm/$name.stderr"\n'
            '  code=$?\n  set -e\n'
            '  printf "%s\\n" "$code" > "/qualification/arm/$name.exit"\n'
            '  test "$code" -eq 0\n'
            'done\npython3 /qualification/capacity.py\n'
            'export ARCH=arm CROSS_COMPILE="$cross"\n'
            'for variant in board debug; do\n'
            '  python3 /qualification/capacity.py\n'
            '  output="/qualification/$variant/output"\n'
            '  make -C /kernel-source O="$output" sunxi_defconfig\n'
            '  /kernel-source/scripts/kconfig/merge_config.sh -m -O "$output" "$output/.config" '
            '/project/kernel/gameshellneo.config "/qualification/$variant/extra.config"\n'
            '  make -C /kernel-source O="$output" olddefconfig\n'
            '  python3 /project/tools/check-kernel-config.py "$output/.config"\n'
            '  python3 /qualification/capacity.py\n'
            '  make -C /kernel-source O="$output" -j1 ' + DRIVER + 'brcmfmac.o\n'
            '  "${cross}readelf" -h "$output/' + DRIVER + 'brcmfmac.o" > "/qualification/$variant/elf-info.txt"\n'
            'done\npython3 /qualification/capacity.py\n')
        (destination / 'stage.sh').write_text(shell)
        lock = json.loads((root / 'build/sources.lock.json').read_text())
        arguments = stage_arguments(root, destination, source, mounts, lock)
        stage_pins = {str(path.relative_to(destination)): file_hash(path)
                      for path in sorted(destination.rglob('*')) if path.is_file()}
        save(destination / 'managed-inputs.json', dict(arguments=arguments,
             maintained=inputs(root), files=stage_pins))
        managed = execute('brcmfmac-reset-drivers', arguments, destination / 'managed', timeout=None)
        check_driver_diagnostics((destination / 'managed/container.log').read_text())
        if any(file_hash(destination / name) != value for name, value in stage_pins.items()):
            raise RuntimeError('Managed phase input changed during original operation')
        if inventory_digest(inventory(source)) != proof['base_inventory_sha256']:
            raise RuntimeError('Retained immutable source changed during original operation')
        check_arm_elf((arm / 'elf-info.txt').read_text())
        outcomes = {}
        for case in CASES:
            stdout = (arm / (case + '.stdout')).read_bytes()
            stderr = (arm / (case + '.stderr')).read_bytes()
            if (arm / (case + '.exit')).read_text() != '0\n':
                raise RuntimeError('Original ARM outcome is not terminal0')
            outcomes[case] = admit_output(case, dict(exit_code=0), stdout, stderr)
            for suffix in ('stdout', 'stderr'):
                if (arm / (case + '.' + suffix)).read_bytes() != (original / 'native' / (case + '.' + suffix)).read_bytes():
                    raise RuntimeError('Original ARM/native output differs')
        objects = {}
        for variant, debug in (('board', 'n'), ('debug', 'y')):
            directory = destination / variant
            config_path = directory / 'output/.config'
            config = dict(re.findall(r'^(CONFIG_\w+)=([^\n]+)$', config_path.read_text(), re.M))
            if (config.get('CONFIG_BRCMFMAC') != 'm' or config.get('CONFIG_BRCMFMAC_SDIO') != 'y' or
                    config.get('CONFIG_BRCMDBG', 'n') != debug):
                raise RuntimeError('Requested complete driver configuration differs')
            check_arm_elf((directory / 'elf-info.txt').read_text())
            objects[variant] = dict(config_sha256=file_hash(config_path),
                object_sha256=file_hash(directory / ('output/' + DRIVER + 'brcmfmac.o')), brcmdbg=debug)
        used = sum(path.lstat().st_blocks * 512 for path in destination.rglob('*'))
        if used > PHASE_LIMIT or shutil.disk_usage(root).free < FREE_FLOOR:
            raise RuntimeError('Original phase violated its capacity reservation')
        return dict(managed=managed, arm=outcomes, objects=objects,
                    source_view=proof, arm_binary_sha256=file_hash(arm / 'fixture'),
                    old_source_postflight_matches=True, allocated_phase_bytes=used,
                    free_bytes_after=shutil.disk_usage(root).free)
