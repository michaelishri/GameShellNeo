"""Actual firmware initialization bodies with controlled synchronous SDIO seams."""
import re

from kernel_checks import ROOT
from kernel_sources import atomic_json

HARNESS = ROOT / 'kernel/tests/brcmfmac_startup_test.c'
COMMON_STAGES = ('download_clock', 'download_code', 'download_nvram', 'activate', 'download_drop',
                 'setup_clock', 'force_read', 'force_write', 'protocol', 'enable_f2',
                 'host_mask', 'watermark', 'register_irq', 'allocate', 'attach')
CASES = []
for chip in range(11):
    for mode in range(3):
        CASES.append(('success', str(chip), str(mode)))
        stages = list(COMMON_STAGES)
        if chip != 10:
            stages += ['device_read', 'device_write', 'mesbusy']
        stages += ['sr_read', 'sr_write', 'sr_card', 'sr_clock'] if mode else ['restore_clock']
        CASES += [('failure', str(chip), str(mode), stage, str(error))
                  for stage in stages for error in range(3)]
CASES += [(group, '10', '0') for group in ('download_primary', 'incoming', 'clock_state')]


def extract_sources(source, attempt, shared):
    base = source / 'drivers/net/wireless/broadcom/brcm80211'
    sdio = (base / 'brcmfmac/sdio.c').read_text()
    header = (base / 'brcmfmac/sdio.h').read_text()
    types = shared.irq.definitions(sdio, header)
    for text in (sdio, header, (base / 'include/brcm_hw_ids.h').read_text(),
                 (source / 'include/linux/mmc/sdio_ids.h').read_text()):
        lines = iter(text.splitlines(True))
        for line in lines:
            match = re.match(r'#define\s+(\w+)', line)
            if not match:
                continue
            while line.endswith('\\\n'):
                line += next(lines)
            if match[1].startswith(('CY_', 'BRCM_CC_', 'SDIO_DEVICE_ID_BROADCOM_',
                                   'SDIO_CCCR_BRCM_CARDCAP', 'BRCMF_SDIO_FW_')) or match[1] in {
                    'DEFAULT_F2_WATERMARK', 'SMB_DATA_VERSION_SHIFT'}:
                types += line
    function = shared.helpers.extract.function
    body = ''.join(function(sdio, prefix) for prefix in (
        'static int brcmf_sdio_download_firmware(', 'static bool brcmf_sdio_aos_no_decode(',
        ('static int' if 'static int brcmf_sdio_sr_init(' in sdio else 'static void') +
        ' brcmf_sdio_sr_init(', 'static void brcmf_sdio_firmware_callback('))
    (attempt / 'brcmfmac_startup_types.h').write_text(types)
    (attempt / 'brcmfmac_startup_functions.h').write_text(body)


def run_cases(attempt, shared, *, arm=False, sanitizer=False, baseline=False):
    label = 'arm' if arm else 'sanitizer' if sanitizer else 'native'
    binary = shared.compile_test(attempt, HARNESS, label + '-startup', arm, sanitizer)
    results = {}
    for case in CASES:
        result = shared.execute(binary, case, arm)
        key = '-'.join(case)
        results[key] = dict(returncode=result.returncode, output=result.stdout, error=result.stderr)
        (attempt / (label + '-startup-' + key + '.log')).write_text(result.stdout + result.stderr)
    atomic_json(attempt / (label + '-startup-results.json'), results)
    failed = [key for key, result in results.items() if result['returncode'] or
              result['output'].strip() != key.replace('-', ' ') + ' passed']
    print(f'{label} startup: {len(results) - len(failed)}/{len(results)} pass', flush=True)
    if failed and not baseline:
        raise RuntimeError('Firmware startup cases failed: ' + ', '.join(failed))
    return failed


def negatives(attempt, shared):
    path = attempt / 'brcmfmac_startup_functions.h'
    good = path.read_text()
    extract = shared.helpers.extract
    callback = extract.function(good, 'static void brcmf_sdio_firmware_callback(')
    download = extract.function(good, 'static int brcmf_sdio_download_firmware(')
    sr = extract.function(good, 'static int brcmf_sdio_sr_init(')
    variants = []

    def add(name, body, before, after, case):
        variants.append((name, extract.mutate_once(good, body,
                         extract.mutate_once(body, before, after)), case))

    def failure(stage, chip='10', mode='0'):
        return ('failure', chip, mode, stage, '0')

    add('download_admission', download, 'if (bcmerror)\n\t\tgoto out;',
        'if (false && bcmerror)\n\t\tgoto out;', failure('download_clock'))
    add('download_drop_error', download, 'bcmerror = ret;', '(void)ret;', failure('download_drop'))
    add('download_first_error', download, 'if (!bcmerror)', 'if (true)', ('download_primary', '10', '0'))
    for name, before in (('code_release', 'release_firmware(fw);'),
                         ('nvram_release', 'brcmf_fw_nvram_free(nvram);')):
        add(name, download, before, 'if (false) ' + before, failure('download_clock'))
    add('setup_clock_admission', callback, 'if (err)\n\t\tgoto release;',
        'if (false && err)\n\t\tgoto release;', failure('setup_clock'))
    add('setup_clock_state_error', callback, 'err = -EIO;', 'err = 0;', ('clock_state', '10', '0'))
    for stage, fragment in (
        ('protocol', 'SDPCM_PROT_VERSION << SMB_DATA_VERSION_SHIFT, &err);'),
        ('host_mask', 'bus->hostintmask, &err);')):
        add(stage + '_errno', callback, fragment, fragment.replace('&err', 'NULL'), failure(stage))
    # Every newly guarded transfer must independently reject later setup.
    gates = list(re.finditer(r'if \(err\)\n\s*goto checkdied;', callback))
    stages = [('protocol', '10'), ('host_mask', '10')]
    stages += [(stage, chip) for chip in ('0', '3', '4', '6', '7')
               for stage in ('watermark', 'device_read', 'device_write', 'mesbusy')]
    stages += [('watermark', '10')]
    if len(gates) != len(stages):
        raise ValueError('Unexpected callback transfer error gates')
    for index, (gate, (stage, chip)) in enumerate(zip(gates, stages)):
        broken = callback[:gate.start()] + gate[0].replace('if (err)', 'if (false && err)') + callback[gate.end():]
        variants.append((f'transfer_gate_{index}', extract.mutate_once(good, callback, broken), failure(stage, chip)))
    add('sr_callback_error', callback, 'err = brcmf_sdio_sr_init(bus);',
        '(void)brcmf_sdio_sr_init(bus);', failure('sr_read', mode='1'))
    gates = list(re.finditer(r'if \(err\) \{', sr))
    if len(gates) != 4:
        raise ValueError('Unexpected save/restore transfer error gates')
    for index, (gate, stage) in enumerate(zip(gates, ('sr_read', 'sr_write', 'sr_card', 'sr_clock'))):
        broken = sr[:gate.start()] + gate[0].replace('if (err)', 'if (false && err)') + sr[gate.end():]
        variants.append((f'sr_gate_{index}', extract.mutate_once(good, sr, broken), failure(stage, mode='1')))
    add('sr_success_publication', sr, 'bus->sr_enabled = true;',
        'bus->sr_enabled = false;', ('success', '10', '1'))
    add('attach_free', callback, 'brcmf_free(sdiod->dev);',
        'if (false) brcmf_free(sdiod->dev);', failure('attach'))
    add('f2_release', callback, 'device_release_driver(&sdiod->func2->dev);',
        'if (false) device_release_driver(&sdiod->func2->dev);', failure('allocate'))
    add('f1_release', callback, 'device_release_driver(dev);',
        'if (false) device_release_driver(dev);', failure('allocate'))
    results = {}
    try:
        for name, body, case in variants:
            path.write_text(body); (attempt / ('startup-' + name + '.h')).write_text(body)
            binary = shared.compile_test(attempt, HARNESS, 'startup-' + name)
            result = shared.execute(binary, case)
            (attempt / ('startup-' + name + '.log')).write_text(result.stdout + result.stderr)
            if not result.returncode or 'Assertion' not in result.stderr:
                raise ValueError('Startup mutation did not fail an assertion: ' + name)
            results[name] = dict(case=case, returncode=result.returncode, error=result.stderr)
    finally:
        path.write_text(good)
    atomic_json(attempt / 'startup-negatives.json', results)
    print(f'{len(results)} startup mutations rejected', flush=True)
