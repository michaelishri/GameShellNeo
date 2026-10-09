"""Bounded alternating cable lineage; shared host/device admission, no I/O."""
import math

import power_key_policy as policy
import sleep_connection
import kernel_evidence

SEQUENCE = ('usb-remove', 'usb-attach', 'usb-remove', 'usb-attach')
SDIO = 'consumer:platform:1c10000.mmc'


def definition(value, count, connection):
    if (not isinstance(value, dict) or set(value) != {'id', 'sequence'} or
            value['sequence'] != list(SEQUENCE) or type(count) is not int or
            not 0 <= count < len(SEQUENCE) or connection != SEQUENCE[count]):
        raise ValueError('Require the next step of the four-cycle alternating cable batch')
    policy.run_id(value['id'])


def identity(snapshot, current):
    if kernel_evidence.KEY in snapshot or kernel_evidence.KEY in current:
        kernel_evidence.delta(snapshot, current)
    now = snapshot['monotonic_seconds']
    if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
        raise ValueError('Invalid cable batch snapshot time')
    if (any(snapshot[k] != current[k] for k in ('boot_id', 'kernel', 'image')) or
            snapshot['rsb_links'][SDIO]['consumer']['power'] !=
            current['rsb_links'][SDIO]['consumer']['power']):
        raise ValueError('Cable batch boot/image/SDIO identity changed')
    features = snapshot['image'].get('sources', {}).get('features', {})
    if (features.get('sleep_cable_irq_policy') != 'masked-cable-v2' or
            features.get('usb_system_wakeup') is not False or
            features.get('power_supply_system_wakeup') is not False or
            snapshot.get('usb_system_wakeup') != ['disabled'] or
            snapshot.get('power_supply_system_wakeup') !=
            {'axp20x-usb': 'disabled', 'axp22x-ac': 'disabled'}):
        raise ValueError('Cable batch requires the qualified disabled wake policies')


def follows(before, after):
    kernel_evidence.delta(before, after)
    times = (before['monotonic_seconds'], after['monotonic_seconds'])
    if (any(type(t) not in (int, float) or not math.isfinite(t) for t in times) or
            not 0 <= times[0] < times[1] or before['stats'] != after['stats']):
        raise ValueError('Cable batch has intervening PM, journal loss or overlapping evidence')


def ancestry(record, qualified):
    q = record['qualification']
    if any(q.get(k) != qualified.get(k) for k in
           ('runs', 'sleep_runs', 'connection', 'cable_batch', 'cable_observations')):
        raise ValueError('Cable batch ancestry or observer evidence changed')


def rehearsal(pm, prior, before, qualified, lock, completed_result, previous=None):
    token = policy.run_id(prior['run_id'])
    if token in qualified['runs'] + qualified['sleep_runs']:
        raise ValueError('Cable rehearsal reuses an ancestor ID')
    completed_result(pm, prior, lock, 'rehearse')
    if prior.get('connection') != qualified['connection']:
        raise ValueError('Cable rehearsal has another connection profile')
    ancestry(prior, qualified)
    for side in ('before', 'after'):
        identity(prior[side], before)
    follows(prior['after'], before)
    if previous is not None:
        follows(previous['after'], prior['before'])
        sleep_connection.unchanged(previous['cable']['after'], prior['cable']['before'],
                                   sleep_connection.endpoint(qualified['connection']))
        if previous['rtc']['irq_after'] != prior['rtc']['irq_before']:
            raise ValueError('RTC activity occurred before the cable rehearsal')
    return prior['rtc']['irq_after']


def history(pm, records, sleeps, current, lock, connection, batch, rehearsals,
            observations, prerequisite, completed_result, digest):
    definition(batch, len(sleeps), connection)
    if (not isinstance(rehearsals, list) or len(rehearsals) != len(sleeps) or
            not isinstance(observations, list) or len(observations) != len(sleeps)):
        raise ValueError('Each cable predecessor requires its rehearsal and observer evidence')
    identity(current, current)
    anchor = sleeps[0]['before'] if sleeps else current
    ids = prerequisite(records, anchor)
    tokens, rehearsal_ids, previous = [], [], None
    for index, (record, awake, observed) in enumerate(zip(sleeps, rehearsals, observations)):
        profile = SEQUENCE[index]
        qualified = dict(runs=ids, sleep_runs=tokens[:], connection=profile,
                         cable_batch=batch, cable_observations=observations[:index])
        token = policy.run_id(record['run_id'])
        if (token in ids + tokens + rehearsal_ids or record.get('connection') != profile or
                record['rehearsal'] != awake['run_id'] or awake['run_id'] in rehearsal_ids or
                awake['run_id'] == token):
            raise ValueError('Cable batch direction, run or rehearsal identity differs')
        completed_result(pm, record, lock, 'rtc-wake')
        ancestry(record, qualified)
        if index == 0:
            prerequisite(records, awake['before'])
        for side in ('before', 'after'):
            identity(record[side], current)
        expected = rehearsal(pm, awake, record['before'], qualified, lock,
                             completed_result, previous)
        sleep_connection.unchanged(awake['cable']['after'], record['cable']['before'],
                                   sleep_connection.endpoint(profile))
        if record['rtc']['irq_before'] != expected:
            raise ValueError('RTC activity occurred between rehearsal and cable sleep')
        parent = tokens[-1] if tokens else ids[-1]
        if record.get('parent_claim') != dict(parent=parent, run_id=token, boot_id=current['boot_id']):
            raise ValueError('Cable batch successor claim differs')
        if observed != dict(run_id=token, device_sha256=digest(record),
                            action='during-dark', display='normal'):
            raise ValueError('Cable predecessor lacks a matching successful observer report')
        tokens.append(token)
        rehearsal_ids.append(awake['run_id'])
        previous = record
    if previous is not None:
        follows(previous['after'], current)
    return dict(runs=ids, sleep_runs=tokens, connection=connection,
                cable_batch=batch, cable_observations=observations)
