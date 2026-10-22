"""Bounded, actual-source EAPOL drain checks; no kernel extraction or devices."""
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

from kernel_sources import atomic_json, ensure_source, locked

DRIVER = 'drivers/net/wireless/broadcom/brcm80211/brcmfmac/'
SOURCE_FILES = tuple(DRIVER + name for name in
                     ('core.c', 'core.h', 'cfg80211.c', 'cfg80211.h', 'fwil_types.h'))
CANDIDATE = 'kernel/candidates/0057-brcmfmac-eapol-ownership.patch'
CASES = (
    'empty_wait', 'drained_wait', 'timeout_single', 'timeout_multiple',
    'late_successful_completion', 'late_failed_completion',
    'old_plus_new_outstanding', 'wait_after_genuine_drain',
    'key_install_timeout_refused', 'key_delete_timeout_refused',
    'successful_key_bytes', 'firmware_errno_after_drain',
    'unrelated_frame_completion', 'interface_isolation',
)
BASELINE_FAILURES = frozenset((
    'timeout_single', 'timeout_multiple', 'late_successful_completion',
    'late_failed_completion', 'old_plus_new_outstanding',
    'wait_after_genuine_drain', 'key_install_timeout_refused',
    'key_delete_timeout_refused', 'interface_isolation',
))
FUNCTIONS = (
    ('core.c', 'static int brcmf_get_pend_8021x_cnt('),
    ('core.c', 'int brcmf_netdev_wait_pend8021x('),
    ('core.c', 'void brcmf_txfinalize('),
    ('cfg80211.c', 'static void convert_key_from_CPU('),
    ('cfg80211.c', 'static int\nsend_key_to_dongle('),
)
# Each mutation compiles the same fixture. Its named case must fail the
# specified contract assertion, rather than merely failing setup or compiling.
CONTROLS = {
    'reset_count': ('\t\treturn -ETIMEDOUT;',
                    '\t\tatomic_set(&ifp->pend_8021x_cnt, 0);\n\t\treturn -ETIMEDOUT;',
                    'timeout_single', ('pending_preserved', 1, 0)),
    'positive_timeout': ('\t\treturn -ETIMEDOUT;', '\t\treturn 1;',
                         'timeout_single', ('timeout_errno', -110, 1)),
    'ignored_drain': ('\tif (err)\n\t\treturn err;\n\n\terr = brcmf_fil_bsscfg_data_set',
                      '\t/* deliberately ignored drain */\n\n\terr = brcmf_fil_bsscfg_data_set',
                      'key_install_timeout_refused', ('no_key_write', 0, 1)),
    'missing_completion': ('\t\tatomic_dec(&ifp->pend_8021x_cnt);',
                           '\t\t/* deliberately missing completion */',
                           'drained_wait', ('genuine_completion', 0, 2)),
    'inverted_frame_type': ('\tif (type == ETH_P_PAE) {', '\tif (type != ETH_P_PAE) {',
                            'unrelated_frame_completion', ('unrelated_count', 1, 0)),
    'lost_firmware_errno': ('\treturn err;\n}', '\treturn 0;\n}',
                            'firmware_errno_after_drain', ('firmware_errno', -5, 0)),
    'corrupt_key_index': ('key_le->index = cpu_to_le32(key->index);',
                          'key_le->index = cpu_to_le32(key->index + 1);',
                          'successful_key_bytes', ('wire_index', 305419896, 305419897)),
}
MAINTAINED = (
    CANDIDATE, 'kernel/tests/brcmfmac_eapol_test.c',
    'kernel/tests/brcmfmac_eapol_reference_test.c',
    'tools/brcmfmac_eapol_checks.py', 'tools/check-brcmfmac-eapol.py',
    'tools/tests/test_brcmfmac_eapol.py', 'tools/kernel-inputs.py',
    'tools/kernel_sources.py', 'build/sources.lock.json', 'Taskfile.yml',
    'kernel/gameshellneo.config', 'tools/managed_container.py', 'tools/docker-stage.py',
    'tools/run-logged.sh', 'tools/build-bin/docker', 'tools/check-kernel-config.py',
    'tools/keypad_supply.py',
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inputs(root):
    return {name: file_hash(root / name) for name in MAINTAINED}


def kernel_inputs(root):
    spec = importlib.util.spec_from_file_location('eapol_kernel_inputs', root / 'tools/kernel-inputs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def selected_queue(queue):
    selected = []
    files = set(SOURCE_FILES)
    for name, data in queue:
        targets = {path.decode() for path in re.findall(rb'^\+\+\+ b/([^\t\n]+)', data, re.M)}
        if targets & files:
            if not targets <= files:
                raise ValueError('Selected patch also changes an unprojected file: ' + name)
            selected.append((name, data))
    if not selected:
        raise ValueError('No production driver patches selected')
    return selected


def prepare(root, archive, destination):
    """Verify the whole locked archive, extract five files, replay whole patches."""
    lock = json.loads((root / 'build/sources.lock.json').read_text())
    if not archive.is_file() or archive.is_symlink():
        raise ValueError('Supply an existing regular locked Linux archive with --archive')
    archive_sha = file_hash(archive)
    if archive_sha != lock['linux']['tarball_sha256']:
        raise ValueError('Locked Linux archive hash mismatch')
    module = kernel_inputs(root)
    queue = list(module.patches())
    selected = selected_queue(queue)
    upstream = destination / 'upstream'
    upstream.mkdir()
    prefix = 'linux-' + lock['linux']['tag'].removeprefix('v') + '/'
    original = {}
    with tarfile.open(archive, 'r|xz') as source:
        # Streaming prevents a large archive-member inventory allocation.
        wanted = {prefix + name: name for name in SOURCE_FILES}
        for member in source:
            source.members.clear()
            if member.name not in wanted:
                continue
            name = wanted.pop(member.name)
            if not member.isfile():
                raise ValueError('Expected regular archive source file: ' + name)
            data = source.extractfile(member).read()
            path = upstream / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            original[name] = digest(data)
            if not wanted:
                break
        if wanted:
            raise ValueError('Locked archive lacks selected files')
    baseline = destination / 'baseline-source'
    shutil.copytree(upstream, baseline)
    module.apply_queue(baseline, selected)
    candidate = destination / 'candidate-source'
    shutil.copytree(baseline, candidate)
    module.apply_queue(candidate, [(Path(CANDIDATE).name, (root / CANDIDATE).read_bytes())])
    return baseline, candidate, dict(
        archive=str(archive), archive_sha256=archive_sha, upstream=original,
        production_queue=[dict(name=name, sha256=digest(data)) for name, data in queue],
        selected_patches=[dict(name=name, sha256=digest(data)) for name, data in selected],
        baseline={name: file_hash(baseline / name) for name in SOURCE_FILES},
        candidate={name: file_hash(candidate / name) for name in SOURCE_FILES},
        candidate_patch_sha256=file_hash(root / CANDIDATE),
    )


def extract(source, declaration, end='\n}'):
    matches = list(re.finditer(r'^' + re.escape(declaration), source, re.M))
    if len(matches) != 1:
        raise ValueError('Expected exactly one actual declaration: ' + declaration)
    start = matches[0].start()
    finish = source.index(end, start) + len(end)
    return source[start:finish] + '\n'


def deadline(source):
    timeout = re.findall(r'^#define MAX_WAIT_FOR_8021X_TX[^\n]*$', source, re.M)
    if (len(timeout) != 1 or not re.fullmatch(
            r'#define MAX_WAIT_FOR_8021X_TX[ \t]+msecs_to_jiffies\(950\)', timeout[0])):
        raise ValueError('Unexpected actual EAPOL wait deadline')
    return timeout[0]


def projection(source):
    files = {name: (source / DRIVER / name).read_text() for name in
             ('core.c', 'cfg80211.c', 'fwil_types.h')}
    types = ''.join(extract(files['fwil_types.h'], 'struct ' + name + ' {', '\n};')
                    for name in ('brcmf_wsec_key', 'brcmf_wsec_key_le'))
    functions = deadline(files['core.c']) + '\n' + ''.join(extract(files[name], declaration)
                                            for name, declaration in FUNCTIONS)
    return types, functions


def mutate(functions, control):
    old, new, _, _ = CONTROLS[control]
    if functions.count(old) != 1:
        raise ValueError('Control target is not unique: ' + control)
    return functions.replace(old, new, 1)


def command(argv, destination, name, *, timeout=60, env=None):
    with (destination / (name + '.stdout')).open('w') as stdout, \
         (destination / (name + '.stderr')).open('w') as stderr:
        result = subprocess.run(argv, stdout=stdout, stderr=stderr, text=True,
                                timeout=timeout, env=env)
    record = dict(command=argv, returncode=result.returncode,
                  stdout_sha256=file_hash(destination / (name + '.stdout')),
                  stderr_sha256=file_hash(destination / (name + '.stderr')))
    atomic_json(destination / (name + '.json'), record)
    return record


def compiler_flags(sanitizer=False):
    flags = ['-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
             '-ftrivial-auto-var-init=pattern']
    if sanitizer:
        flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                  '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    return flags


def compile_fixture(root, source, destination, *, reference=False, sanitizer=False, control=None):
    destination.mkdir()
    types, functions = projection(source)
    if control:
        functions = mutate(functions, control)
    (destination / 'eapol_types.h').write_text(types)
    (destination / 'eapol_functions.h').write_text(functions)
    fixture = root / ('kernel/tests/brcmfmac_eapol_reference_test.c' if reference
                      else 'kernel/tests/brcmfmac_eapol_test.c')
    binary = destination / 'fixture'
    record = command(['cc', *compiler_flags(sanitizer), '-I', str(destination), str(fixture), '-o', str(binary)],
                     destination, 'compile')
    if record['returncode']:
        raise RuntimeError('Fixture compile failed: ' + str(destination))
    return binary


def validate_case(result, output, error, name, *, failure=False, assertion=None):
    expected = 1 if failure else 0
    integer = r'-?(?:0|[1-9][0-9]*)'
    count = r'(?:0|[1-9][0-9]*)'
    case = re.escape(name)
    observation = (rf'OBSERVE {case} result={integer} pending={integer} other_pending={integer} '
                   rf'firmware_calls={count} frees={count} barriers={count} wakes={count} tx_errors={count}\n')
    terminal = (rf'FAIL {case} [a-z_]+ expected={integer} actual={integer}' if failure else
                'PASS ' + case)
    if (type(result['returncode']) is not int or result['returncode'] != expected or error or
            not re.fullmatch(observation + terminal + r'\n', output)):
        raise RuntimeError('Unexpected actual fixture outcome: ' + name)
    if assertion:
        label, expected_value, actual_value = assertion
        exact = f'FAIL {name} {label} expected={expected_value} actual={actual_value}'
        if exact not in output.splitlines():
            raise RuntimeError('Control failed a different assertion/value: ' + name)


def observe_cases(binary, destination, *, failures=frozenset(), only=None, assertion=None):
    results = {}
    for name in only or CASES:
        result = command([str(binary), name], destination, name, timeout=30)
        output = (destination / (name + '.stdout')).read_text()
        error = (destination / (name + '.stderr')).read_text()
        expected = 1 if name in failures else 0
        validate_case(result, output, error, name, failure=bool(expected), assertion=assertion)
        results[name] = result
        print(f'{destination.name}/{name}: ' + ('expected failure' if expected else 'PASS'), flush=True)
    atomic_json(destination / 'cases.json', results)
    return results


def qualify(root, baseline, candidate, destination, *, reference_only=False):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    results = {}
    for label, source, reference, sanitizer, control in (
            [('baseline', baseline, True, False, None)] if reference_only else
            [('candidate', candidate, False, False, None),
             ('sanitizer', candidate, False, True, None)] +
            [(name, candidate, False, False, name) for name in CONTROLS]):
        directory = destination / label
        binary = compile_fixture(root, source, directory, reference=reference,
                                 sanitizer=sanitizer, control=control)
        if reference:
            cases = observe_cases(binary, directory, failures=BASELINE_FAILURES)
        elif control:
            _, _, name, assertion = CONTROLS[control]
            cases = observe_cases(binary, directory, failures={name}, only=(name,), assertion=assertion)
        else:
            cases = observe_cases(binary, directory)
        results[label] = dict(binary_sha256=file_hash(binary),
                              types_sha256=file_hash(directory / 'eapol_types.h'),
                              functions_sha256=file_hash(directory / 'eapol_functions.h'),
                              cases=cases)
    return results


def check_arm_elf(text):
    if not (re.search(r'^\s*Class:\s+ELF32\s*$', text, re.M) and
            re.search(r'^\s*Machine:\s+ARM\s*$', text, re.M)):
        raise ValueError('Expected an ARM32 ELF artifact')


def admit_native(root, candidate, destination, previous):
    """Prove exact executable closure; retain original execution provenance."""
    previous = previous.resolve()
    if previous.parent != destination.parent.resolve() or previous == destination.resolve():
        raise ValueError('Native evidence must be a distinct retained attempt in this suite')
    record = json.loads((previous / 'result.json').read_text())
    source = json.loads((previous / 'sources.json').read_text())
    current = inputs(root)
    if record.get('status') != 'passed':
        raise ValueError('Native evidence is not an accepted original execution')
    host_delta = {'tools/brcmfmac_eapol_checks.py', 'tools/check-brcmfmac-eapol.py',
                  'tools/tests/test_brcmfmac_eapol.py'}
    changed = {name for name, value in record['inputs'].items() if current.get(name) != value}
    if changed - host_delta:
        raise ValueError('Native executable dependency changed: ' + str(sorted(changed - host_delta)))
    # Do not trust a source stamp or ancestry: compare actual current and original
    # five-file sources, extracted types/bodies, exact compile flags, fixture,
    # original binaries, command outcomes and every retained output hash.
    expected_files = {name: file_hash(candidate / name) for name in SOURCE_FILES}
    if (source['candidate'] != expected_files or
            {name: file_hash(previous / 'candidate-source' / name) for name in SOURCE_FILES} != expected_files):
        raise ValueError('Native source files differ from current selected source')
    types, functions = projection(candidate)
    observed = {}
    for label in ('candidate', 'sanitizer', *CONTROLS):
        original = record['results'][label]
        directory = previous / label
        expected_functions = mutate(functions, label) if label in CONTROLS else functions
        if ((directory / 'eapol_types.h').read_text() != types or
                (directory / 'eapol_functions.h').read_text() != expected_functions or
                original['types_sha256'] != digest(types.encode()) or
                original['functions_sha256'] != digest(expected_functions.encode()) or
                file_hash(directory / 'fixture') != original['binary_sha256']):
            raise ValueError('Native generated input/binary differs: ' + label)
        compile_record = json.loads((directory / 'compile.json').read_text())
        expected_command = ['cc', *compiler_flags(label == 'sanitizer'), '-I', str(directory),
                            str(root / 'kernel/tests/brcmfmac_eapol_test.c'), '-o', str(directory / 'fixture')]
        if (compile_record['command'] != expected_command or compile_record['returncode'] != 0 or
                any(file_hash(directory / ('compile.' + extension)) != compile_record[extension + '_sha256']
                    for extension in ('stdout', 'stderr'))):
            raise ValueError('Native compile provenance differs: ' + label)
        names = (CONTROLS[label][2],) if label in CONTROLS else CASES
        if set(original['cases']) != set(names):
            raise ValueError('Native case inventory differs: ' + label)
        for name in names:
            case = original['cases'][name]
            if (case != json.loads((directory / (name + '.json')).read_text()) or
                    case['command'] != [str(directory / 'fixture'), name] or
                    any(file_hash(directory / (name + '.' + extension)) != case[extension + '_sha256']
                        for extension in ('stdout', 'stderr'))):
                raise ValueError('Native case provenance differs: ' + label + '/' + name)
            validate_case(case, (directory / (name + '.stdout')).read_text(),
                          (directory / (name + '.stderr')).read_text(), name,
                          failure=label in CONTROLS,
                          assertion=CONTROLS[label][3] if label in CONTROLS else None)
        observed[label] = dict(binary_sha256=original['binary_sha256'], cases=list(names))
    generated = destination / 'candidate'
    generated.mkdir()
    (generated / 'eapol_types.h').write_text(types)
    (generated / 'eapol_functions.h').write_text(functions)
    proof = dict(original_attempt=str(previous), original_result_sha256=file_hash(previous / 'result.json'),
                 original_sources_sha256=file_hash(previous / 'sources.json'),
                 source_files=expected_files, types_sha256=digest(types.encode()),
                 functions_sha256=digest(functions.encode()), verified=observed,
                 changed_host_inputs=sorted(changed), added_host_inputs=sorted(set(current) - set(record['inputs'])),
                 limits='Read-only current admission of original native/sanitizer/control executions; no new execution or current historical receipt claim.')
    atomic_json(destination / 'native-provenance-equivalence.json', proof)
    return proof


def qualify_drivers(root, archive, candidate, destination, original_native):
    """One owned, serial, offline ARM fixture + complete normal/debug objects."""
    from managed_container import execute
    lock = json.loads((root / 'build/sources.lock.json').read_text())
    if shutil.disk_usage(root).free < 3 * 1024 ** 3:
        raise RuntimeError('Full source/object qualification requires at least 3 GiB free')
    module = kernel_inputs(root)
    queue = list(module.patches())
    if Path(CANDIDATE).name in {name for name, _ in queue}:
        raise ValueError('EAPOL candidate unexpectedly entered the image queue')
    queue.append((Path(CANDIDATE).name, (root / CANDIDATE).read_bytes()))
    manifest = [dict(name=name, sha256=digest(data)) for name, data in queue]
    work = destination.parent
    with locked(work / '.source-lock'):
        source, _, metadata = ensure_source(root, work, archive, lock, manifest, recorded_patches=queue)
    equivalent = {name: file_hash(source / name) for name in SOURCE_FILES}
    if equivalent != {name: file_hash(candidate / name) for name in SOURCE_FILES}:
        raise RuntimeError('Full driver source differs from the qualified native projection')
    atomic_json(destination / 'full-source.json', dict(path=str(source), metadata=metadata,
                                                     projected_file_sha256=equivalent))
    arm = destination / 'arm'
    arm.mkdir()
    for name in ('board', 'debug'):
        directory = destination / name
        directory.mkdir()
        (directory / 'extra.config').write_text('CONFIG_BRCMDBG=' + ('y' if name == 'debug' else 'n') + '\n')
    relative = destination.relative_to(root).as_posix()
    # All paths interpolated into shell code are fixed or generated hex paths
    # below .local; assert this rather than relying on JSON as shell escaping.
    if not re.fullmatch(r'[A-Za-z0-9_./-]+', relative):
        raise ValueError('Unexpected generated qualification path')
    shell = (
        'set -euo pipefail\nulimit -c 0\n'
        f'attempt=/project/{relative}\n'
        'cross=arm-linux-gnueabihf-\n'
        '"${cross}gcc" --version > "$attempt/arm/compiler.txt"\n'
        '"${cross}gcc" -std=gnu11 -O1 -g -Wall -Wextra -Werror -static '
        '-ftrivial-auto-var-init=pattern -I "$attempt/candidate" '
        '/project/kernel/tests/brcmfmac_eapol_test.c -o "$attempt/arm/fixture"\n'
        '"${cross}readelf" -h "$attempt/arm/fixture" > "$attempt/arm/elf-info.txt"\n'
        'for name in ' + ' '.join(CASES) + '; do\n'
        '  qemu-arm "$attempt/arm/fixture" "$name" > "$attempt/arm/$name.stdout" '
        '2> "$attempt/arm/$name.stderr"\n'
        'done\n'
        'export ARCH=arm CROSS_COMPILE="$cross"\n'
        'for variant in board debug; do\n'
        '  output="$attempt/$variant/output"\n'
        '  make -C /kernel-source O="$output" sunxi_defconfig\n'
        '  /kernel-source/scripts/kconfig/merge_config.sh -m -O "$output" '
        '"$output/.config" /project/kernel/gameshellneo.config "$attempt/$variant/extra.config"\n'
        '  make -C /kernel-source O="$output" olddefconfig\n'
        '  python3 /project/tools/check-kernel-config.py "$output/.config"\n'
        '  make -C /kernel-source O="$output" -j1 drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.o\n'
        '  "${cross}readelf" -h "$output/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.o" '
        '> "$attempt/$variant/elf-info.txt"\n'
        'done\n')
    builder = lock['builder']
    if builder['cross_compile'] != 'arm-linux-gnueabihf-' or builder['jobs'] != 1:
        raise ValueError('Expected the locked serial ARMHF builder')
    arguments = ['--pull=never', '--network', 'none', '--cpus=1', '--memory=3g',
                 '--user', f'{os.getuid()}:{os.getgid()}', '--platform', builder['platform'],
                 '--entrypoint', 'bash', '-v', f'{root}:/project', '-v', f'{source}:/kernel-source:ro',
                 '-e', 'KBUILD_BUILD_USER=gameshellneo', '-e', 'KBUILD_BUILD_HOST=builder',
                 '-e', 'LOCALVERSION=' + lock['linux']['localversion'],
                 '-w', '/project', builder['image'], '-c', shell]
    # Positive-only managed outcome: every error, timeout and unresolved
    # ownership propagates. No nonzero fallback or historical output admission.
    managed = execute('brcmfmac-eapol-drivers', arguments, destination / 'managed', timeout=3600)
    check_arm_elf((arm / 'elf-info.txt').read_text())
    for name in CASES:
        for extension in ('stdout', 'stderr'):
            if (arm / (name + '.' + extension)).read_bytes() != (
                    original_native / 'candidate' / (name + '.' + extension)).read_bytes():
                raise RuntimeError('Native/ARM outcome differs: ' + name)
    objects = {}
    for name, debug in (('board', 'n'), ('debug', 'y')):
        directory = destination / name
        config = (directory / 'output/.config').read_text()
        actual = dict(re.findall(r'^(CONFIG_\w+)=([^\n]+)$', config, re.M))
        if (actual.get('CONFIG_BRCMDBG', 'n') != debug or
                actual.get('CONFIG_BRCMFMAC') != 'm' or actual.get('CONFIG_BRCMFMAC_SDIO') != 'y'):
            raise RuntimeError('Requested complete driver configuration was not applied: ' + name)
        check_arm_elf((directory / 'elf-info.txt').read_text())
        objects[name] = dict(config_sha256=file_hash(directory / 'output/.config'),
            object_sha256=file_hash(directory / ('output/' + DRIVER + 'brcmfmac.o')),
            brcmdbg=debug)
    if {name: file_hash(source / name) for name in SOURCE_FILES} != equivalent:
        raise RuntimeError('Full source changed during driver compilation')
    return dict(managed_result=managed, source=metadata, objects=objects,
                arm_binary_sha256=file_hash(arm / 'fixture'),
                arm_cases=list(CASES), builder=builder)
