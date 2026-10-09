#!/usr/bin/env python3
"""Install and run bounded camera observations in the Mac's desktop session."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import posixpath
import re
import shlex
import sys

import paramiko
from private_config import load_env
from remote import connect_mac, evidence_directory, run, upload

SOURCE = Path(__file__).with_name('macos-camera.swift')
BUNDLE_ID = 'org.gameshellneo.cameraobserver'
CAMERA = 'FaceTime HD Camera'


def options(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('setup', 'status', 'capture'))
    parser.add_argument('--seconds', type=int, default=0,
                        help='0 saves one still; 1..300 records a bounded frame sequence')
    parser.add_argument('--fps', type=int, default=2, help='Export 1..5 frames per second')
    args = parser.parse_args(argv)
    if not 0 <= args.seconds <= 300 or not 1 <= args.fps <= 5:
        parser.error('Use seconds 0..300 and fps 1..5')
    if args.action != 'capture' and args.seconds:
        parser.error('Duration is only valid for capture')
    return args


def bundle_info():
    return dict(CFBundleIdentifier=BUNDLE_ID, CFBundleName='GameShellNeo Camera',
                CFBundleDisplayName='GameShellNeo Camera', CFBundleExecutable='CameraObserver',
                CFBundlePackageType='APPL', CFBundleVersion='1',
                CFBundleShortVersionString='1.0', NSPrincipalClass='NSApplication',
                LSUIElement=True,
                NSCameraUsageDescription='Observe the GameShell display during explicitly requested hardware tests.')


def digest():
    value = SOURCE.read_bytes() + plistlib.dumps(bundle_info(), sort_keys=True)
    return hashlib.sha256(value).hexdigest()


def mkdirs(sftp, path):
    try:
        sftp.stat(path)
    except FileNotFoundError:
        mkdirs(sftp, posixpath.dirname(path))
        sftp.mkdir(path, mode=0o700)


def install(client, sftp, base):
    app = base + '/GameShellNeo Camera.app'
    marker = base + '/source.sha256'
    expected = digest()
    try:
        with sftp.open(marker) as stream:
            current = stream.read().decode().strip()
        sftp.stat(app + '/Contents/MacOS/CameraObserver')
        if current == expected:
            print('Existing camera app matches the source; preserving its identity.')
            return app
    except FileNotFoundError:
        pass
    mkdirs(sftp, app + '/Contents/MacOS')
    upload(sftp, SOURCE, base + '/macos-camera.swift')
    with sftp.open(app + '/Contents/Info.plist', 'wb') as stream:
        stream.write(plistlib.dumps(bundle_info()))
    sftp.chmod(app + '/Contents/Info.plist', 0o600)
    run(client, shlex.join(['/usr/bin/xcrun', 'swiftc', '-O', base + '/macos-camera.swift',
                           '-o', app + '/Contents/MacOS/CameraObserver']), timeout=90)
    run(client, shlex.join(['/usr/bin/codesign', '--force', '--sign', '-',
                           '--identifier', BUNDLE_ID, app]), timeout=20)
    with sftp.open(marker, 'w') as stream:
        stream.write(expected + '\n')
    sftp.chmod(marker, 0o600)
    return app


def launch_source(app, destination, action, seconds, fps, base):
    # Hold the lock while open waits for this bounded app instance to exit.
    arguments = ['/usr/bin/open', '-n', '-W', app, '--args', action, destination,
                 str(seconds), str(fps), CAMERA, 'video-only']
    return '''import fcntl, pathlib, subprocess, sys, time
with open({lock!r}, 'a') as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit('Another camera operation is active')
    child = subprocess.Popen({arguments!r}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + {timeout!r}
    announced = False
    while child.poll() is None:
        if not announced and pathlib.Path({ready!r}).is_file():
            print('Camera ready: first image saved; observation is active.', flush=True)
            announced = True
        if time.monotonic() >= deadline:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            sys.exit('Camera app exceeded its watchdog; inspect partial private evidence')
        time.sleep(0.1)
    sys.stdout.buffer.write(child.stdout.read()[-4000:])
    sys.exit(child.returncode)
'''.format(lock=base + '/capture.lock', arguments=arguments,
           ready=destination + '/ready.json',
           timeout=135 if action == 'authorize' else seconds + 35)


def validate_result(result, action):
    if result.get('schema') != 1 or result.get('action') != action:
        raise ValueError('Camera result has an unexpected schema or action')
    if not isinstance(result.get('frames'), list):
        raise ValueError('Camera result is missing its frame list')
    names = []
    for frame in result['frames']:
        name = frame.get('file', '')
        if not re.fullmatch(r'frame-[0-9]{6}\.jpg', name) or name in names:
            raise ValueError('Invalid or duplicate camera frame filename')
        if not all(isinstance(frame.get(key), (int, float)) and frame[key] > 0
                   for key in ('width', 'height')):
            raise ValueError('Invalid camera frame dimensions')
        names.append(name)
    if len(names) > 1501:
        raise ValueError('Camera result exceeded the bounded frame count')
    if result.get('success'):
        if result.get('camera_stopped') is not True:
            raise ValueError('Camera session did not stop')
        if action in ('authorize', 'capture') and result.get('authorization') != 'authorized':
            raise ValueError('Camera permission was not granted')
        if action == 'capture' and not names:
            raise ValueError('Capture succeeded without images')
    return names


def main(argv=None):
    args = options(argv)
    os.umask(0o077)
    capture = evidence_directory()
    print('Private camera evidence:', capture, flush=True)
    action = 'authorize' if args.action == 'setup' else args.action
    with connect_mac(load_env()) as client, client.open_sftp() as sftp:
        base = posixpath.join(sftp.normalize('.'), '.local/share/GameShellNeo/camera')
        mkdirs(sftp, base)
        app = base + '/GameShellNeo Camera.app'
        if args.action == 'setup':
            app = install(client, sftp, base)
        else:
            try:
                with sftp.open(base + '/source.sha256') as stream:
                    installed = stream.read().decode().strip()
            except FileNotFoundError as error:
                raise RuntimeError('Run task mac:camera-setup first') from error
            if installed != digest():
                raise RuntimeError('Camera app source changed; run task mac:camera-setup')
        destination = base + '/captures/' + capture.name
        mkdirs(sftp, destination)
        source = launch_source(app, destination, action, args.seconds, args.fps, base)
        with (capture / 'launch.log').open('wb') as output:
            run(client, '/usr/bin/python3 -B -', input_data=source.encode(),
                timeout=145 if action == 'authorize' else args.seconds + 45,
                output=output, display=True)
        try:
            with sftp.open(destination + '/result.json') as stream:
                data = stream.read()
        except FileNotFoundError as error:
            raise RuntimeError('No camera result; the app may have timed out or failed to launch') from error
        (capture / 'result.json').write_bytes(data)
        result = json.loads(data)
        names = validate_result(result, action)
        if names:
            sftp.get(destination + '/ready.json', str(capture / 'ready.json'))
        for name in names:
            sftp.get(destination + '/' + name, str(capture / name))
            if (capture / name).read_bytes()[:2] != b'\xff\xd8':
                raise ValueError('Downloaded camera frame is not a JPEG')
        # Preserve failed/partial Mac captures for diagnosis; remove only fully
        # downloaded results after validating the successful session stopped.
        if result.get('success'):
            for name in names + ['result.json'] + (['ready.json'] if names else []):
                sftp.remove(destination + '/' + name)
            sftp.rmdir(destination)
    print(json.dumps(dict(success=result.get('success'), authorization=result.get('authorization'),
                         frame_count=len(names), camera_stopped=result.get('camera_stopped'),
                         error=result.get('error')), indent=2))
    if not result.get('success'):
        raise RuntimeError(result.get('error', 'Camera observation failed'))
    print('Camera operation finished; no GameShell settings or power state changed.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, paramiko.SSHException) as error:
        print('Mac camera operation failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
