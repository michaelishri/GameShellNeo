"""Real Linux managed-wakeup ownership, exact control, and selected ARM builds."""
from collections import Counter
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import uuid

from kernel_checks import check_overrides, sha256
from kernel_sources import atomic_json, ensure_source, locked
from managed_container import execute
from managed_wakeup_init_source import CASES, CONTROL_FAILURES, HEADER, PATCH, function
from musb_restart_kunit import checked_cases as validate_cases

STEM = 'managed-wakeup-init'
TARGETS = (HEADER, 'drivers/base/power/wakeup.c', 'drivers/base/devres.c', 'kernel/power/Kconfig')
LIMITS = ('Five synchronous calls on valid registered, unbound devices in single-CPU UML '
          'with real wakeup registration/attachment, IDA, devres/reset and device release, '
          'KASAN and lockdep. Test-only allocation failures match the exact fixture, caller '
          'task and action identity; observer lifetime is protected by a short spinlock. '
          'No concurrent capability/policy/unbind, DPM, MUSB/IRQ, image or hardware claim.')


def changed(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Managed-wakeup test boundary changed: ' + old)
    return text.replace(old, new)


def test_patch(root, archive, lock, queue, apply_queue, scratch):
    """One shared source: config selects exact original or patched inline body."""
    candidate = PATCH.rsplit('/', 1)[-1]
    if not queue or queue[-1][0] != candidate or sum(name == candidate for name, _ in queue) != 1:
        raise ValueError('Exactly one final explicit 0072 candidate is required')
    prefix = 'linux-' + lock['linux']['tag'].removeprefix('v') + '/'
    remaining = set(TARGETS)
    with tarfile.open(archive, 'r|xz') as stream:
        for member in stream:
            relative = member.name.removeprefix(prefix)
            if relative in remaining and member.name == prefix + relative:
                path = scratch / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(stream.extractfile(member).read())
                remaining.remove(relative)
                if not remaining:
                    break
    if remaining:
        raise ValueError('Missing actual Linux managed-wakeup dependencies')
    relevant = []
    for name, data in queue[:-1]:
        chunks = re.split(r'(?=^diff --git )', data.decode(), flags=re.M)
        selected = [chunk for chunk in chunks if any(
            chunk.startswith('diff --git a/' + target + ' ') for target in TARGETS)]
        if selected:
            relevant.append((name, ''.join(selected).encode()))
    if relevant:
        apply_queue(scratch, relevant)
    original_inline = function((scratch / HEADER).read_text(), 'devm_device_init_wakeup')
    apply_queue(scratch, [queue[-1]])
    originals = {name: (scratch / name).read_text() for name in TARGETS}
    candidate_inline = function(originals[HEADER], 'devm_device_init_wakeup')
    if original_inline == candidate_inline:
        raise ValueError('Candidate did not change managed-wakeup initialization')
    header = changed(originals[HEADER], candidate_inline,
        '#ifdef CONFIG_NEO_MANAGED_WAKEUP_RETURN_IGNORED\n' + original_inline +
        '#else\n' + candidate_inline + '#endif\n')
    wakeup = changed(originals['drivers/base/power/wakeup.c'],
        'static DEFINE_IDA(wakeup_ida);\n',
        'static DEFINE_IDA(wakeup_ida);\n\n#include "managed-wakeup-init-kunit.h"\n')
    wakeup = changed(wakeup, '\tws = kzalloc(sizeof(*ws), GFP_KERNEL);',
        '\tws = neo_managed_wakeup_source_fail(name) ? NULL :\n'
        '\t\tkzalloc(sizeof(*ws), GFP_KERNEL);')
    wakeup = changed(wakeup, '\tws->id = id;\n',
                     '\tws->id = id;\n\tneo_managed_wakeup_created(ws);\n')
    wakeup = changed(wakeup, '\tida_free(&wakeup_ida, ws->id);',
        '\tneo_managed_wakeup_freeing(ws);\n\tida_free(&wakeup_ida, ws->id);')
    wakeup += ('\n#ifdef CONFIG_NEO_MANAGED_WAKEUP_INIT_KUNIT_TEST\n'
               '#include "managed-wakeup-init-kunit.c"\n#endif\n')
    devres = changed(originals['drivers/base/devres.c'], '#include <linux/device.h>\n',
        '#include <linux/device.h>\n#include "power/managed-wakeup-init-kunit.h"\n')
    devres = changed(devres,
        '\tdevres = __devres_alloc_node(devm_action_release, sizeof(struct action_devres),\n'
        '\t\t\t\t     GFP_KERNEL, NUMA_NO_NODE, name);',
        '\tdevres = neo_managed_wakeup_action_fail(dev, action, data) ? NULL :\n'
        '\t\t__devres_alloc_node(devm_action_release, sizeof(struct action_devres),\n'
        '\t\t\t\t    GFP_KERNEL, NUMA_NO_NODE, name);')
    kconfig = originals['kernel/power/Kconfig'] + '''
config NEO_MANAGED_WAKEUP_INIT_KUNIT_TEST
\tbool "Managed wakeup initialization tests (isolated kernel only)"
\tdepends on KUNIT=y && PM_SLEEP && SYSFS

config NEO_MANAGED_WAKEUP_RETURN_IGNORED
\tbool "Original return-ignored managed wakeup control"
\tdepends on NEO_MANAGED_WAKEUP_INIT_KUNIT_TEST
'''
    replacements = {HEADER: (originals[HEADER], header),
        'drivers/base/power/wakeup.c': (originals['drivers/base/power/wakeup.c'], wakeup),
        'drivers/base/devres.c': (originals['drivers/base/devres.c'], devres),
        'kernel/power/Kconfig': (originals['kernel/power/Kconfig'], kconfig)}
    for name in ('managed-wakeup-init-kunit.c', 'managed-wakeup-init-kunit.h'):
        replacements['drivers/base/power/' + name] = ('', (root / 'kernel/tests' / name).read_text())
    patch = ''.join(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile='a/' + name if before else '/dev/null', tofile='b/' + name))
        for name, (before, after) in replacements.items())
    return '9999-managed-wakeup-init-test-only.patch', patch.encode()


def ownership_observations(log, *, control):
    expected = {
        CASES[0]: 'result=0 source_hits=0 action_hits=0 created=1 freed=1',
        CASES[1]: ('result=0 action=1 capable=0' if control else 'result=-12 action=0 capable=1') +
                  ' source_hits=1 action_hits=0 created=0 freed=0',
        CASES[2]: ('result=0 action=1 source=0 id=0 capable=0' if control else
                   'result=-17 action=0 source=1 id=1 capable=1') +
                  (' source_hits=0 action_hits=0 created=2 freed=2' if control else
                   ' source_hits=0 action_hits=0 created=2 freed=1'),
        CASES[3]: 'result=-12 source_hits=0 action_hits=1 created=1 freed=1',
        CASES[4]: 'result=0 source_hits=0 action_hits=0 created=1 freed=1',
    }
    actual = re.findall(r'#\s*(\w+_test): ownership ([^\n]+)', log)
    if Counter(actual) != Counter(expected.items()):
        raise ValueError('Different or missing actual managed-wakeup ownership observation')


def checked_cases(report, log):
    cases = validate_cases(report, log, suite_name=STEM, expected_cases=CASES)
    ownership_observations(log, control=False)
    return cases


def checked_control(report, log):
    counts = dict(tests=5, passed=3, failed=2, crashed=0, skipped=0, errors=0)
    if re.search(r'WARNING:|BUG:|possible circular locking|suspicious RCU|'
                 r'sleeping function called|Kernel panic|rcu:.*detected .*stalls|'
                 r'INFO: task .*blocked for more than', log):
        raise ValueError('Kernel diagnostic invalidates managed-wakeup control')
    if (not isinstance(report, dict) or report.get('name') != 'KUnit Test Group' or
            report.get('arch') != 'um' or report.get('misc') != counts or
            report.get('test_cases') != [] or len(report.get('sub_groups', [])) != 1):
        raise ValueError('Expected complete executed managed-wakeup control')
    suite = report['sub_groups'][0]
    cases = suite.get('test_cases', [])
    if (suite.get('name') != STEM or suite.get('arch') != 'um' or suite.get('misc') != counts or
            suite.get('sub_groups') != [] or tuple(case.get('name') for case in cases) != CASES or
            any(case.get('status') != ('FAIL' if case.get('name') in CONTROL_FAILURES else 'PASS')
                for case in cases)):
        raise ValueError('Different or incomplete managed-wakeup control outcomes')
    failures, active = [], None
    for line in log.splitlines():
        marker = re.match(r'\s*#\s*(\w+_test): (?:ASSERTION|EXPECTATION) FAILED', line)
        if marker:
            active = [marker[1], []]
            failures.append(active)
        elif re.match(r'\s*(?:not )?ok\s+\d+', line) or re.match(r'\s*#.*: ownership ', line):
            active = None
        if active is not None:
            active[1].append(line.strip())
    expected = []
    for case, assertions in CONTROL_FAILURES.items():
        for name, actual, wanted in assertions:
            lines = ([f'Expected result == {wanted}, but', 'result == 0 (0x0)'] if name == 'result'
                     else [f'Expected {name} to be {"true" if wanted else "false"}, '
                           f'but is {"true" if actual else "false"}'])
            expected.append((case, tuple(lines)))
    parsed = []
    for case, block in failures:
        marker = (r'# ' + re.escape(case) + r': EXPECTATION FAILED at '
                  r'drivers/base/power/managed-wakeup-init-kunit\.c:[1-9][0-9]*')
        if not block or not re.fullmatch(marker, block[0]):
            raise ValueError('Unexpected managed-wakeup compiled assertion boundary')
        parsed.append((case, tuple(line for line in block[1:] if line)))
    if Counter(parsed) != Counter(expected):
        raise ValueError('Different or incomplete eight-assertion managed-wakeup control')
    ownership_observations(log, control=True)
    return cases


def resources(root, work):
    """Admission/receipt only: never terminate a writer to recover disk space."""
    used = sum(path.lstat().st_blocks * 512 for path in work.rglob('*') if not path.is_symlink())
    free = shutil.disk_usage(root).free
    if free < 3 * 1024**3 or used > 4 * 1024**3:
        raise RuntimeError('Managed-wakeup stage exceeds admitted disk budget; retain all artifacts')
    return dict(free_bytes=free, qualification_allocated_bytes=used)


def production_pins(root):
    paths = [*sorted((root / 'kernel/patches').glob('*.patch')),
             *sorted(path for path in (root / 'kernel/overlay').rglob('*') if path.is_file()),
             *(root / 'kernel/candidates/clock-provenance' / name
               for name in ('hooks.patch', 'neo-clock-diag.c', 'neo-clock-diag.h'))]
    return {str(path.relative_to(root)): sha256(path) for path in paths}


def kernel_source(root, lock, archive):
    base = root / '.local/build/managed-wakeup-init-kernel'
    base.mkdir(parents=True, exist_ok=True)
    resources(root, base)
    spec = importlib.util.spec_from_file_location('managed_wakeup_kernel_inputs', root / 'tools/kernel-inputs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    queue = list(module.patches())
    candidate = root / PATCH
    queue.append((candidate.name, candidate.read_bytes()))
    with tempfile.TemporaryDirectory(dir=base) as temporary:
        queue.append(test_patch(root, archive, lock, queue, module.apply_queue, Path(temporary)))
    manifest = [dict(name=name, sha256=hashlib.sha256(data).hexdigest()) for name, data in queue]
    with locked(base / '.source-lock'):
        source, entries, metadata = ensure_source(root, base, archive, lock, manifest, recorded_patches=queue)
        inventory_file = base / ('inventory-' + metadata['tree_sha256'] + '.json')
        if inventory_file.exists():
            if json.loads(inventory_file.read_text()) != entries:
                raise ValueError('Retained source inventory changed')
        else:
            atomic_json(inventory_file, entries)
        for name, data in queue[-2:]:
            path = base / (hashlib.sha256(data).hexdigest() + '-' + name)
            if path.exists() and path.read_bytes() != data:
                raise ValueError('Retained kernel patch changed')
            if not path.exists():
                path.write_bytes(data)
    return base, source, dict(path=str(source.relative_to(root)), **metadata,
        inventory_file=str(inventory_file.relative_to(root)), inventory_sha256=sha256(inventory_file))


def driver_objects(root, lock, archive, work, candidate_text):
    """Two actual selected ARM configurations; no image or controller claim."""
    base = root / '.local/build/managed-wakeup-init-kernel'
    base.mkdir(parents=True, exist_ok=True)
    with locked(base / '.qualification-lock'):
        base, source, metadata = kernel_source(root, lock, archive)
        # The effective non-test header must be the exact native-qualified body.
        from managed_wakeup_init_source import DEVRES_HEADER, inline_functions
        header = (source / HEADER).read_text()
        before, rest = header.split('#ifdef CONFIG_NEO_MANAGED_WAKEUP_RETURN_IGNORED\n', 1)
        _, rest = rest.split('#else\n', 1)
        good, tail = rest.split('#endif\n', 1)
        if inline_functions(before + good + tail, (source / DEVRES_HEADER).read_text()) != candidate_text:
            raise ValueError('Selected-object inline differs from native-qualified candidate')
        builder = lock['builder']
        records = {}
        for sleep in (True, False):
            resources(root, base)
            name = 'pm-sleep' if sleep else 'pm-no-sleep'
            scratch = base / 'driver-runs' / (name + '-' + uuid.uuid4().hex)
            scratch.mkdir(parents=True)
            settings = ['CONFIG_COMPILE_TEST=y', 'CONFIG_I2C=y',
                'CONFIG_MFD_MAX77541=y', 'CONFIG_RTC_CLASS=y', 'CONFIG_RTC_DRV_STM32=y',
                'CONFIG_OF=y', 'CONFIG_PINCTRL=y', 'CONFIG_COMMON_CLK=y', 'CONFIG_PM=y',
                'CONFIG_SUSPEND=' + ('y' if sleep else 'n'), 'CONFIG_HIBERNATION=n',
                'CONFIG_PM_SLEEP=' + ('y' if sleep else 'n'), 'CONFIG_KUNIT=n',
                'CONFIG_NEO_MANAGED_WAKEUP_INIT_KUNIT_TEST=n',
                'CONFIG_NEO_MANAGED_WAKEUP_RETURN_IGNORED=n']
            (scratch / 'extra.config').write_text('\n'.join(settings) + '\n')
            objects = ['drivers/base/devres.o', 'drivers/mfd/max77541.o', 'drivers/rtc/rtc-stm32.o']
            if sleep:
                objects.append('drivers/base/power/wakeup.o')
            relative = scratch.relative_to(root).as_posix()
            result = execute(STEM + '-drivers-' + name, ['--pull=never', '--network', 'none',
                '--user', f'{os.getuid()}:{os.getgid()}', '--platform', builder['platform'],
                '--entrypoint', 'bash', '-v', f'{root}:/project', '-v', f'{source}:/kernel-source:ro',
                '-e', f'NEO_WAKEUP_OUTPUT=/project/{relative}/output',
                '-e', f'CROSS_COMPILE={builder["cross_compile"]}', '-e', 'ARCH=arm',
                '-e', 'KBUILD_BUILD_USER=gameshellneo', '-e', 'KBUILD_BUILD_HOST=builder',
                '-w', '/kernel-source', builder['image'], '-c',
                'set -euo pipefail\n'
                'make O="$NEO_WAKEUP_OUTPUT" sunxi_defconfig\n'
                '/kernel-source/scripts/kconfig/merge_config.sh -m -O "$NEO_WAKEUP_OUTPUT" '
                f'"$NEO_WAKEUP_OUTPUT/.config" /project/{relative}/extra.config\n'
                'make O="$NEO_WAKEUP_OUTPUT" olddefconfig\n'
                'python3 -c \'import pathlib,sys;sys.path.insert(0,"/project/tools");'
                'from kernel_checks import check_overrides;check_overrides(pathlib.Path(sys.argv[1]),'
                'pathlib.Path(sys.argv[2]).read_text().splitlines())\' '
                f'"$NEO_WAKEUP_OUTPUT/.config" /project/{relative}/extra.config\n'
                'make O="$NEO_WAKEUP_OUTPUT" -j1 ' + ' '.join(objects) + '\n'
                f'"${{CROSS_COMPILE}}gcc" --version > /project/{relative}/compiler.txt\n'
                f'"${{CROSS_COMPILE}}readelf" -h ' + ' '.join('"$NEO_WAKEUP_OUTPUT/' + obj + '"' for obj in objects) +
                f' > /project/{relative}/elf-info.txt\n'], scratch / 'attempt', timeout=None)
            check_overrides(scratch / 'output/.config', settings)
            record = dict(managed_result=result, extra_config=settings,
                scratch=relative, objects={obj: sha256(scratch / 'output' / obj) for obj in objects},
                config_sha256=sha256(scratch / 'output/.config'),
                compiler_sha256=sha256(scratch / 'compiler.txt'),
                elf_info_sha256=sha256(scratch / 'elf-info.txt'), source=metadata,
                resources=resources(root, base), configuration_scope='selected ARM driver objects only')
            atomic_json(scratch / 'evidence.json', record)
            records[name] = record
        return records
