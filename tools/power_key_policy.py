"""Owned, boot-local logind key policy for diagnostics; never enters sleep.

The ignore drop-in outlives the experiment process. Uncertain cleanup retains
ownership; there is deliberately no unconditional remove/restore command.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import sys
import time

from keypad_pm import exclusive_pm, save_owned
import power_key

BOOT = Path('/proc/sys/kernel/random/boot_id')
OWNED = Path('/run/gameshellneo-power-policy.json')
DROPIN = Path('/run/systemd/logind.conf.d/zz-gameshellneo-pm-guard.conf')
CONFIG_ROOTS = tuple(Path(p) for p in ('/etc', '/run', '/usr/local/lib', '/usr/lib'))
RESULTS = Path('/var/lib/gameshellneo/power-policy-tests')
KEYS = ('HandlePowerKey', 'HandlePowerKeyLongPress')
PROPERTIES = KEYS + ('HandleRebootKey', 'HandleRebootKeyLongPress',
    'HandleSuspendKey', 'HandleSuspendKeyLongPress', 'HandleHibernateKey',
    'HandleHibernateKeyLongPress', 'HandleLidSwitch', 'HandleLidSwitchExternalPower',
    'HandleLidSwitchDocked', 'IdleAction')
IGNORE = dict.fromkeys(KEYS, 'ignore')


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=10).strip()


def run_id(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise ValueError('Expected a 32-character diagnostic run ID')
    return value


def content(token):
    return ('# GameShellNeo diagnostic owner: ' + run_id(token) + '\n[Login]\n'
            'HandlePowerKey=ignore\nHandlePowerKeyLongPress=ignore\n')


def policy():
    rows = command('busctl', '--system', '--json=short', 'get-property',
        'org.freedesktop.login1', '/org/freedesktop/login1',
        'org.freedesktop.login1.Manager', *PROPERTIES).splitlines()
    values = [json.loads(row) for row in rows]
    if len(values) != len(PROPERTIES) or any(v.get('type') != 's' or
            not isinstance(v.get('data'), str) for v in values):
        raise ValueError('Unexpected effective login1 policy response')
    return dict(zip(PROPERTIES, (v['data'] for v in values)))


def identity():
    value = dict(line.split('=', 1) for line in command('systemctl', 'show',
        'systemd-logind.service', '-p',
        'MainPID,ExecMainStartTimestampMonotonic,ActiveState').splitlines())
    if (value.get('ActiveState') != 'active' or int(value.get('MainPID', 0)) <= 1 or
            int(value.get('ExecMainStartTimestampMonotonic', 0)) <= 0):
        raise ValueError('logind is not an active identified process')
    return value


def config():
    """Fingerprint all possible config inputs, excluding only our owned drop-in."""
    result = {}
    for root in CONFIG_ROOTS:
        paths = [root/'systemd/logind.conf', *(root/'systemd/logind.conf.d').glob('*.conf')]
        for path in sorted(paths):
            if path == DROPIN or not os.path.lexists(path):
                continue
            data = path.read_bytes()  # Includes /dev/null masks; broken links fail.
            result[str(path)] = dict(sha256=hashlib.sha256(data).hexdigest(),
                                    target=os.readlink(path) if path.is_symlink() else None)
    return result


def inspect():
    return dict(boot_id=BOOT.read_text().strip(), kernel=os.uname().release,
                logind=identity(), policy=policy(), config=config(),
                owned=os.path.lexists(OWNED), dropin=os.path.lexists(DROPIN))


def write_exclusive(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(text)
        output.flush()
        os.fsync(output.fileno())


def read_owned(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError('Diagnostic ownership file changed identity or permissions')
    return path.read_text()


def reload_policy(expected, process):
    if identity() != process:
        raise ValueError('logind changed before policy reload')
    command('systemctl', 'kill', '--kill-whom=main', '--signal=HUP', 'systemd-logind.service')
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if identity() != process:
            raise ValueError('logind restarted during policy reload')
        if policy() == expected:
            return
        time.sleep(0.05)
    raise TimeoutError('Effective logind policy did not match after SIGHUP')


def acquire(token, expected_boot):
    token = run_id(token)
    power_key.verify_inhibitor()
    before = inspect()
    if before['boot_id'] != expected_boot or before['owned'] or before['dropin']:
        raise ValueError('Boot changed or diagnostic policy already owned')
    if any(before['policy'][key] != 'poweroff' for key in KEYS):
        raise ValueError('Expected the ordinary diagnostic poweroff policy')
    record = dict(run_id=token, before=before)
    save_owned(record, OWNED)  # Intent precedes mutation, including failed reloads.
    write_exclusive(DROPIN, content(token))
    if config() != before['config']:
        raise ValueError('Unowned logind configuration changed during acquisition')
    reload_policy(before['policy'] | IGNORE, before['logind'])
    verify(token)
    return record


def verify(token):
    record = json.loads(read_owned(OWNED))
    if record.get('run_id') != run_id(token):
        raise ValueError('Foreign diagnostic policy owner')
    before = record['before']
    if BOOT.read_text().strip() != before['boot_id']:
        raise ValueError('Diagnostic policy belongs to another boot')
    if read_owned(DROPIN) != content(token) or config() != before['config']:
        raise ValueError('Owned drop-in or unowned configuration changed')
    if identity() != before['logind'] or policy() != before['policy'] | IGNORE:
        raise ValueError('Effective ignore policy or logind identity changed')
    return record


def restore_untouched(token, guard):
    """Only the continuously held, untouched awake guard can hand policy back.

    This is NOT a waking/held-key handoff: input-core clears need separate proof.
    There is no CLI bypass for a lost guard or interrupted ownership record.
    """
    guard.before_entry()  # Checks inhibitor, untouched stream and empty bitmap.
    record = verify(token)
    guard.before_entry()
    DROPIN.unlink()
    try:
        reload_policy(record['before']['policy'], record['before']['logind'])
        guard.before_entry()
        if config() != record['before']['config']:
            raise ValueError('Unowned configuration changed during restoration')
        if (os.path.lexists(DROPIN) or json.loads(read_owned(OWNED)) != record or
                BOOT.read_text().strip() != record['before']['boot_id']):
            raise ValueError('Diagnostic owner or boot changed during restoration')
    except BaseException:
        # Retain suppression when handoff cannot be certified. Never overwrite
        # a foreign replacement; the marker survives every restoration failure.
        if not os.path.lexists(DROPIN):
            write_exclusive(DROPIN, content(token))
            reload_policy(record['before']['policy'] | IGNORE, record['before']['logind'])
        raise
    OWNED.unlink()


def smoke(token, directory):
    """Parent owns the untouched key; a disposable policy worker is SIGKILLed."""
    record = dict(run_id=run_id(token), passed=False, mode='awake-policy-worker-death',
                  restored=False, power_key={})
    child = None
    try:
        record['before'] = inspect()
        save_owned(record, directory/'started.json')
        with exclusive_pm(OWNED.parent), power_key.own(record['power_key'], lambda: None) as guard:
            guard.before_entry()
            with (directory/'worker.stderr').open('wb') as errors:
                child = subprocess.Popen([sys.executable, '-B', __file__, '--worker',
                    '--run-id', token, '--boot-id', record['before']['boot_id']],
                    stdout=subprocess.PIPE, stderr=errors)
            ready, _, _ = select.select([child.stdout], [], [], 25)
            if not ready:
                raise TimeoutError('Policy worker did not become ready; inspect retained ownership')
            row = json.loads(child.stdout.readline())
            if row != dict(run_id=token, armed=True):
                raise ValueError('Unexpected policy-worker readiness record')
            child.kill()
            record['worker_returncode'] = child.wait(timeout=5)
            if record['worker_returncode'] != -signal.SIGKILL:
                raise ValueError('Disposable worker did not terminate with SIGKILL')
            verify(token)
            record['survived_worker_death'] = inspect()
            guard.before_entry()
            restore_untouched(token, guard)
            record['restored'] = True
        record['after'] = inspect()
        if record['after'] != record['before']:
            raise ValueError('Final policy/process/configuration state differs from baseline')
        record['passed'] = True
    except BaseException as error:
        record['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        if child is not None:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdout.close()
        record['policy_owner_retained'] = os.path.lexists(OWNED)
        record['dropin_retained'] = os.path.lexists(DROPIN)
        save_owned(record, directory/'result.json')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--smoke', action='store_true')
    mode.add_argument('--worker', action='store_true')
    parser.add_argument('--run-id')
    parser.add_argument('--boot-id')
    args = parser.parse_args()
    os.umask(0o077)
    if args.inspect:
        print(json.dumps(inspect()))
    elif args.worker:
        acquire(args.run_id, args.boot_id)
        print(json.dumps(dict(run_id=args.run_id, armed=True)), flush=True)
        while True:
            signal.pause()
    else:
        token = run_id(args.run_id)
        directory = RESULTS/token
        directory.mkdir(parents=True, exist_ok=False)
        print(json.dumps(smoke(token, directory)))


if __name__ == '__main__':
    main()
