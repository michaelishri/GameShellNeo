#!/usr/bin/env python3
"""Reusable SSH operations for the diagnostic GameShell and the owner's Mac."""
import argparse
import base64
import hashlib
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import posixpath
import re
import shlex
import shutil
import socket
import sys

import paramiko
from private_config import load_env

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local'
STATUS_COMMAND = '''
uname -r; hostname; uptime; nproc; free -m
systemctl show gameshellneo-usb gameshellneo-battery gameshellneo-ready ssh systemd-networkd wpa_supplicant@wlan0 -p Id -p ActiveState -p SubState -p Result -p NRestarts
systemctl --failed --no-pager
cat /run/gameshellneo/ready.json /run/gameshellneo/battery.json
ip -brief address
cat /sys/class/udc/*/state /sys/class/udc/*/current_speed
cat /sys/devices/system/cpu/cpufreq/policy0/scaling_governor /sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq /sys/class/thermal/thermal_zone0/temp
cat /proc/sys/kernel/tainted
systemd-analyze
'''


def private_path(value, default):
    return Path(value or default).expanduser().resolve()


def connect_mac(config):
    identity = config.get('M2_MACBOOK_AIR_IP') or config.get('M2_MACBOOK_AIR_TAILNET')
    endpoint = config.get('M2_MACBOOK_AIR_TAILNET') or identity
    if not identity:
        raise ValueError('Configure the Mac SSH address in .env')
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    known = LOCAL / 'ssh/known_hosts'
    if known.exists():
        client.load_host_keys(str(known))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    sock = None
    try:
        # Use the existing Mac identity for host-key verification even when
        # reaching that same host through its explicitly configured tailnet IP.
        if endpoint != identity:
            sock = socket.create_connection((endpoint, 22), timeout=10)
        client.connect(identity, username=config['M2_MACBOOK_AIR_USERNAME'],
                       password=config.get('M2_MACBOOK_AIR_PASSWORD') or None,
                       key_filename=config.get('M2_MACBOOK_AIR_KEY') or None,
                       sock=sock, timeout=10, auth_timeout=10, banner_timeout=10)
    except BaseException:
        client.close()
        if sock is not None:
            sock.close()
        raise
    return client


@contextmanager
def device(config, route):
    via_mac = config.get('GAMESHELL_WIFI_VIA_MAC') or '0'
    if route not in ('usb', 'wifi') or via_mac not in ('0', '1'):
        raise ValueError('Use ROUTE=usb/wifi and GAMESHELL_WIFI_VIA_MAC=0/1')
    with ExitStack() as stack:
        address = config.get('GAMESHELL_USB_IP', '192.168.10.1') if route == 'usb' else config['GAMESHELL_IP']
        sock = None
        if route == 'usb' or via_mac == '1':
            mac = stack.enter_context(connect_mac(config))
            sock = mac.get_transport().open_channel('direct-tcpip', (address, 22), ('127.0.0.1', 0), timeout=10)
            stack.callback(sock.close)
        public = private_path(config.get('NEO_HOST_PUBLIC_KEY'), LOCAL / 'provisioning/device/ssh_host_ed25519_key.pub')
        fields = public.read_text().split()
        if fields[0] != 'ssh-ed25519':
            raise ValueError('Expected the provisioned Ed25519 device host key')
        client = stack.enter_context(paramiko.SSHClient())
        client.get_host_keys().add(address, fields[0], paramiko.Ed25519Key(data=base64.b64decode(fields[1])))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        key = private_path(config.get('NEO_SSH_KEY'), LOCAL / 'ssh/id_ed25519')
        client.connect(address, username=config.get('GAMESHELL_USERNAME', 'cpi'), key_filename=str(key),
                       sock=sock, look_for_keys=False, allow_agent=False,
                       timeout=10, auth_timeout=10, banner_timeout=10)
        yield client


def run(client, command, password=None, output=None, display=True, timeout=300):
    """Drain one combined channel to avoid stdout/stderr deadlocks."""
    channel = client.get_transport().open_session(timeout=10)
    channel.settimeout(timeout)
    channel.set_combine_stderr(True)
    try:
        channel.exec_command(command)
        if password is not None:
            channel.sendall((password + '\n').encode())
        channel.shutdown_write()
        data = bytearray()
        while True:
            chunk = channel.recv(65536)
            if not chunk:
                break
            data.extend(chunk)
            if output:
                output.write(chunk)
                output.flush()
            if display:
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
        code = channel.recv_exit_status()
        if code:
            raise RuntimeError('Remote command failed (exit {})'.format(code))
        return bytes(data)
    finally:
        channel.close()


def evidence_directory():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    root = LOCAL / 'diagnostics'
    if os.environ.get('NEO_EVIDENCE_ROOT'):
        # A workflow may group fresh captures beneath its private step directory.
        # Never redirect diagnostics into the repository or an unrelated path.
        root = Path(os.environ['NEO_EVIDENCE_ROOT']).resolve(strict=True)
        if not root.is_dir() or not root.is_relative_to((LOCAL / 'diagnostics').resolve()):
            raise ValueError('Evidence root must exist inside .local/diagnostics')
    directory = root / stamp
    directory.mkdir(mode=0o700, parents=True)
    return directory


def governor_command(remote_dir, seconds, rate):
    if not re.fullmatch(r'/tmp/gameshellneo-governor\.[A-Za-z0-9]+', remote_dir):
        raise ValueError('Unexpected temporary governor comparison directory')
    if not 60 <= seconds <= 300 or seconds % 30 or not 1000 <= rate <= 100000:
        raise ValueError('SECONDS must be a multiple of 30 in 60..300; RATE_US must be 1000..100000')
    script = remote_dir + '/compare-governor.py'
    return ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe', '--collect',
            '--unit=gameshellneo-governor-comparison',
            '--description=GameShellNeo temporary schedutil rate comparison',
            '--property=RuntimeMaxSec=' + str(3 * (seconds + 30) + 60),
            '--property=TimeoutStopSec=15', '--property=Nice=10',
            '--property=ExecStopPost=/usr/bin/python3 -B ' + script + ' --restore',
            '/usr/bin/python3', '-B', '-u', script, '--seconds', str(seconds), '--rate-us', str(rate)]


def device_action(config, action, route):
    with device(config, route) as client:
        if action == 'exec':
            arguments = shlex.split(os.environ.get('NEO_COMMAND', ''))
            if not arguments:
                raise ValueError('Supply a command after --, e.g. task device:exec -- uname -r')
            run(client, shlex.join(arguments))
            return
        directory = evidence_directory()
        if action == 'check':
            country = config.get('GAMESHELL_WIFI_COUNTRY', '')
            active_country = os.environ.get('NEO_ACTIVE_COUNTRY') or country
            if not all(re.fullmatch(r'[A-Z]{2}', value) for value in (country, active_country)):
                raise ValueError('Set a valid GAMESHELL_WIFI_COUNTRY; ACTIVE_COUNTRY is optional')
            lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
            remote_dir = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-check.XXXXXXXX',
                             display=False).decode().strip()
            if not re.fullmatch(r'/tmp/gameshellneo-check\.[A-Za-z0-9]+', remote_dir):
                raise ValueError('Unexpected temporary check directory')
            script = remote_dir + '/check-device.py'
            with client.open_sftp() as sftp:
                try:
                    upload(sftp, ROOT / 'tools/check-device.py', script)
                    arguments = ['sudo', '-n', '/usr/bin/python3', script,
                                 '--kernel', lock['linux']['tag'][1:] + lock['linux']['localversion'],
                                 '--version', lock['image_version'], '--country', country,
                                 '--active-country', active_country]
                    with (directory / 'integration.json').open('wb') as output:
                        run(client, shlex.join(arguments), output=output)
                finally:
                    for path in (script, script + '.part'):
                        try:
                            sftp.remove(path)
                        except FileNotFoundError:
                            pass
                    sftp.rmdir(remote_dir)
                    print('Private integration evidence:', directory)
            return
        elif action == 'usb-policy':
            mode = os.environ.get('NEO_USB_POLL_MODE', 'status')
            if mode not in ('status', 'stock', 'experimental'):
                raise ValueError('MODE must be status, stock or experimental')
            arguments = ['sudo', '-n', 'python3', '-c',
                         (ROOT / 'tools/usb_poll_boot.py').read_text(), '--mode', mode]
            with (directory / 'usb-policy.txt').open('wb') as output:
                run(client, shlex.join(arguments), output=output, timeout=30)
        elif action == 'battery-check':
            source = ROOT / 'runtime/usr/local/lib/gameshellneo/battery_guard.py'
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            arguments = ['env', 'NEO_BATTERY_MODULE=/usr/local/lib/gameshellneo/battery_guard.py',
                         'NEO_BATTERY_SHA256=' + digest, '/usr/bin/timeout', '60',
                         '/usr/bin/python3', '-B', '-c',
                         (ROOT / 'runtime/tests/test_battery.py').read_text(), '-v']
            with (directory / 'battery-policy.txt').open('wb') as output:
                run(client, shlex.join(arguments), output=output, timeout=90)
        elif action == 'idle-sample':
            print('Capturing private idle sample:', directory / 'idle-sample.jsonl', flush=True)
            seconds = int(os.environ.get('NEO_IDLE_SECONDS', '600'))
            backlight = os.environ.get('NEO_IDLE_BACKLIGHT', 'keep')
            if not 60 <= seconds <= 3600 or seconds % 10:
                raise ValueError('SECONDS must be a multiple of 10 in 60..3600')
            if backlight not in ('keep', 'off'):
                raise ValueError('BACKLIGHT must be keep or off')
            arguments = ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe',
                         '--collect', '--unit=gameshellneo-idle-sample',
                         '--property=RuntimeMaxSec=' + str(seconds + 120),
                         '--property=TimeoutStopSec=10', '--property=Nice=10',
                         '/usr/bin/python3', '-B', '-u', '-c',
                         (ROOT / 'tools/sample-idle.py').read_text(), '--seconds', str(seconds),
                         '--backlight', backlight]
            with (directory / 'idle-sample.jsonl').open('wb') as output:
                run(client, shlex.join(arguments), output=output, timeout=90)
        elif action == 'power-profile':
            seconds = int(os.environ.get('NEO_PROFILE_SECONDS', '120'))
            if not 30 <= seconds <= 300 or seconds % 30:
                raise ValueError('SECONDS must be a multiple of 30 in 30..300')
            arguments = ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe',
                         '--collect', '--unit=gameshellneo-power-profile',
                         '--description=GameShellNeo awake-power counter profile',
                         '--property=RuntimeMaxSec=' + str(seconds + 90),
                         '--property=TimeoutStopSec=10', '--property=Nice=10',
                         '/usr/bin/python3', '-B', '-u', '-c',
                         (ROOT / 'tools/profile-power.py').read_text(), '--seconds', str(seconds)]
            path = directory / 'power-profile.jsonl'
            print('Capturing private profile:', path, flush=True)
            with path.open('wb') as output:
                run(client, shlex.join(arguments), output=output, display=False, timeout=seconds + 90)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            if not records or records[-1].get('event') != 'complete' or not records[-1].get('passed'):
                raise ValueError('Incomplete power profile; inspect the private capture')
            result = records[-1]
            for key in ('interrupts', 'softirqs', 'processes'):
                result[key] = result[key][:10]
            print(json.dumps(result, indent=2))
        elif action == 'wifi-scan-restore':
            if route != 'usb':
                raise ValueError('Restore scan-test state through ROUTE=usb')
            # Wait for a running comparison and its exit hook before restoring;
            # otherwise its next phase could overwrite the restored flag.
            loaded = run(client, 'systemctl show gameshellneo-scan-test -p LoadState --value',
                         display=False, timeout=10).decode().strip()
            if loaded != 'not-found':
                run(client, 'sudo -n systemctl stop gameshellneo-scan-test',
                    display=False, timeout=45)
            arguments = ['sudo', '-n', '/usr/bin/python3', '-B', '-c',
                         (ROOT / 'tools/test-wifi-scanning.py').read_text(), '--restore']
            with (directory / 'scan-restore.txt').open('wb') as output:
                run(client, shlex.join(arguments), output=output, timeout=45)
            print('Scan comparison stopped; any saved scan-offload setting restored.')
        elif action == 'wifi-scan-test':
            seconds = int(os.environ.get('NEO_PROFILE_SECONDS', '120'))
            if route != 'usb' or not 60 <= seconds <= 180 or seconds % 10:
                raise ValueError('Use ROUTE=usb and SECONDS a multiple of ten in 60..180')
            remote_dir = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-scan.XXXXXXXX',
                             display=False).decode().strip()
            if not re.fullmatch(r'/tmp/gameshellneo-scan\.[A-Za-z0-9]+', remote_dir):
                raise ValueError('Unexpected scan-test directory')
            script = remote_dir + '/test-wifi-scanning.py'
            with client.open_sftp() as sftp:
                upload(sftp, ROOT / 'tools/test-wifi-scanning.py', script)
            arguments = ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe', '--collect',
                         '--unit=gameshellneo-scan-test',
                         '--property=RuntimeMaxSec=' + str(3 * (seconds + 10) + 90),
                         '--property=TimeoutStopSec=30',
                         '--property=ExecStopPost=/usr/bin/python3 -B ' + script + ' --restore',
                         '/usr/bin/python3', '-B', '-u', script, '--seconds', str(seconds)]
            print('Private scan comparison:', directory, flush=True)
            print('Retain device helper on failure:', remote_dir, flush=True)
            path = directory / 'wifi-scanning.jsonl'
            with path.open('wb') as output:
                run(client, shlex.join(arguments), output=output, timeout=60)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            if not records or records[-1].get('event') != 'complete' or not records[-1].get('passed'):
                raise ValueError('Incomplete scan comparison; verify runtime-setting restoration')
            with client.open_sftp() as sftp:
                sftp.remove(script)
                sftp.rmdir(remote_dir)
        elif action == 'governor-compare':
            seconds = int(os.environ.get('NEO_PROFILE_SECONDS', '120'))
            rate = int(os.environ.get('NEO_GOVERNOR_RATE_US', '10000'))
            governor_command('/tmp/gameshellneo-governor.validation', seconds, rate)
            if route != 'wifi':
                raise ValueError('Governor comparison requires ROUTE=wifi and USB unplugged')
            remote_dir = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-governor.XXXXXXXX',
                             display=False).decode().strip()
            arguments = governor_command(remote_dir, seconds, rate)
            names = ('compare-governor.py', 'profile-power.py', 'sample-idle.py')
            with client.open_sftp() as sftp:
                for name in names:
                    upload(sftp, ROOT / 'tools' / name, remote_dir + '/' + name)
            path = directory / 'governor-comparison.jsonl'
            print('Capturing private comparison:', path, flush=True)
            print('Device helper directory (retain on failure for recovery):', remote_dir, flush=True)
            # Do not remove helpers after a transport error: ExecStopPost may still need them.
            with path.open('wb') as output:
                run(client, shlex.join(arguments), output=output, display=False,
                    timeout=3 * (seconds + 30) + 90)
            with client.open_sftp() as sftp:
                for name in names:
                    sftp.remove(remote_dir + '/' + name)
                sftp.rmdir(remote_dir)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            if not records or records[-1].get('event') != 'complete' or not records[-1].get('passed'):
                raise ValueError('Incomplete governor comparison; inspect the private capture')
            result = records[-1]
            for phase in result['phases']:
                for key in ('interrupts', 'softirqs', 'processes'):
                    phase['counters'][key] = phase['counters'][key][:10]
            print(json.dumps(result, indent=2))
        elif action == 'governor-profile':
            seconds = int(os.environ.get('NEO_PERF_SECONDS', '30'))
            if route != 'wifi' or not 10 <= seconds <= 60:
                raise ValueError('Use ROUTE=wifi with USB unplugged and SECONDS in 10..60')
            binary = LOCAL / 'build/perf/perf'
            expected = (binary.parent / 'perf.sha256').read_text().split()[0]
            if hashlib.sha256(binary.read_bytes()).hexdigest() != expected:
                raise ValueError('perf binary hash mismatch; run task build:perf')
            remote_dir = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-sugov.XXXXXXXX',
                             display=False).decode().strip()
            if not re.fullmatch(r'/tmp/gameshellneo-sugov\.[A-Za-z0-9]+', remote_dir):
                raise ValueError('Unexpected temporary governor profile directory')
            names = ('profile-governor.py', 'profile-power.py')
            artifacts = ('perf.data', 'perf-record.txt', 'perf-report.txt', 'kallsyms.txt')
            with client.open_sftp() as sftp:
                for name in names:
                    upload(sftp, ROOT / 'tools' / name, remote_dir + '/' + name)
                upload(sftp, binary, remote_dir + '/perf')
                sftp.chmod(remote_dir + '/perf', 0o700)
            print('Capturing private governor profile:', directory, flush=True)
            print('Device helper directory (retained on failure):', remote_dir, flush=True)
            arguments = ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe', '--collect',
                         '--unit=gameshellneo-governor-profile',
                         '--property=RuntimeMaxSec=' + str(seconds + 60),
                         '--property=TimeoutStopSec=15', '--property=Nice=10',
                         '/usr/bin/python3', '-B', '-u', remote_dir + '/profile-governor.py',
                         '--seconds', str(seconds)]
            path = directory / 'governor-profile.jsonl'
            try:
                with path.open('wb') as output:
                    run(client, shlex.join(arguments), output=output, display=False, timeout=seconds + 90)
            finally:
                # Keep error diagnostics too; a missing artifact never implies a successful capture.
                with client.open_sftp() as sftp:
                    for name in artifacts:
                        try:
                            sftp.get(remote_dir + '/' + name, str(directory / name))
                        except FileNotFoundError:
                            pass
            records = [json.loads(line) for line in path.read_text().splitlines()]
            if not records or records[-1].get('event') != 'complete' or not records[-1].get('passed'):
                raise ValueError('Incomplete governor profile; inspect the private capture')
            with client.open_sftp() as sftp:
                for name in (*names, *artifacts, 'perf'):
                    sftp.remove(remote_dir + '/' + name)
                sftp.rmdir(remote_dir)
            print((directory / 'perf-report.txt').read_text())
        elif action == 'stability':
            arguments = ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe',
                         '--collect', '--unit=gameshellneo-stability-test',
                         '--property=RuntimeMaxSec=420', '--property=TimeoutStopSec=15',
                         '--property=Nice=10', '/usr/bin/python3', '-u', '-c',
                         (ROOT / 'tools/check-stability.py').read_text()]
            with (directory / 'stability.jsonl').open('wb') as output:
                run(client, shlex.join(arguments), output=output)
        elif action == 'backlight':
            arguments = ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe',
                         '--collect', '--unit=gameshellneo-backlight-test',
                         '--property=RuntimeMaxSec=60', '--property=TimeoutStopSec=5',
                         '/bin/sh', '-c', (ROOT / 'tools/check-backlight.sh').read_text()]
            with (directory / 'backlight.txt').open('wb') as output:
                run(client, shlex.join(arguments), output=output)
        elif action == 'status':
            with (directory / 'status.txt').open('wb') as output:
                run(client, STATUS_COMMAND, output=output)
        else:
            archive = run(client, 'sudo -n gameshellneo-collect', display=False).decode().strip()
            if not re.fullmatch(r'/var/tmp/gameshellneo-diagnostics\.[A-Za-z0-9]+\.tar\.gz', archive):
                raise ValueError('Unexpected diagnostic archive path')
            # Keep stderr separate from the binary archive and propagate errors.
            stdin, stdout, stderr = client.exec_command('sudo -n cat ' + shlex.quote(archive), timeout=60)
            stdin.close()
            with (directory / 'device.tar.gz.part').open('wb') as output:
                while chunk := stdout.read(1024 * 1024):
                    output.write(chunk)
            error = stderr.read().decode()
            if stdout.channel.recv_exit_status():
                raise RuntimeError('Diagnostic download failed: ' + error)
            (directory / 'device.tar.gz.part').replace(directory / 'device.tar.gz')
            stdout.close()
            stderr.close()
        print('Private capture:', directory)


def upload(sftp, source, destination):
    sftp.put(str(source), destination + '.part')
    sftp.chmod(destination + '.part', 0o600)
    sftp.posix_rename(destination + '.part', destination)


def sudo(config, arguments):
    password = config.get('M2_MACBOOK_AIR_SUDO_PASSWORD', config.get('M2_MACBOOK_AIR_PASSWORD'))
    flags = ['sudo', '-S', '-p', ''] if password else ['sudo', '-n']
    return shlex.join(flags + arguments), password


def staged_arguments(sftp, directory):
    with sftp.open(directory + '/transfer.json') as stream:
        manifest = json.load(stream)
    name = manifest['compressed_file']
    if posixpath.basename(name) != name or not name.endswith('.img.gz'):
        raise ValueError('Unexpected transfer filename')
    return ['/usr/bin/python3', '-u', directory + '/flash-macos.py',
            '--image', directory + '/' + name, '--manifest', directory + '/transfer.json',
            '--target', directory + '/target.json']


def stage_recovery(client, sftp, directory, recovery, allow_upload=False):
    compressed, metadata, manifest = recovery
    destination = directory + '/' + compressed.name
    try:
        size = sftp.stat(destination).st_size
    except FileNotFoundError:
        size = None
    if size is None:
        if not allow_upload:
            raise ValueError('Recovery archive is absent on the Mac; use UPLOAD=1 on an approved network')
        print('Uploading retained recovery image to the Mac...', flush=True)
        upload(sftp, compressed, destination)
    elif size != manifest['compressed_bytes']:
        raise ValueError('Existing Mac recovery archive has a different size; selection unchanged')
    temporary = directory + '/transfer-recovery.json'
    upload(sftp, metadata, temporary)
    run(client, shlex.join(['/usr/bin/python3', '-u', directory + '/flash-macos.py',
        '--image', destination, '--manifest', temporary,
        '--target', directory + '/target.json', '--source-only']))
    sftp.posix_rename(temporary, directory + '/transfer.json')
    print('Recovery archive verified and selected; no card written:', manifest['image'], flush=True)


def mac_action(config, action, disk):
    if action in ('inspect', 'flash', 'backup', 'compare') and not re.fullmatch(r'disk[1-9][0-9]*', disk):
        raise ValueError('Supply the inspected external whole disk as DISK=diskN')
    recovery = None
    if action == 'stage-recovery':
        from recovery_image import resolve
        recovery = resolve(ROOT, os.environ.get('NEO_CHECKPOINT_NAME', ''))
    with connect_mac(config) as client, client.open_sftp() as sftp:
        if action == 'status':
            run(client, 'sw_vers; diskutil list external physical; route -n get 192.168.10.1')
            return
        directory = posixpath.join(sftp.normalize('.'), '.local/share/GameShellNeo')
        run(client, 'umask 077; mkdir -p {0}; chmod 700 {0}'.format(shlex.quote(directory)), display=False)
        if action == 'backup':
            mac_backup(client, sftp, config, directory, disk)
            return
        upload(sftp, ROOT / 'tools/flash-macos.py', directory + '/flash-macos.py')
        if action == 'flash':
            upload(sftp, ROOT / 'tools/macos-mount-guard.c', directory + '/macos-mount-guard.c')
        if action == 'stage-recovery':
            option = os.environ.get('NEO_RECOVERY_UPLOAD', '0')
            if option not in ('0', '1'):
                raise ValueError('UPLOAD must be 0 or 1')
            stage_recovery(client, sftp, directory, recovery, option == '1')
        elif action == 'stage':
            manifest = json.loads((LOCAL / 'flash/transfer.json').read_text())
            name = manifest['compressed_file']
            if Path(name).name != name:
                raise ValueError('Unexpected transfer filename')
            print('Uploading private image to the Mac...', flush=True)
            upload(sftp, LOCAL / 'flash' / name, directory + '/' + name)
            upload(sftp, LOCAL / 'flash/transfer.json', directory + '/transfer.json')
            # Verify the transferred source even when no card is inserted.
            args = staged_arguments(sftp, directory) + ['--source-only']
            run(client, shlex.join(args))
        elif action == 'inspect':
            run(client, shlex.join(['/usr/bin/python3', directory + '/flash-macos.py',
                                    '--inspect', disk, '--target', directory + '/target.json']))
            (LOCAL / 'flash').mkdir(mode=0o700, parents=True, exist_ok=True)
            sftp.get(directory + '/target.json', str(LOCAL / 'flash/target.json'))
        elif action == 'preflight':
            run(client, shlex.join(staged_arguments(sftp, directory)))
        elif action == 'compare':
            with sftp.open(directory + '/target.json') as stream:
                target = json.load(stream)
            if target['device'] != disk:
                raise ValueError('DISK differs from the fresh inspection')
            capture = evidence_directory()
            print('Private card comparison:', capture, flush=True)
            report = directory + '/card-compare-' + capture.name + '.json'
            arguments = staged_arguments(sftp, directory) + ['--compare-card', '--report', report]
            command, password = sudo(config, arguments)
            try:
                with (capture / 'card-compare.log').open('wb') as output:
                    run(client, command, password, output)
            finally:
                try:
                    sftp.stat(report)
                except FileNotFoundError:
                    pass
                else:
                    command, password = sudo(config, ['/bin/cat', report])
                    (capture / 'card-compare.json').write_bytes(run(client, command, password, display=False))
        else:
            with sftp.open(directory + '/target.json') as stream:
                target = json.load(stream)
            if target['device'] != disk:
                raise ValueError('DISK differs from the recorded inspection; inspect the intended spare again')
            capture = evidence_directory()
            report = directory + '/flash-' + capture.name + '.json'
            arguments = staged_arguments(sftp, directory) + ['--write', '--report', report]
            command, password = sudo(config, arguments)
            with (capture / 'flash.log').open('wb') as output:
                run(client, command, password, output)
            command, password = sudo(config, ['/bin/cat', report])
            (capture / 'flash-result.json').write_bytes(run(client, command, password, display=False))
            print('Private flash evidence:', capture)


def mac_backup(client, sftp, config, directory, disk):
    capture = evidence_directory()
    backups = LOCAL / 'backups'
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = 'original-card-' + capture.name + '.img.gz'
    remote_dir = directory + '/backups'
    run(client, 'umask 077; mkdir -p {0}; chmod 700 {0}'.format(shlex.quote(remote_dir)), display=False)
    upload(sftp, ROOT / 'tools/backup-macos.py', directory + '/backup-macos.py')
    remote_archive = remote_dir + '/' + name
    report_path = remote_archive + '.json'
    command, password = sudo(config, ['/usr/bin/python3', '-u', directory + '/backup-macos.py',
                                      '--disk', disk, '--output', remote_archive, '--report', report_path])
    with (capture / 'backup.log').open('wb') as output:
        run(client, command, password, output)
    command, password = sudo(config, ['/bin/cat', report_path])
    report_bytes = run(client, command, password, display=False)
    (capture / 'backup-result.json').write_bytes(report_bytes)
    report = json.loads(report_bytes)
    if report['archive'] != remote_archive or report['archive_verification'] != 'passed':
        raise ValueError('Unexpected backup verification result')
    if shutil.disk_usage(backups).free < report['compressed_bytes'] + 1024**3:
        raise RuntimeError('Verified backup is on the Mac; insufficient space for the Linux copy')
    print('Downloading the verified backup to the Linux host...', flush=True)
    partial = backups / (name + '.part')
    with partial.open('xb') as output:
        sftp.getfo(remote_archive, output)
        output.flush()
        os.fsync(output.fileno())
    with partial.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if digest != report['compressed_sha256'] or partial.stat().st_size != report['compressed_bytes']:
        raise RuntimeError('Downloaded backup checksum/size mismatch; Mac copy is preserved')
    partial.rename(backups / name)
    (backups / (name + '.json')).write_bytes(report_bytes)
    print('Verified recovery backup:', backups / name)
    print('Private backup evidence:', capture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='host', required=True)
    target = sub.add_parser('device')
    target.add_argument('action', choices=['status', 'logs', 'exec', 'check', 'backlight',
                                          'stability', 'battery-check', 'idle-sample', 'power-profile',
                                          'governor-compare', 'governor-profile', 'usb-policy',
                                          'wifi-scan-test', 'wifi-scan-restore'])
    target.add_argument('--route', choices=['wifi', 'usb'], default=os.environ.get('NEO_ROUTE', 'wifi'))
    mac = sub.add_parser('mac')
    mac.add_argument('action', choices=['status', 'backup', 'stage', 'stage-recovery', 'inspect', 'preflight', 'flash', 'compare'])
    mac.add_argument('--disk', default=os.environ.get('NEO_DISK', ''))
    args = parser.parse_args()
    os.umask(0o077)
    config = load_env()
    if args.host == 'device':
        if args.route not in ('wifi', 'usb'):
            parser.error('ROUTE must be wifi or usb')
        device_action(config, args.action, args.route)
    else:
        mac_action(config, args.action, args.disk)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, paramiko.SSHException) as error:
        print('Operation failed: {}'.format(error), file=sys.stderr)
        sys.exit(1)
