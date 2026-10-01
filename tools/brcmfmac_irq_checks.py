"""Actual SDIO status/DPC extraction and assertion-based negative controls."""
import re


def extracted(sdio, header, function):
    text = function(header, 'static inline bool brcmf_sdiod_io_blocked(')
    for name in ('static inline void brcmf_sdio_clrintr(',
                 'static int brcmf_sdio_intr_rstatus(',
                 'static void brcmf_sdio_dpc(', 'void brcmf_sdio_trigger_dpc(',
                 'void brcmf_sdio_isr(', 'static void brcmf_sdio_dataworker('):
        text += function(sdio, name)
    return text


def definitions(sdio, header):
    start = header.index('struct sdpcmd_regs {')
    registers = header[start:header.index('\n};', start) + 4]
    # Kernel PAD expands to unique member names; preserve every type/size.
    pads = iter(range(100))
    text = re.sub(r'\bPAD\b', lambda _: 'pad_' + str(next(pads)), registers)
    for source in (header, sdio):
        lines = iter(source.splitlines(keepends=True))
        for line in lines:
            match = re.match(r'#define\s+(\w+)', line)
            if not match:
                continue
            while line.endswith('\\\n'):
                line += next(lines)
            if match[1].startswith(('SBSDIO_', 'I_', 'CLK_')) or match[1] in {
                    'SD_REG', 'HOSTINTMASK'}:
                text += line
    return text


def variants(good, function, mutate_once):
    isr = function(good, 'void brcmf_sdio_isr(')
    status = function(good, 'static int brcmf_sdio_intr_rstatus(')
    dpc = function(good, 'static void brcmf_sdio_dpc(')
    worker = function(good, 'static void brcmf_sdio_dataworker(')
    clear = function(good, 'static inline void brcmf_sdio_clrintr(')
    cases = {'candidate': good}
    for name, body, before, after in (
        ('lost_irq_deferral', isr,
         'in_isr || READ_ONCE(bus->sdiodev->pm_irq_blocked)', 'in_isr'),
        ('lost_pending_publication', isr, 'atomic_set(&bus->ipend, 1);',
         'atomic_set(&bus->ipend, 0);'),
        ('lost_pending_consumption', dpc, 'err = brcmf_sdio_intr_rstatus(bus);',
         'err = 0;'),
        ('lost_pending_clear', dpc, 'atomic_set(&bus->ipend, 0);', ''),
        ('lost_status_mask', status, 'val &= bus->hostintmask;', ''),
        ('lost_status_ack', status,
         'brcmf_sdiod_writel(bus->sdiodev, addr, val, &ret);', ''),
        ('lost_status_publication', status, 'atomic_or(val, &bus->intstatus);', ''),
        ('lost_read_error', status, 'if (ret != 0)', 'if (false && ret != 0)'),
        ('lost_frame_service', dpc, 'brcmf_sdio_readframes(bus, bus->rxbound);',
         'if (false) brcmf_sdio_readframes(bus, bus->rxbound);'),
        ('lost_mailbox_service', dpc, 'intstatus |= brcmf_sdio_hostmail(bus);',
         'if (false) intstatus |= brcmf_sdio_hostmail(bus);'),
        ('lost_leftover_status', dpc, 'atomic_or(intstatus, &bus->intstatus);', ''),
        ('lost_worker_failure_gate', worker,
         'if (!brcmf_sdiod_io_blocked(bus->sdiodev))', 'if (true)'),
        ('lost_isr_failure_gate', isr,
         'if (brcmf_sdiod_io_blocked(bus->sdiodev))',
         'if (false && brcmf_sdiod_io_blocked(bus->sdiodev))'),
        ('lost_oob_pending_gate', clear,
         '!sdiodev->irq_en && !atomic_read(&bus->ipend)', '!sdiodev->irq_en'),
    ):
        cases[name] = mutate_once(good, body, mutate_once(body, before, after))
    return cases
