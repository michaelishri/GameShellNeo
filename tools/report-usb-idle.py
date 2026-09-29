#!/usr/bin/env python3
"""Render a completed USB idle comparison using only its saved private captures."""
import json
import os
from pathlib import Path
import sys


def records(phase, kind, filename):
    capture = Path(phase[kind]['capture'])
    rows = [json.loads(line) for line in (capture / filename).read_text().splitlines()]
    if (not rows or rows[-1] != phase[kind]['summary'] or
            rows[-1].get('event') != 'complete' or rows[-1].get('passed') is not True):
        raise ValueError('Raw capture is incomplete or differs from the accepted phase')
    return rows


def phase_metrics(phase):
    idle = records(phase, 'idle', 'idle-sample.jsonl')
    profile = records(phase, 'profile', 'power-profile.jsonl')
    samples = [row for row in idle if row['event'] == 'sample']
    ready = [row for row in idle if row['event'] == 'ready']
    raw = [row for row in profile if row['event'] == 'raw']
    if (len(samples) != 31 or len(ready) != 1 or ready[0]['seconds'] != 300 or
            any(row['boot_id'] != phase['boot_id'] for row in samples) or len(raw) != 1 or
            any(raw[0][key]['health']['boot_id'] != phase['boot_id'] for key in ('before', 'after')) or
            not 299 <= idle[-1]['duration_seconds'] <= 310 or
            not 119 <= profile[-1]['duration_seconds'] <= 130):
        raise ValueError('Raw capture does not match the phase boot or duration')
    rsb = [row for row in profile[-1]['interrupts'] if 'sunxi-rsb' in row['description'].split()]
    if len(rsb) != 1:
        raise ValueError('Expected one RSB interrupt counter')
    return dict(mode=phase['mode'], boot_id=phase['boot_id'],
                idle_capture=Path(phase['idle']['capture']).name,
                profile_capture=Path(phase['profile']['capture']).name,
                current_ma=idle[-1]['time_weighted_current_ma'],
                power_mw=idle[-1]['time_weighted_power_mw'],
                voltage_v=[op(row['voltage_uv'] for row in samples) / 1e6 for op in (min, max)],
                temperature_c=[op(row['temperature_millic'] for row in samples) / 1000 for op in (min, max)],
                capacity_percent=[samples[0]['capacity_percent'], samples[-1]['capacity_percent']],
                idle_signal_dbm=[ready[0]['wifi_signal_dbm'], idle[-1]['wifi_signal_dbm']],
                profile_signal_dbm=[profile[-1]['radio_before']['signal_dbm'], profile[-1]['radio_after']['signal_dbm']],
                cpu_busy_percent=profile[-1]['cpu']['cpu']['busy_percent'],
                cpu_accounting_coverage_percent=profile[-1]['cpu']['cpu']['accounting_coverage_percent'],
                rsb_irqs_per_second=rsb[0]['per_second'],
                network=profile[-1]['network'],
                profile_seconds=profile[-1]['duration_seconds'])


def summarize(report):
    phases = report.get('phases', [])
    if (report.get('passed') is not True or len(phases) != 3 or
            [phase['mode'] for phase in phases] != ['experimental', 'stock', 'experimental'] or
            any(phase.get('passed') is not True for phase in phases) or
            len({phase['boot_id'] for phase in phases}) != 3):
        raise ValueError('A complete experimental/stock/experimental comparison with three boots is required')
    rows = [phase_metrics(phase) for phase in phases]
    stock = rows[1]
    # Report each experimental window separately; do not hide drift in an average.
    differences = [dict(window=index + 1, **{
        key: dict(difference=rows[index][key] - stock[key],
                  percent=(rows[index][key] / stock[key] - 1) * 100 if stock[key] else None)
        for key in ('current_ma', 'power_mw', 'rsb_irqs_per_second')}) for index in (0, 2)]
    return dict(calibrated=False, phases=rows, experimental_minus_stock=differences)


def markdown(summary):
    rows = summary['phases']
    lines = ['# Saved USB idle comparison', '',
             'Software telemetry is uncalibrated. Battery and counter windows are sequential,',
             'with different observers. RSB IRQs are neither USB poll counts nor unique wakeups.', '',
             '| Metric | Experimental 1 | Stock | Experimental 2 |',
             '| --- | ---: | ---: | ---: |']
    def table(label, values):
        lines.append('| ' + ' | '.join([label, *values]) + ' |')
    for label, key, digits in (
            ('Current estimate (mA)', 'current_ma', 2), ('Power estimate (mW)', 'power_mw', 2),
            ('CPU busy (%)', 'cpu_busy_percent', 2),
            ('CPU accounting coverage (%)', 'cpu_accounting_coverage_percent', 2),
            ('RSB IRQs/s', 'rsb_irqs_per_second', 3)):
        table(label, [f'{row[key]:.{digits}f}' for row in rows])
    for label, key, digits in (
            ('Voltage range (V)', 'voltage_v', 4), ('Temperature range (°C)', 'temperature_c', 2)):
        table(label, [f'{row[key][0]:.{digits}f}–{row[key][1]:.{digits}f}' for row in rows])
    for label, key in (('Reported charge start/end (%)', 'capacity_percent'),
                       ('Idle signal start/end (dBm)', 'idle_signal_dbm'),
                       ('Profile signal start/end (dBm)', 'profile_signal_dbm')):
        table(label, [' / '.join(str(value) for value in row[key]) for row in rows])
    for key in ('rx_bytes', 'tx_bytes', 'rx_packets', 'tx_packets'):
        table('Profile ' + key.replace('_', ' '), [str(row['network'][key]) for row in rows])
    lines.extend(['', '## Experimental minus stock', '',
                  'Negative values mean lower readings. These differences alone do not establish causation.', ''])
    for difference in summary['experimental_minus_stock']:
        values = []
        for label, key in (('current', 'current_ma'), ('power', 'power_mw'), ('RSB IRQ rate', 'rsb_irqs_per_second')):
            percent = difference[key]['percent']
            values.append(label + ': ' + (f'{percent:+.2f}%' if percent is not None else 'undefined (zero baseline)'))
        lines.append(f'- Window {difference["window"]}: ' + '; '.join(values) + '.')
    lines.extend(['', '## Private evidence', ''])
    for index, row in enumerate(rows, 1):
        lines.append(f'- Phase {index} ({row["mode"]}), boot `{row["boot_id"]}`: '
                     f'idle `{row["idle_capture"]}/`, profile `{row["profile_capture"]}/`.')
    return '\n'.join(lines) + '\n'


def main():
    os.umask(0o077)
    value = os.environ.get('NEO_COMPARISON_CAPTURE', '')
    if not value:
        raise ValueError('Set CAPTURE to the comparison directory printed by device:usb-idle-compare')
    capture = Path(value).resolve()
    summary = summarize(json.loads((capture / 'comparison.json').read_text()))
    output = markdown(summary)
    (capture / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (capture / 'summary.md').write_text(output)
    print(output, end='')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print('Cannot summarize comparison: ' + str(error), file=sys.stderr)
        sys.exit(1)
