#!/usr/bin/env python3
"""Awake kernel-evidence append smoke test; no PM, screen, radio or journal policy changes."""
import fcntl
import hashlib
import importlib.util
import json
import os
import uuid

import kernel_evidence as evidence
from private_config import load_env
from remote import LOCAL, ROOT, device, evidence_directory, python_command, run


PROBE = '''import json, os, re, stat, sys
from pathlib import Path
root = Path('/var/lib/gameshellneo/kernel-evidence')
token = sys.argv[1] if len(sys.argv) == 2 else None
if token is not None:
    if not re.fullmatch('[0-9a-f]{32}', token):
        raise ValueError('Invalid smoke token')
    data = ('<15>gameshellneo-kernel-evidence-smoke ' + token + '\\n').encode()
    fd = os.open('/dev/kmsg', os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if not stat.S_ISCHR(os.fstat(fd).st_mode):
            raise ValueError('Expected printk character device')
        if os.write(fd, data) != len(data):
            raise OSError('Incomplete marker write; do not retry')
    finally:
        os.close(fd)
def metadata(path):
    s = path.lstat()
    return dict(uid=s.st_uid, mode=stat.S_IMODE(s.st_mode), links=s.st_nlink,
                regular=stat.S_ISREG(s.st_mode), directory=stat.S_ISDIR(s.st_mode),
                bytes=s.st_size, inode=s.st_ino, mtime_ns=s.st_mtime_ns)
print(json.dumps(dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
    directory=metadata(root), entries=sorted(p.name for p in root.iterdir()),
    files={name:metadata(root/name) for name in ('checkpoint.json','lock')}, marker=token)))
'''


def pm_host():
    spec = importlib.util.spec_from_file_location('kernel_smoke_pm', ROOT/'tools/check-pm-stages.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def validate_storage(value, snapshot):
    if (value['boot_id'] != snapshot['boot_id'] or value['entries'] != ['checkpoint.json','lock'] or
            set(value['files']) != {'checkpoint.json','lock'} or
            value['directory']['uid'] != 0 or value['directory']['mode'] != 0o700 or
            value['directory']['directory'] is not True):
        raise ValueError('Kernel evidence directory identity or interruption state failed')
    for name, data in value['files'].items():
        if data['uid'] != 0 or data['mode'] != 0o600 or not data['regular'] or data['links'] != 1:
            raise ValueError('Kernel evidence file protection failed')
        expected = len(evidence.encoded(snapshot[evidence.KEY])) if name == 'checkpoint.json' else 0
        if data['bytes'] != expected:
            raise ValueError('Kernel evidence file size differs from the snapshot')


def validate(before, after, token, lock, pm):
    for value in (before,after):
        pm.validate(value,lock)
        if evidence.KEY not in value:
            raise ValueError('Smoke requires sequence-checked evidence')
    evidence.delta(before,after)
    for name in ('boot_id','kernel','image','stats','backlight','inputs','pm','charger','cpu_policy',
                 'wifi_config_sha256','wifi_power_save','usb','external_power','services'):
        if before[name] != after[name]:
            raise ValueError('Awake state changed: '+name)
    message = 'gameshellneo-kernel-evidence-smoke '+token
    old, new = before[evidence.KEY]['records'],after[evidence.KEY]['records']
    matches = [evidence.parse(raw) for raw in new if evidence.parse(raw)[3] == message]
    if (len(matches) != 1 or matches[0][0] < len(old) or matches[0][1] != 15 or
            message in before['journal'] or message in after['journal']):
        raise ValueError('Marker missing, duplicated or used as kernel-origin text')
    return dict(passed=True, boot_id=before['boot_id'], records_before=len(old),
                records_after=len(new), marker_sequence=matches[0][0], marker_priority=15,
                pm_unchanged=True, screen_unchanged=True,
                limits='Awake append/readback only; no PM, ring-overrun or crash-recovery hardware qualification.')


def experiment(config, capture, host, token):
    lock=json.loads((ROOT/'build/sources.lock.json').read_text())
    pm=host.module('kernel_smoke_validator','test-pm-stages.py')
    def save(name, raw):
        (capture/name).write_bytes(raw)
        return json.loads(raw)
    with device(config,'usb') as client:
        before=save('before.json',host.inline(client,'--inspect'))
        pm.validate(before,lock)
        storage=save('storage-before.json',run(client,**python_command(PROBE),display=False))
        validate_storage(storage,before)
        active=run(client,'systemctl list-units --all --plain --no-legend '
            '--state=active,activating,deactivating gameshellneo-*.service',display=False).decode()
        allowed={'gameshellneo-usb.service','gameshellneo-battery.service','gameshellneo-ready.service'}
        if any(line.split()[0] not in allowed for line in active.splitlines() if line.split()):
            raise ValueError('Another diagnostic is active; do not inject the marker')
        # One marker submission, never retried even if its reply is lost.
        save('marker.json',run(client,**python_command(PROBE,token),display=False))
        after=save('after.json',host.inline(client,'--inspect'))
        result=validate(before,after,token,lock,pm)
        storage=save('storage-after.json',run(client,**python_command(PROBE),display=False))
        validate_storage(storage,after)
    # Independent, non-mutating Wi-Fi proof follows original USB evidence.
    host.wifi_proof(config,after)
    result.update(usb_ssh_verified=True,wifi_ssh_verified=True)
    (capture/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    os.umask(0o077)
    capture=evidence_directory()
    print('Private awake kernel-evidence smoke:',capture,flush=True)
    token=uuid.uuid4().hex
    names=('check-kernel-evidence','kernel_evidence','test-pm-stages','check-pm-stages')
    (capture/'source.json').write_text(json.dumps(dict(token=token,sources={name:hashlib.sha256(
        (ROOT/'tools'/(name+'.py')).read_bytes()).hexdigest() for name in names}),indent=2)+'\n')
    with (LOCAL/'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            experiment(load_env(),capture,pm_host(),token)
        except BaseException as error:
            (capture/'failure.json').write_text(json.dumps(dict(passed=False,token=token,
                error=type(error).__name__,marker_may_have_been_written=True,
                instruction='Preserve original files; do not automatically repeat marker submission.'))+'\n')
            raise
    print('Awake kernel-evidence append passed; both routes verified; no PM submitted.')


if __name__=='__main__':main()
