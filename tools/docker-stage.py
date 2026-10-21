#!/usr/bin/env python3
"""Retain Docker build identity and results independently of its foreground CLI."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / '.local/build'
ACTIVE = BUILD / 'container-active.json'
WORKSPACE = hashlib.sha256(str(ROOT).encode()).hexdigest()[:20]
NAME = 'gameshellneo-build-' + WORKSPACE
PREFIX = 'org.gameshellneo.build.'


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
            temporary.replace(path)
            fd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def ownership(wait=False):
    BUILD.mkdir(parents=True, exist_ok=True)
    with (BUILD / 'container-ownership.lock').open('a') as stream:
        deadline = time.monotonic() + (35 if wait else 0)
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Another container ownership operation is active; retry status later') from error
                time.sleep(0.1)
        yield


def docker(*args, check=True, **kwargs):
    executable = os.environ.get('NEO_BUILD_DOCKER') or shutil.which('docker')
    if not executable or Path(executable).resolve() == (ROOT / 'tools/build-bin/docker').resolve():
        raise RuntimeError('A real Docker executable is required')
    try:
        result = subprocess.run([executable, *args], timeout=30, **kwargs)
    except subprocess.TimeoutExpired as error:
        control_failure(args[0], error.stdout, error.stderr, None, 'timeout')
        raise RuntimeError('Docker ' + args[0] + ' observation timed out; retain ownership and inspect status') from None
    if check and result.returncode:
        path = control_failure(args[0], result.stdout, result.stderr, result.returncode, 'failed')
        raise RuntimeError('Docker operation failed: ' + args[0] + '; private details: ' + str(path))
    return result


def control_failure(operation, stdout, stderr, returncode, kind):
    def text(value):
        return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value
    job = active()
    if not job:
        return None
    path = directory(job) / ('docker-' + operation + '-' + uuid.uuid4().hex + '.json')
    save(path, dict(schema=1, operation=operation, kind=kind, returncode=returncode,
                    stdout=text(stdout), stderr=text(stderr), observed_utc=timestamp()))
    return path


def inspect(job):
    result = docker('inspect', '--type', 'container', job.get('id') or job['name'],
                    check=False, capture_output=True, text=True)
    if result.returncode:
        if 'No such object:' in result.stderr or 'No such container:' in result.stderr:
            return None
        raise RuntimeError('Docker state is unavailable; build admission remains blocked')
    value, = json.loads(result.stdout)
    labels = value['Config'].get('Labels') or {}
    expected = {'workspace': WORKSPACE, 'stage': job['stage'], 'run': job['run']}
    if any(labels.get(PREFIX + key) != item for key, item in expected.items()):
        raise RuntimeError('Container identity differs from the recorded build; refusing to act')
    if job.get('id') and value['Id'] != job['id']:
        raise RuntimeError('Container ID differs from the recorded build')
    return value


def validate(job):
    if (job.get('schema') != 1 or job.get('workspace') != WORKSPACE or job.get('name') != NAME or
            not re.fullmatch(r'[a-z][a-z0-9-]{0,62}', job.get('stage', '')) or
            not re.fullmatch(r'[0-9a-f]{32}', job.get('run', '')) or
            ('id' in job and not re.fullmatch(r'[0-9a-f]{64}', job['id']))):
        raise RuntimeError('Invalid build ownership record; admission remains blocked')
    return job


def active():
    return validate(json.loads(ACTIVE.read_text())) if ACTIVE.exists() else None


def directory(job):
    return BUILD / 'container-stages' / job['run']


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save_result(job, value):
    target = directory(job) / 'result.json'
    # Preserve an earlier cancellation/collection if a late create is found.
    if target.exists():
        target = target.with_name('reconciliation-' + uuid.uuid4().hex + '.json')
    save(target, value)


def recover_named():
    found = docker('inspect', '--type', 'container', NAME, check=False,
                   capture_output=True, text=True)
    if found.returncode:
        if 'No such object:' in found.stderr or 'No such container:' in found.stderr:
            return None
        raise RuntimeError('Cannot verify build-container absence')
    value, = json.loads(found.stdout)
    labels = value['Config'].get('Labels') or {}
    run = labels.get(PREFIX + 'run', '')
    if labels.get(PREFIX + 'workspace') != WORKSPACE or not re.fullmatch(r'[0-9a-f]{32}', run):
        raise RuntimeError('Build container name is occupied by an unverified owner')
    record = BUILD / 'container-stages' / run / 'job.json'
    job = validate(json.loads(record.read_text()))
    inspect(job)  # Verify all labels, and any already-recorded ID.
    job['id'] = value['Id']
    save(ACTIVE, job)
    save(record, job)
    return job


def release():
    ACTIVE.unlink()
    fd = os.open(BUILD, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def cancel_created(job, value):
    target = directory(job)
    target.mkdir(parents=True, exist_ok=True)
    receipt = target / 'cancellation.json'
    if receipt.exists():
        receipt = target / ('cancellation-' + uuid.uuid4().hex + '.json')
    # Preserve the observed state (including a failed start) before removal.
    # This is cancellation intent, not a fabricated terminal process result.
    save(receipt, dict(schema=1, job=job, state=value['State'],
                       requested_utc=timestamp()))
    # Non-force removal refuses a running container. A delayed start could
    # also finish between inspect and removal, so no complete-log or
    # never-started claim follows from the earlier created-state snapshot.
    docker('rm', job['id'], capture_output=True)
    log = target / 'container.log'
    if not log.exists():
        with log.open('wb') as stream:
            stream.flush()
            os.fsync(stream.fileno())
    save_result(job, dict(schema=1, job=job, state=value['State'],
         exit_code=None, returncode=125, outcome='cancelled-created-container',
         stop_requested=True, collected_utc=timestamp(),
         log_complete=False, cancellation_evidence=receipt.name,
         log_sha256=file_hash(log)))
    release()
    return 125


def cancel_absent(job):
    target = directory(job)
    previous = target / 'result.json'
    if previous.exists():
        saved = json.loads(previous.read_text())
        if saved['job']['run'] != job['run'] or file_hash(target / 'container.log') != saved['log_sha256']:
            raise RuntimeError('Existing terminal evidence does not match the absent container')
        release()
        return saved['returncode']
    target.mkdir(parents=True, exist_ok=True)
    log = target / 'container.log'
    if not log.exists():
        with log.open('wb') as stream:
            stream.flush()
            os.fsync(stream.fileno())
    # Holding ownership excludes a live creator. An orphaned create RPC can
    # finish only as a stopped container: its lost caller cannot issue start.
    # Its fixed name prevents another create, and recover_named can retire it.
    save_result(job, dict(schema=1, job=job, state=None, exit_code=None,
        returncode=125, outcome='container-absent-on-cancel', log_complete=False,
        stop_requested=True, collected_utc=timestamp(), log_sha256=file_hash(log)))
    release()
    return 125


def blocked(job):
    value = inspect(job)
    state = value['State']['Status'] if value else 'missing or creation incomplete'
    raise RuntimeError(f"Recorded {job['stage']} container is {state}; use task build:stage:status, "
                       'build:stage:resume or build:stage:stop before starting another writer')


def collect(job, stopped=False):
    with ownership(wait=True):
        current = active()
        if not current or current['run'] != job['run']:
            result = directory(job) / 'result.json'
            if result.exists():
                return json.loads(result.read_text())['returncode']
            raise RuntimeError('Build ownership changed before result collection')
        job = current
        value = inspect(job)
        if not value or value['State']['Status'] != 'exited' or value['State']['Running']:
            raise RuntimeError('Container is not proven exited; retaining build ownership')
        target = directory(job)
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                try:
                    docker('logs', job['id'], stdout=stream, stderr=subprocess.STDOUT)
                except (OSError, RuntimeError):
                    stream.flush()
                    os.fsync(stream.fileno())
                    temporary.replace(target / ('failed-log-collection-' + uuid.uuid4().hex + '.log'))
                    raise
                stream.flush()
                os.fsync(stream.fileno())
                previous = target / 'result.json'
                if previous.exists():
                    saved = json.loads(previous.read_text())
                    if (file_hash(target / 'container.log') != saved['log_sha256'] or
                            file_hash(temporary) != saved['log_sha256']):
                        temporary.replace(target / ('log-mismatch-' + uuid.uuid4().hex + '.log'))
                        raise RuntimeError('Repeated log collection differs from the original terminal evidence')
                temporary.replace(target / 'container.log')
            finally:
                temporary.unlink(missing_ok=True)
        result = dict(schema=1, job=job, exit_code=value['State']['ExitCode'],
                      returncode=value['State']['ExitCode'], outcome='exited',
                      state=value['State'], collected_utc=timestamp(),
                      stop_requested=stopped or job.get('stop_requested', False),
                      log_sha256=file_hash(target / 'container.log'))
        save_result(job, result)
        # Remove only this verified container, after durable logs and result.
        docker('rm', job['id'], capture_output=True)
        release()
        return result['exit_code']


def watch(job):
    # The daemon owns the retained log. Losing this observer leaves ACTIVE
    # intact, and resume reattaches to the same container without a new writer.
    executable = os.environ.get('NEO_BUILD_DOCKER') or shutil.which('docker')
    subprocess.run([executable, 'logs', '--follow', job['id']])
    # Another observer may have collected and removed this run just before
    # attachment. Only verified collection or its durable result decides the
    # exit status; an observer error alone never releases a live owner.
    return collect(job)


def start(job):
    value = inspect(job)
    if not value or value['State']['Status'] != 'created':
        raise RuntimeError('Container is not proven created; retaining build ownership')
    logging = value['HostConfig']['LogConfig']
    options = logging.get('Config') or {}
    if (logging['Type'] != 'json-file' or options.get('max-size') not in (None, '', '-1') or
            options.get('mode') not in (None, '', 'blocking')):
        raise RuntimeError('Lossy Docker logging cannot preserve an interrupted full build log; '
                           'stop the created stage and inspect the daemon logging policy')
    docker('start', job['id'], capture_output=True)


def run(stage, arguments):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,62}', stage):
        raise ValueError('Invalid build stage name')
    if arguments and arguments[0] == '--':
        arguments = arguments[1:]
    if arguments and arguments[0] in ('--rm', '--rm=true'):
        arguments = arguments[1:]
    # Managed repository builds are foreground, noninteractive commands.
    # Reserved identity/lifetime flags must never override this ownership.
    reserved = ('--rm', '--name', '--label', '--cidfile', '--restart', '--log-driver', '--log-opt',
                '--detach', '--interactive', '--tty')
    if not arguments or any(arg in ('-d', '-i', '-t', '-it') or
                            any(arg == flag or arg.startswith(flag + '=') for flag in reserved)
                            for arg in arguments):
        raise ValueError('Unsupported managed Docker run flags')
    with ownership():
        if job := active():
            blocked(job)
        # A deterministic workspace name is a second daemon-side exclusion.
        # Never delete an existing container merely because the ledger is absent.
        if job := recover_named():
            blocked(job)
        job = dict(schema=1, workspace=WORKSPACE, name=NAME, stage=stage,
                   run=uuid.uuid4().hex, created_utc=timestamp())
        save(directory(job) / 'job.json', job)
        save(ACTIVE, job)  # Publish reservation before sending a create request.
        labels = [item for key in ('workspace', 'stage', 'run')
                  for item in ('--label', PREFIX + key + '=' + job[key])]
        created = docker('create', '--name', NAME, *labels, '--log-driver', 'json-file',
                         *arguments, capture_output=True, text=True)
        job['id'] = created.stdout.strip()
        save(ACTIVE, job)
        save(directory(job) / 'job.json', job)
        start(job)
    return watch(job)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    start = sub.add_parser('run')
    start.add_argument('stage')
    start.add_argument('arguments', nargs=argparse.REMAINDER)
    for name in ('admit', 'status', 'resume', 'stop'):
        sub.add_parser(name)
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == 'run':
        return run(args.stage, args.arguments)
    with ownership():
        job = active()
        if args.action == 'admit':
            if job:
                blocked(job)
            return 0
        if args.action == 'status':
            value = inspect(job) if job else None
            print(json.dumps(dict(active=job, container_state=value['State'] if value else None,
                                  container_name=NAME), indent=2))
            return 0
        if not job:
            job = recover_named()
        if not job:
            raise RuntimeError('No recorded container to resume or stop')
        value = inspect(job)
        if not value:
            if args.action == 'stop':
                return cancel_absent(job)
            raise RuntimeError('Recorded container is missing or creation was interrupted; retain evidence for reconciliation')
        if not job.get('id'):
            # A create may finish after its host observer disappears. Adopt
            # only the container whose name and all recorded labels match.
            job['id'] = value['Id']
            save(ACTIVE, job)
            save(directory(job) / 'job.json', job)
        if args.action == 'stop':
            job['stop_requested'] = True
            save(ACTIVE, job)
            if value['State']['Status'] == 'created':
                return cancel_created(job, value)
            if value['State']['Running']:
                docker('stop', '--time', '10', job['id'], capture_output=True)
        elif value['State']['Status'] == 'created':
            previous = directory(job) / 'result.json'
            if previous.exists() and json.loads(previous.read_text()).get('stop_requested'):
                raise RuntimeError('This late-created job was cancelled; use stop to retire it before a new build')
            start(job)
    return collect(job, stopped=True) if args.action == 'stop' else watch(job)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('Build container: ' + str(error), file=sys.stderr)
        sys.exit(1)
