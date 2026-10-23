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
