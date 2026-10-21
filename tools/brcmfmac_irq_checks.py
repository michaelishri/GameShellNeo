"""Actual SDIO status/DPC extraction and assertion-based negative controls."""
import re


def extracted(sdio, header, function, bcmsdh='', hardened=False, mailbox=False):
    text = function(header, 'static inline bool brcmf_sdiod_io_blocked(')
    if mailbox:
        text += function(sdio, 'static int brcmf_sdio_hostmail(')
    if hardened:
        text += function(bcmsdh, 'void brcmf_sdiod_quiesce_irqs(')
        text += function(sdio, 'static void brcmf_sdio_dpc_failed(')
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
            if match[1].startswith(('SBSDIO_', 'I_', 'CLK_', 'HMB_DATA_')) or match[1] in {
                    'SD_REG', 'HOSTINTMASK', 'SMB_INT_ACK', 'SDPCM_PROT_VERSION'}:
                text += line
    return text


def variants(good, function, mutate_once, hardened=False, mailbox=False):
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
        ('lost_mailbox_service', dpc,
         'err = brcmf_sdio_hostmail(bus, &mailbox_status);' if mailbox else
         'intstatus |= brcmf_sdio_hostmail(bus);',
         'err = 0; mailbox_status = 0;' if mailbox else
         'if (false) intstatus |= brcmf_sdio_hostmail(bus);'),
        ('lost_leftover_status', dpc, 'atomic_or(intstatus, &bus->intstatus);', ''),
        ('lost_worker_failure_gate', worker,
         'if (!READ_ONCE(bus->sdiodev->pm_failed))' if hardened else
         'if (!brcmf_sdiod_io_blocked(bus->sdiodev))', 'if (true)'),
        ('lost_isr_failure_gate', isr,
         'if (brcmf_sdiod_io_blocked(bus->sdiodev))',
         'if (false && brcmf_sdiod_io_blocked(bus->sdiodev))'),
        ('lost_oob_pending_gate', clear,
         '!atomic_read(&bus->ipend) || bus->clkstate == CLK_PENDING' if hardened else
         '!sdiodev->irq_en && !atomic_read(&bus->ipend)',
         'true' if hardened else '!sdiodev->irq_en'),
    ):
        cases[name] = mutate_once(good, body, mutate_once(body, before, after))
    if hardened:
        failed = function(good, 'static void brcmf_sdio_dpc_failed(')
        for name, body, before, after in (
            ('lost_wake_error', dpc, 'err = brcmf_sdio_bus_sleep(bus, false, true);',
             'err = 0 * brcmf_sdio_bus_sleep(bus, false, true);'),
            ('lost_ack_error', status, 'if (ret)\n\t\t\treturn ret;',
             'if (false && ret)\n\t\t\treturn ret;'),
            ('lost_status_error_exit', dpc,
             'err = brcmf_sdio_intr_rstatus(bus);\n\t\tif (err)',
             'err = brcmf_sdio_intr_rstatus(bus);\n\t\tif (false && err)'),
            ('lost_isr_error_latch', isr, 'WRITE_ONCE(bus->sdiodev->io_error, err);',
             'WRITE_ONCE(bus->sdiodev->io_error, 0);'),
            ('lost_failure_latch', failed, 'WRITE_ONCE(sdiod->io_error, err);',
             'WRITE_ONCE(sdiod->io_error, 0 * err);'),
            ('lost_irq_shutdown', failed, 'brcmf_sdiod_quiesce_irqs(sdiod);', ''),
            ('lost_watchdog_stop', failed, 'brcmf_sdio_wd_timer(bus, false);',
             'if (false) brcmf_sdio_wd_timer(bus, false);'),
            ('lost_tx_completion', failed, 'bus->ctrl_frame_stat = false;', ''),
            ('lost_response_wakeup', failed, 'brcmf_sdio_dcmd_resp_wake(bus);',
             'if (false) brcmf_sdio_dcmd_resp_wake(bus);'),
            ('lost_cleanup_idempotence', failed, 'if (bus->io_error_handled)',
             'if (false && bus->io_error_handled)'),
            ('lost_clock_pending_exit', dpc, 'if (bus->clkstate == CLK_PENDING) {',
             'if (false && bus->clkstate == CLK_PENDING) {'),
            ('lost_clock_oob_rearm', clear,
             '!atomic_read(&bus->ipend) || bus->clkstate == CLK_PENDING',
             '!atomic_read(&bus->ipend)'),
            ('lost_oob_ownership_recheck', clear,
             'if (sdiodev->oob_irq_requested &&', 'if (true &&'),
            ('lost_clock_read_error', dpc,
             'SBSDIO_FUNC1_CHIPCLKCSR, &err);\n\t\tif (err)',
             'SBSDIO_FUNC1_CHIPCLKCSR, &err);\n\t\tif (false && err)'),
            ('lost_clock_write_error', dpc,
             'SBSDIO_DEVICE_CTL, devctl, &err);\n\t\t\tif (err)',
             'SBSDIO_DEVICE_CTL, devctl, &err);\n\t\t\tif (false && err)'),
            ('lost_flow_ack_error', dpc,
             'I_HMB_FC_CHANGE, &err);\n\t\tbus->sdcnt.f1regdata++;\n\t\tif (err)',
             'I_HMB_FC_CHANGE, &err);\n\t\tbus->sdcnt.f1regdata++;\n\t\tif (false && err)'),
            ('lost_flow_read_error', dpc,
             'newstatus = brcmf_sdiod_readl(sdiod, intstat_addr, &err);\n\n'
             '\t\tbus->sdcnt.f1regdata++;\n\t\tif (err)',
             'newstatus = brcmf_sdiod_readl(sdiod, intstat_addr, &err);\n\n'
             '\t\tbus->sdcnt.f1regdata++;\n\t\tif (false && err)'),
        ):
            cases[name] = mutate_once(good, body, mutate_once(body, before, after))
    return cases
