#!/usr/bin/env python3
"""Fault-test actual retained-power PM callbacks and failed-wake I/O boundaries."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import tarfile

from kernel_checks import archive_for, compile_objects, run, sha256

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.local/build/brcmfmac-pm-tests'
BASE = 'drivers/net/wireless/broadcom/brcm80211/brcmfmac/'
DRIVERS = tuple(BASE + name for name in ('bcmsdh.c', 'sdio.c', 'sdio.h'))
CONTRACT = ('include/linux/mmc/sdio.h', 'drivers/mmc/core/sdio_io.c',
            'drivers/mmc/core/sdio_irq.c', 'kernel/irq/manage.c')
PATCHES = tuple(ROOT / 'kernel/patches' / name for name in (
    '0014-brcmfmac-sdio-sleep-errors.patch', '0015-brcmfmac-freezer-lifecycle.patch',
    '0016-brcmfmac-pm-rollback.patch'))


def function(source, declaration):
    start = source.index(declaration)
    return source[start:source.index('\n}', start) + 2] + '\n'


def mutate_once(source, before, after):
    if source.count(before) != 1:
        raise RuntimeError('Missing/ambiguous mutation: ' + before)
    return source.replace(before, after, 1)


def extracted(bcmsdh, sdio, header, lifecycle=False):
    text = header[header.index('static inline bool brcmf_sdiod_io_blocked('):
                  header.index('\nu32 brcmf_sdiod_readl(')]
    for name in ('void brcmf_sdiod_change_state(', 'static int brcmf_sdiod_pm_disarm(',
                 'static void brcmf_sdiod_pm_quiesce_irqs('):
        text += function(bcmsdh, name)
    text += function(sdio, 'static int brcmf_sdio_dcmd_resp_wake(')
    text += function(sdio, 'void brcmf_sdio_pm_failed(')
    text += bcmsdh[bcmsdh.index('static int brcmf_sdiod_freezer_attach('):
                   bcmsdh.index('\nint brcmf_sdiod_remove(')]
    if lifecycle:
        text += function(bcmsdh, 'static int brcmf_sdiod_suspend(')
        text += function(bcmsdh, 'static void brcmf_sdiod_pm_abort(')
    for name in ('static int brcmf_ops_sdio_suspend(', 'static int brcmf_ops_sdio_resume('):
        text += function(bcmsdh, name)
    for name in ('void brcmf_sdio_trigger_dpc(', 'void brcmf_sdio_isr(',
                 'static void brcmf_sdio_dataworker(', 'static int\nbrcmf_sdio_watchdog_thread(',
                 'static int\nbrcmf_sdio_bus_txctl(', 'static int brcmf_sdio_dcmd_resp_wait(',
                 'static int\nbrcmf_sdio_bus_rxctl(', 'static int brcmf_sdio_assert_info(',
                 'static int brcmf_sdio_bus_reset('):
        text += function(sdio, name)
    for name in ('static int brcmf_sdiod_set_backplane_window(', 'u32 brcmf_sdiod_readl(',
                 'void brcmf_sdiod_writel(', 'static int brcmf_sdiod_skbuff_read(',
                 'static int brcmf_sdiod_skbuff_write(', 'static int mmc_submit_one(',
                 'static irqreturn_t brcmf_sdiod_oob_irqhandler('):
        text += function(bcmsdh, name)
    # Give the teardown body its own test entry; legacy power-off tests retain
    # their lifecycle seam. The body itself is unchanged.
    text += function(bcmsdh, 'void brcmf_sdiod_intr_unregister(').replace(
        'void brcmf_sdiod_intr_unregister(', 'static void test_intr_unregister(', 1)
    if lifecycle:
        text += function(bcmsdh, 'static void brcmf_ops_sdio_remove(')
        # Callbacks are invoked through a driver-core lock seam in the harness.
        for name in ('suspend', 'resume', 'remove'):
            text = text.replace('brcmf_ops_sdio_' + name + '(', 'callback_' + name + '(')
    return text


def main():
    global WORK, PATCHES, CONTRACT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-driver', action='store_true')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--lifecycle', action='store_true')
    mode.add_argument('--irq-service', action='store_true')
    args = parser.parse_args()
    if args.lifecycle or args.irq_service:
        WORK = ROOT / ('.local/build/brcmfmac-irq-tests' if args.irq_service
                       else '.local/build/brcmfmac-lifecycle-tests')
        PATCHES += (ROOT / 'kernel/patches/0017-brcmfmac-pm-lifecycle.patch',)
        CONTRACT += ('drivers/base/power/main.c', 'drivers/base/dd.c',
                     'include/linux/device.h', 'drivers/mmc/core/sdio.c',
                     'drivers/mmc/core/sdio_bus.c', BASE + 'core.c', BASE + 'bus.h')
        if args.irq_service:
            CONTRACT += ('include/linux/mmc/host.h', 'drivers/mmc/host/sunxi-mmc.c',
                         'kernel/workqueue.c')
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = WORK / ('compile-evidence.json' if args.compile_driver else 'evidence.json')
        output.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        with tarfile.open(archive, mode='r|xz') as source:
            prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
            remaining = {*DRIVERS, *CONTRACT}
            for member in source:
                name = member.name.removeprefix(prefix)
                if name not in remaining:
                    continue
                target = WORK / 'patched' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.extractfile(member).read())
                remaining.remove(name)
                if not remaining:
                    break
            if remaining:
                raise RuntimeError('Missing locked sources: ' + repr(remaining))
        original = {name: sha256(WORK / 'patched' / name) for name in DRIVERS}
        previous_sleep = None
        for patch in PATCHES:
            run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=WORK / 'patched')
            if patch == PATCHES[1]:
                previous_sleep = (WORK / 'patched' / DRIVERS[1]).read_text()
        bcmsdh, sdio, driver_header = ((WORK / 'patched' / name).read_text() for name in DRIVERS)
        for declaration in ('static int\nbrcmf_sdio_kso_control(', 'static int brcmf_sdio_htclk(',
                            'static int brcmf_sdio_sdclk(', 'static int brcmf_sdio_clkctl(',
                            'static int\nbrcmf_sdio_bus_sleep('):
            if function(previous_sleep, declaration) != function(sdio, declaration):
                raise RuntimeError('Previously tested sleep helper changed: ' + declaration)
        definitions = re.search(r'#define BRCMF_SDIO_FREEZE_TIMEOUT_MS[^\n]+\n', bcmsdh)[0]
        definitions += bcmsdh[bcmsdh.index('struct brcmf_sdiod_freezer {'):
                             bcmsdh.index('\n};', bcmsdh.index('struct brcmf_sdiod_freezer {')) + 4]
        wanted = {'SDIO_CCCR_IENx', 'SDIO_CCCR_BRCM_SEPINT', 'CTL_DONE_TIMEOUT', 'DCMD_RESP_TIMEOUT',
                  'SDPCM_SHARED_ASSERT_BUILT', 'SDPCM_SHARED_ASSERT'}
        for source in (driver_header, sdio, (WORK / 'patched' / CONTRACT[0]).read_text()):
            lines = iter(source.splitlines(keepends=True))
            for line in lines:
                match = re.match(r'#define\s+(\w+)', line)
                if not match:
                    continue
                while line.endswith('\\\n'):
                    line += next(lines)
                if match[1] in wanted or match[1].startswith('SBSDIO_'):
                    definitions += line
        (WORK / 'brcmfmac_freezer_types.h').write_text(definitions)
        good = extracted(bcmsdh, sdio, driver_header, args.lifecycle)
        header = WORK / 'brcmfmac_freezer_functions.h'
        harness = ROOT / 'kernel/tests' / ('brcmfmac_lifecycle_test.c' if args.lifecycle
                                         else 'brcmfmac_pm_test.c')
        if args.irq_service:
            import brcmfmac_irq_checks as irq_checks
            good = irq_checks.extracted(sdio, driver_header, function)
            (WORK / 'brcmfmac_irq_types.h').write_text(irq_checks.definitions(sdio, driver_header))
            harness = ROOT / 'kernel/tests/brcmfmac_irq_test.c'
        # The upstream debug string "<???>" is intentionally not a trigraph.
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-trigraphs', '-pthread',
                 '-I', str(WORK), str(harness)]
        if args.irq_service:
            cases = irq_checks.variants(good, function, mutate_once)
        elif args.lifecycle:
            # The same source regressions run in lifecycle mode, with its own
            # mutation targets for the new callbacks and interrupt boundary.
            from brcmfmac_lifecycle_checks import variants
            cases = variants(good, function, mutate_once)
        else:
            cases = pm_variants(good)
        results = {}
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        try:
            for name, text in cases.items():
                if name != 'candidate' and text == good:
                    raise RuntimeError('Negative control did not change source: ' + name)
                header.write_text(text)
                binary = WORK / name
                run(['cc', *flags, '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
                (WORK / (name + '.txt')).write_text(result.stdout + result.stderr)
                if name == 'candidate':
                    result.check_returncode()
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise RuntimeError('Negative control did not fail by assertion: ' + name)
                results[name] = dict(returncode=result.returncode, output=result.stdout.strip(),
                                     error=result.stderr.strip())
                print(name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
        finally:
            header.write_text(good)
        builder = lock['builder']
        work_relative = WORK.relative_to(ROOT).as_posix()
        harness_relative = harness.relative_to(ROOT).as_posix()
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash',
            '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\n'
            'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -Wno-trigraphs -pthread -static '
            f'-I{work_relative} {harness_relative} -o {work_relative}/arm\n'
            f'qemu-arm {work_relative}/arm'], text=True, timeout=120).strip()
        if arm != results['candidate']['output']:
            raise RuntimeError('Native and ARM32 results differ')
        print('ARM32: ' + arm, flush=True)
        inputs = (*PATCHES, harness, ROOT / 'kernel/tests/brcmfmac_pm_shims.h',
                  ROOT / 'kernel/tests/brcmfmac_freezer_test.c', Path(__file__),
                  ROOT / 'tools/kernel_checks.py', ROOT / 'tools/check-kernel-config.py')
        if args.lifecycle:
            inputs += (ROOT / 'kernel/tests/brcmfmac_pm_test.c',
                       ROOT / 'kernel/tests/brcmfmac_lifecycle_shims.h',
                       ROOT / 'tools/brcmfmac_lifecycle_checks.py')
        if args.irq_service:
            inputs = (*PATCHES, harness, Path(__file__),
                      ROOT / 'tools/brcmfmac_irq_checks.py', ROOT / 'tools/kernel_checks.py')
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
                        original=original,
                        patched={name: sha256(WORK / 'patched' / name) for name in DRIVERS},
                        inputs={str(p.relative_to(ROOT)): sha256(p) for p in inputs},
                        contract={name: sha256(WORK / 'patched' / name) for name in CONTRACT},
                        native=results, arm32=arm, builder=builder,
                        limits='Actual PM/freezer/worker/IRQ/control/accessor bodies with pthread and '
                               'scripted SDIO seams. No hardware, complete PM scheduling, electrical '
                               'state or automatic recovery qualification. Lifecycle mode exercises '
                               'selected device-lock, reset/removal and IRQ interleavings.')
        if args.irq_service:
            evidence['limits'] = ('Actual ISR/status/DPC/dataworker/OOB-rearm bodies; scripted '
                'register, clock, packet, workqueue and freezer seams. PM callback/freezer '
                'ordering is qualified separately by the lifecycle suite. No MMC controller '
                'execution, firmware, RF, Linux scheduling, electrical IRQ rate or energy proof. '
                'Error-characterization scenarios preserve existing limitations, not recovery guarantees.')
        if args.compile_driver:
            evidence['arm_build'] = compile_objects(archive, lock, WORK, [BASE + 'brcmfmac.o'])
            evidence['arm_debug_build'] = compile_objects(archive, lock, WORK,
                [BASE + 'brcmfmac.o'], extra_config=('CONFIG_BRCMDBG=y',))
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', output.relative_to(ROOT), flush=True)


def pm_variants(good):
    suspend = function(good, 'static int brcmf_ops_sdio_suspend(')
    restore = function(good, 'static int brcmf_sdiod_pm_restore(')
    disarm = function(good, 'static int brcmf_sdiod_pm_disarm(')
    trigger = function(good, 'void brcmf_sdio_trigger_dpc(')
    worker = function(good, 'static void brcmf_sdio_dataworker(')
    wd = function(good, 'static int\nbrcmf_sdio_watchdog_thread(')
    isr = function(good, 'void brcmf_sdio_isr(')
    window = function(good, 'static int brcmf_sdiod_set_backplane_window(')
    byte_check = function(good, 'static inline bool brcmf_sdiod_io_check(')
    fail = function(good, 'void brcmf_sdio_pm_failed(')
    response = function(good, 'static int brcmf_sdio_dcmd_resp_wait(')
    oob_handler = function(good, 'static irqreturn_t brcmf_sdiod_oob_irqhandler(')
    debug_info = function(good, 'static int brcmf_sdio_assert_info(')
    tx_control = function(good, 'static int\nbrcmf_sdio_bus_txctl(')
    cases = {
        'candidate': good,
        'lost_sleep_error': mutate_once(good, suspend, mutate_once(suspend,
            'ret = brcmf_sdio_sleep(sdiodev->bus, true);',
            'brcmf_sdio_sleep(sdiodev->bus, true);')),
        'lost_wake_error': mutate_once(good, restore, mutate_once(restore,
            'ret = brcmf_sdio_sleep(sdiodev->bus, false);',
            'ret = 0 * brcmf_sdio_sleep(sdiodev->bus, false);')),
        'lost_oob_error': mutate_once(good, suspend, mutate_once(suspend,
            'ret = enable_irq_wake(', 'ret = 0 * enable_irq_wake(')),
        'lost_flags_error': mutate_once(good, suspend, mutate_once(suspend,
            'ret = sdio_set_host_pm_flags(', 'ret = 0 * sdio_set_host_pm_flags(')),
        'lost_primary_error': mutate_once(good, '\treturn ret;\n}\nstatic int brcmf_ops_sdio_resume(',
            '\treturn restore;\n}\nstatic int brcmf_ops_sdio_resume('),
        'lost_commit': mutate_once(good, '\t\tsdiodev->pm_suspended = true;', ''),
        'lost_wake_ownership': mutate_once(good, '\t\tsdiodev->pm_oob_irq_wake = true;',
            '\t\tsdiodev->pm_oob_irq_wake = false;'),
        'lost_disable_ownership': mutate_once(good, disarm,
            disarm.replace('\telse\n\t\tsdiodev->pm_oob_irq_wake = false;',
                           '\tsdiodev->pm_oob_irq_wake = false;')),
        'lost_failure_latch': mutate_once(good, 'WRITE_ONCE(bus->sdiodev->pm_failed, true);',
            'WRITE_ONCE(bus->sdiodev->pm_failed, false);'),
        'lost_worker_gate': mutate_once(good, worker,
            worker.replace('\t\tif (!brcmf_sdiod_io_blocked(bus->sdiodev))\n', '')
                  .replace('\t\t\tbrcmf_sdio_dpc(bus);', '\t\tbrcmf_sdio_dpc(bus);')),
        'lost_watchdog_gate': mutate_once(good, wd,
            wd.replace('if (!brcmf_sdiod_io_blocked(bus->sdiodev))', 'if (true)')),
        'lost_irq_gate': mutate_once(good, isr,
            isr.replace('\tif (brcmf_sdiod_io_blocked(bus->sdiodev))\n\t\treturn;\n', '')),
        'lost_trigger_gate': mutate_once(good, trigger,
            trigger.replace('\tif (brcmf_sdiod_io_blocked(bus->sdiodev))\n\t\treturn;\n', '')),
        'lost_byte_gate': mutate_once(good, byte_check,
            byte_check.replace('if (!brcmf_sdiod_io_blocked(sdiodev))',
                               '(void)sdiodev;\n\tif (true)')),
        'lost_window_gate': mutate_once(good, window,
            window.replace('\tif (brcmf_sdiod_io_blocked(sdiodev))\n\t\treturn -EHOSTDOWN;\n', '')),
        'lost_tx_error': mutate_once(good, fail,
            fail.replace('bus->ctrl_frame_err = -EHOSTDOWN;', 'bus->ctrl_frame_err = 0;')),
        'lost_tx_serialization': mutate_once(good, tx_control,
            tx_control.replace('\tsdio_claim_host(sdiodev->func1);\n', '')
                      .replace('\t\tsdio_release_host(sdiodev->func1);\n', '')
                      .replace('\tsdio_release_host(sdiodev->func1);\n', '')),
        'lost_irq_quiesce': mutate_once(good, restore,
            restore.replace('\t\tbrcmf_sdiod_pm_quiesce_irqs(sdiodev);\n', '')),
        'lost_rx_wakeup': mutate_once(good, fail,
            fail.replace('\tbrcmf_sdio_dcmd_resp_wake(bus);\n', '')),
        'lost_rx_predicate': mutate_once(good, response,
            response.replace(' && !brcmf_sdiod_io_blocked(bus->sdiodev)', '')),
        'lost_debug_host_release': mutate_once(good, debug_info,
            debug_info.replace('\t\t\tgoto release_host;\n', '\t\t\treturn error;\n', 1)),
        'lost_oob_serialization': mutate_once(good, oob_handler,
            oob_handler.replace('\tunsigned long flags;\n', '')
                .replace('\tspin_lock_irqsave(&sdiodev->irq_en_lock, flags);\n', '')
                .replace('\tspin_unlock_irqrestore(&sdiodev->irq_en_lock, flags);\n', '')),
    }
    for name, declaration in [('lost_packet_read_gate', 'static int brcmf_sdiod_skbuff_read('),
                              ('lost_packet_write_gate', 'static int brcmf_sdiod_skbuff_write('),
                              ('lost_sg_gate', 'static int mmc_submit_one(')]:
        text = function(good, declaration)
        cases[name] = mutate_once(good, text, text.replace(
            '\tif (brcmf_sdiod_io_blocked(sdiodev))\n\t\treturn -EHOSTDOWN;\n', ''))
    return cases


if __name__ == '__main__':
    main()
