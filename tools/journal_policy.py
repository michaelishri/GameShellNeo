"""Read-only journal evidence and narrowly scoped persistent-storage policy."""
import json
import os
from pathlib import Path
import subprocess
import sys

FILES = ('etc/default/armbian-ramlog',
         'etc/systemd/system/logrotate.service.d/50-gameshellneo.conf')


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=30).strip()


def properties(unit):
    return dict(line.split('=', 1) for line in command('systemctl', 'show', '--all', unit,
        '-p', 'Id,LoadState,ActiveState,SubState,MainPID,ExecMainStartTimestampMonotonic,NRestarts,ExecStartPre,ExecStart,ExecStartPost,LastTriggerUSec').splitlines())


def inspect():
    units = {name: properties(name) for name in ('systemd-journald.service',
        'systemd-journal-flush.service', 'logrotate.service', 'logrotate.timer',
        'armbian-ramlog.service', 'cron.service')}
    files = {name: (Path('/') / name).read_text() if (Path('/') / name).exists() else None
             for name in FILES}
    stores = {}
    for root in ('/run/log/journal', '/var/log/journal', '/var/log.hdd/journal'):
        directory = Path(root)
        inventory = []
        if directory.exists():
            for path in sorted(directory.glob('*/*.journal*')):
                stat = path.stat()
                inventory.append(dict(path=str(path), bytes=stat.st_size, uid=stat.st_uid,
                                      gid=stat.st_gid, mtime_ns=stat.st_mtime_ns))
        stores[root] = dict(exists=directory.exists(), symlink=directory.is_symlink(), files=inventory)
    pid = units['systemd-journald.service']['MainPID']
    opened = []
    for path in Path('/proc/' + pid + '/fd').glob('*'):
        try:
            target = str(path.readlink())
        except FileNotFoundError:
            continue
        if '.journal' in target:
            opened.append(target)
    return dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        kernel=os.uname().release, uptime=Path('/proc/uptime').read_text().split()[0],
        units=units, files=files, stores=stores, open_journals=sorted(opened),
        config=command('systemd-analyze', 'cat-config', 'systemd/journald.conf'),
        journal=command('journalctl', '-b', '-k', '-n', '4000', '--no-pager', '-o', 'short-monotonic'),
        logging_events=command('journalctl', '-b', '-n', '500', '-u', 'systemd-journald',
                               '-u', 'logrotate', '--no-pager', '-o', 'short-monotonic'),
        boots=command('journalctl', '--list-boots', '--no-pager'))


def validate_policy(value, policy):
    if value['files'] != policy:
        raise ValueError('Journal policy differs from the saved source files')
    unit = value['units']['logrotate.service']
    if unit['LoadState'] != 'loaded':
        raise ValueError('Log rotation unit is not loaded')
    # systemd can omit empty Exec command arrays even with show --all.
    if unit.get('ExecStartPre') or unit.get('ExecStartPost'):
        raise ValueError('Log rotation still has pre/post hooks')
    if '/usr/sbin/logrotate' not in unit['ExecStart']:
        raise ValueError('Ordinary text-log rotation is missing')
    if value['units']['armbian-ramlog.service']['LoadState'] != 'masked':
        raise ValueError('Armbian RAM-log service is not masked')
    if not any(path.startswith('/var/log/journal/') and not path.endswith(' (deleted)')
               for path in value['open_journals']):
        raise ValueError('Journald has no open persistent journal; preserve evidence before recovery')


def validate_continuity(before, after):
    if before['boot_id'] != after['boot_id']:
        raise ValueError('Device rebooted')
    for key in ('MainPID', 'ExecMainStartTimestampMonotonic'):
        if before['units']['systemd-journald.service'][key] != after['units']['systemd-journald.service'][key]:
            raise ValueError('Journald restarted during the check')
    if not after['journal'].startswith(before['journal']):
        raise ValueError('Kernel evidence changed or exceeded the bounded capture')
    if before['stores']['/var/log.hdd/journal'] != after['stores']['/var/log.hdd/journal']:
        raise ValueError('Displaced journals changed during the check')


def validate_rotation(before, after):
    old = before['units']['logrotate.service']['ExecMainStartTimestampMonotonic']
    new = after['units']['logrotate.service']['ExecMainStartTimestampMonotonic']
    if int(new) <= int(old):
        raise ValueError('Log rotation did not execute; its AC-power condition may have skipped it')
    if after['units']['logrotate.service']['ActiveState'] != 'inactive':
        raise ValueError('Log rotation did not finish normally')


def apply(policy, expected_boot):
    if set(policy) != set(FILES) or not all(isinstance(value, str) for value in policy.values()):
        raise ValueError('Only the two journal policy files may be installed')
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != expected_boot:
        raise ValueError('Device rebooted before policy application')
    timer_active = properties('logrotate.timer')['ActiveState'] == 'active'
    command('systemctl', 'stop', 'logrotate.timer')
    try:
        if properties('logrotate.service')['ActiveState'] not in ('inactive', 'failed'):
            raise ValueError('Log rotation is already running; preserve its result first')
        # Disable direct helpers first. Both updates are atomic; interrupted
        # application leaves a conservative disabled helper, not journal repair.
        for name in FILES:
            path = Path('/') / name
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + '.gameshellneo-new')
            with temporary.open('x') as output:
                os.fchmod(output.fileno(), 0o644)
                output.write(policy[name])
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(path)
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        command('systemctl', 'daemon-reload')
    finally:
        if timer_active:
            command('systemctl', 'start', 'logrotate.timer')


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('Root is required to inspect journal ownership')
    if len(sys.argv) > 1:
        if len(sys.argv) != 4 or sys.argv[1] != '--apply':
            raise SystemExit('Use no arguments for inspection, or --apply POLICY BOOT')
        apply(json.loads(sys.argv[2]), sys.argv[3])
    print(json.dumps(inspect(), indent=2))
