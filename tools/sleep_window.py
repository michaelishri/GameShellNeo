"""Bounded RTC test durations and uncalibrated, awake battery endpoints."""
import json
import math
from pathlib import Path
import time

from battery_sample import sample_age

DEFAULT_SECONDS = 30
ALLOWED_SECONDS = (30, 60)
MAX_ENDPOINT_SECONDS = 5


def duration(seconds, connection='usb'):
    if type(seconds) is not int or seconds not in ALLOWED_SECONDS:
        raise ValueError('RTC alarm duration must be exactly 30 or 60 seconds')
    if connection not in ('usb', 'battery', 'usb-remove', 'usb-attach'):
        raise ValueError('Unknown sleep connection profile')
    if seconds != DEFAULT_SECONDS and connection not in ('usb', 'battery'):
        raise ValueError('Extended duration requires an unchanged USB or battery connection')
    return seconds


def recorded(record):
    # Historical records were fixed at 30 s. This fallback does not requalify
    # their source hashes or allow them to serve as a 60-second rehearsal.
    return duration(record.get('alarm_seconds', DEFAULT_SECONDS), record.get('connection', 'usb'))


def budget(seconds):
    duration(seconds)
    # Keep the existing awake setup/recovery allowances. A systemd timeout
    # cannot wake a frozen system; the separately verified RTC alarm must do so.
    return dict(service_seconds=seconds+150, collection_seconds=seconds+180)


def minimum_margin(seconds):
    return duration(seconds)-15  # At most 15 seconds of setup after arming.


def observe(root=Path('/')):
    """Sequential sysfs reads, bracketed by BOOTTIME; never a sleep integral."""
    read = lambda name: (root/name).read_text().strip()
    start = time.clock_gettime(time.CLOCK_BOOTTIME)
    boot_id = read('proc/sys/kernel/random/boot_id')
    battery = 'sys/class/power_supply/axp20x-battery/'
    value = dict(boot_id=boot_id, boottime_before=start,
        status=read(battery+'status'),
        **{field: int(read(battery+name)) for field, name in
           (('present', 'present'), ('capacity_percent', 'capacity'),
            ('voltage_uv', 'voltage_now'), ('current_ua', 'current_now'))},
        temperature_millic=int(read('sys/class/thermal/thermal_zone0/temp')),
        external={name: {field: int(read('sys/class/power_supply/'+name+'/'+field))
                         for field in ('present', 'online')}
                  for name in ('axp20x-usb', 'axp22x-ac')},
        guard=json.loads(read('run/gameshellneo/battery.json')))
    value['boottime_after'] = time.clock_gettime(time.CLOCK_BOOTTIME)
    if read('proc/sys/kernel/random/boot_id') != boot_id:
        raise ValueError('Boot changed during battery endpoint reads')
    return value


def validate(value, boot_id, connection, *, admission=False):
    """60-second operating gate, not a capacity model or asleep protection."""
    start, end = value['boottime_before'], value['boottime_after']
    if (value['boot_id'] != boot_id or
            any(type(t) not in (int, float) or not math.isfinite(t) for t in (start, end)) or
            not 0 <= start <= end <= start+MAX_ENDPOINT_SECONDS):
        raise ValueError('Invalid battery endpoint boot or read window')
    for field in ('present', 'capacity_percent', 'voltage_uv', 'current_ua', 'temperature_millic'):
        if type(value[field]) is not int:
            raise ValueError('Invalid battery endpoint integer')
    # Conservative test entry reserve. These are software operating limits,
    # not asserted electrical pack limits or calibrated state of charge.
    capacity_floor, voltage_floor = (50, 3800000) if admission else (20, 3500000)
    if (value['present'] != 1 or not capacity_floor < value['capacity_percent'] <= 100 or
            not voltage_floor <= value['voltage_uv'] <= 4300000 or
            not -500000 <= value['current_ua'] <= 1500000 or
            not 0 <= value['temperature_millic'] < 60000):
        raise ValueError('Battery endpoint is outside the bounded-trial reserve or operating limits')
    if connection not in ('usb', 'battery'):
        raise ValueError('Battery endpoint requires a fixed connection')
    online = int(connection == 'usb')
    expected = {name: dict(present=online, online=online) for name in ('axp20x-usb', 'axp22x-ac')}
    if (value['external'] != expected or
            value['status'] not in (('Discharging',) if not online else ('Charging', 'Full', 'Not charging', 'Discharging')) or
            (not online and value['current_ua'] > 0)):
        raise ValueError('Battery endpoint differs from the unchanged connection')
    if admission and (value['guard'].get('monitoring') != 'valid' or
            sample_age(value['guard'], now=end, boot_id=boot_id) > 25):
        raise ValueError('Fresh valid battery guard required before extended RTC trial')
    # At return the guard may still hold its pre-sleep sample. Direct reads
    # above are the observation; ordinary postflight separately checks refresh.


def fresh(value, now):
    if (type(now) not in (int, float) or not math.isfinite(now) or
            not value['boottime_after'] <= now <= value['boottime_before']+MAX_ENDPOINT_SECONDS):
        raise ValueError('Battery endpoint became stale before PM submission')


def assess(record):
    """Recheck timing and reserve without manufacturing sleep energy."""
    if recorded(record) == DEFAULT_SECONDS:
        return None
    boot_id, connection = record['before']['boot_id'], record['connection']
    points = record['battery_window']
    for side in ('admission', 'entry', 'returned'):
        validate(points[side], boot_id, connection, admission=side != 'returned')
    a, b = points['entry'], points['returned']
    if points['admission']['boottime_after'] > a['boottime_before']:
        raise ValueError('Battery admission and entry endpoints are out of order')
    if a['boottime_before'] < record['rtc']['started']['boot']:
        raise ValueError('Battery entry endpoint precedes the owned alarm')
    # Rehearsal endpoints span the awake alarm wait. Actual entry additionally
    # binds the pre-reading to the immediate pre-write clock, excluding setup.
    if record['mode'] == 'rtc-wake':
        fresh(a, record['entry_clock']['boot'])
    else:
        fresh(a, record['battery_entry_checked_boot'])
    returned = record['returned']['boot']
    if not a['boottime_after'] <= returned <= b['boottime_before'] <= b['boottime_after'] <= returned+MAX_ENDPOINT_SECONDS:
        raise ValueError('Battery return endpoint is delayed or outside the submitted interval')
    return dict(capacity_before_percent=a['capacity_percent'], capacity_after_percent=b['capacity_percent'],
                voltage_before_uv=a['voltage_uv'], voltage_after_uv=b['voltage_uv'],
                endpoint_span_seconds=b['boottime_after']-a['boottime_before'],
                energy_qualified=False, calibrated=False,
                limits='Awake endpoint reads include entry/resume overhead. Gauge deltas are not charge or energy; '
                       'current is instantaneous awake current, never integrated across sleep.')
