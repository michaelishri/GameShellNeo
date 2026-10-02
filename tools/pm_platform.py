"""Admission and trace evidence for platform+freeze, never actual s2idle."""
import re
from pathlib import Path

WAKE_PATCH = 'kernel/patches/0019-wake-irq-error-ownership.patch'
WAKE_SHA = 'e3cd7c021bb14369fcf6c3d415c84dd96bd37c27a5449583e27180c1d9d03cf3'
PHASES = ('dpm_suspend_late', 'dpm_suspend_noirq', 'dpm_resume_noirq', 'dpm_resume_early')


def admission(snapshot, power_key, keypad_trace):
    if power_key is not True or keypad_trace is not True:
        raise ValueError('Platform debug requires power-key ownership and PM tracing')
    if snapshot['image'].get('project_inputs_sha256', {}).get(WAKE_PATCH) != WAKE_SHA:
        raise ValueError('Platform debug requires the checked wake-IRQ image')
    lines = Path('/etc/default/armbian-ramlog').read_text().splitlines()
    if [l for l in lines if l.strip() and not l.lstrip().startswith('#')] != ['ENABLED=false']:
        raise ValueError('Persistent-journal policy missing')
    import subprocess
    hooks = subprocess.check_output(['systemctl', 'show', 'logrotate.service',
        '-p', 'ExecStartPre', '-p', 'ExecStartPost', '--value'], text=True, timeout=5).strip()
    if hooks:
        raise ValueError('Log rotation still owns journal-moving hooks')
    from rtc_alarm import qualification
    return qualification(snapshot['boot_id'], snapshot['kernel'])


def validate_trace(record):
    if record.get('trace_overrun') is not False or record.get('trace_restored') is not True:
        raise ValueError('Platform trace incomplete or unrestored')
    text = record.get('trace', '')
    boundaries = []
    for match in re.finditer(r'suspend_resume: (dpm_(?:suspend_late|suspend_noirq|resume_noirq|resume_early))\[\d+\] (begin|end)', text):
        boundaries.append((match.group(1), match.group(2), match.start(), match.end()))
    expected = [(name, direction) for name in PHASES for direction in ('begin', 'end')]
    if [(name, direction) for name, direction, _, _ in boundaries] != expected:
        raise ValueError('Missing/repeated/out-of-order late/noirq trace boundaries')
    if re.search(r'device_pm_callback_end: .*err=(?!0\b)-?\d+', text):
        raise ValueError('Nonzero device PM callback result')
    if re.search(r'suspend_resume: (?:machine_suspend|s2idle_enter)\[', text):
        raise ValueError('Unexpected actual-sleep trace')
    rsb = []
    for index, verb in ((2, 'suspend'), (4, 'resume')):
        window = text[boundaries[index][3]:boundaries[index+1][2]]
        starts = list(re.finditer(r'device_pm_callback_start: sunxi-rsb 1f03400\.rsb, parent: [^,]+, noirq [^\n]*\['+verb+r'\]', window))
        ends = list(re.finditer(r'device_pm_callback_end: sunxi-rsb 1f03400\.rsb, err=0\b', window))
        if len(starts) != 1 or len(ends) != 1 or starts[0].start() >= ends[0].start():
            raise ValueError('RSB noirq callback entry/return missing or ambiguous')
        rsb.append(verb)
    return dict(phases=list(PHASES), rsb_noirq=rsb,
                limits='Completed late/noirq callbacks and debug return; no sleep/wake or energy proof.')
