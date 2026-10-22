"""Use the stage manager's durable result instead of inspecting removed containers."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from kernel_sources import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def owns_active(identity):
    path = ROOT / '.local/build/container-active.json'
    try:
        active = json.loads(path.read_text())
    except FileNotFoundError:
        return False
    return active.get('run') == identity['run']


def result_for(receipt):
    identity = json.loads(receipt.read_text())
    expected_workspace = hashlib.sha256(str(ROOT).encode()).hexdigest()[:20]
    run = identity.get('run', '')
    if (identity.get('schema') != 1 or identity.get('workspace') != expected_workspace or
            len(run) != 32 or any(c not in '0123456789abcdef' for c in run)):
        raise ValueError('Managed run receipt identity differs')
    directory = ROOT / '.local/build/container-stages' / run
    path = directory / 'result.json'
    if not path.exists():
        return identity, None, directory
    result = json.loads(path.read_text())
    job = result.get('job', {})
    if any(job.get(key) != identity[key] for key in ('workspace', 'stage', 'run')):
        raise ValueError('Managed result identity differs')
    log = directory / 'container.log'
    if hashlib.sha256(log.read_bytes()).hexdigest() != result.get('log_sha256'):
        raise ValueError('Managed container log changed')
    return identity, result, directory


def execute(stage, arguments, destination, *, timeout):
    if not destination.is_absolute() or not destination.resolve().is_relative_to((ROOT / '.local').resolve()):
        raise ValueError('Managed evidence must be inside this checkout\'s private .local directory')
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError('Managed evidence requires a fresh attempt directory')
    receipt = destination / 'managed-run.json'
    command = [sys.executable, str(ROOT / 'tools/docker-stage.py'), 'run',
               '--receipt', str(receipt), stage, '--', '--rm', *arguments]
    atomic_json(destination / 'command.json', command)
    try:
        with (destination / 'runner.log').open('wb') as output:
            process = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
        _, result, _ = result_for(receipt)
        state = (result or {}).get('state') or {}
        if (process.returncode or not result or result.get('outcome') != 'exited' or
                result.get('exit_code') != 0 or result.get('returncode') != 0 or result.get('stop_requested') or
                state.get('Running') is not False or state.get('Status') != 'exited' or
                state.get('ExitCode') != 0 or
                state.get('OOMKilled') or state.get('Error')):
            raise RuntimeError('Managed container did not complete successfully; inspect ' + str(destination))
        return result
    finally:
        # An interrupted observer leaves ownership intact. Stop only the exact
        # run allocated to this attempt; a successor must never be stopped.
        if receipt.exists():
            identity, result, directory = result_for(receipt)
            if result is None or owns_active(identity):
                try:
                    status = subprocess.run([sys.executable, str(ROOT / 'tools/docker-stage.py'), 'status'],
                                            capture_output=True, text=True, timeout=40)
                    atomic_json(destination / 'interrupted-state.json', dict(
                        returncode=status.returncode, stdout=status.stdout, stderr=status.stderr))
                except (OSError, subprocess.TimeoutExpired) as error:
                    atomic_json(destination / 'interrupted-state.json', dict(error=str(error)))
                stop = [sys.executable, str(ROOT / 'tools/docker-stage.py'), 'stop', '--run', identity['run']]
                try:
                    stopped = subprocess.run(stop, capture_output=True, text=True, timeout=60)
                    atomic_json(destination / 'stop-observation.json', dict(
                        returncode=stopped.returncode, stdout=stopped.stdout, stderr=stopped.stderr))
                except (OSError, subprocess.TimeoutExpired) as error:
                    atomic_json(destination / 'stop-observation.json', dict(error=str(error)))
                identity, result, directory = result_for(receipt)
            if result is not None and not owns_active(identity):
                atomic_json(destination / 'managed-result.json', result)
                shutil.copyfile(directory / 'container.log', destination / 'container.log')
                if hashlib.sha256((destination / 'container.log').read_bytes()).hexdigest() != result['log_sha256']:
                    raise RuntimeError('Managed log changed during evidence retention')
            else:
                atomic_json(destination / 'cleanup-pending.json', identity)
                raise RuntimeError('Managed run remains unresolved; retain ownership and inspect ' + str(receipt))
