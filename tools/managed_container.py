"""Use the stage manager's durable result instead of inspecting removed containers."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from kernel_sources import atomic_json

ROOT = Path(__file__).resolve().parents[1]


class ManagedCommandFailure(RuntimeError):
    """A verified nonzero command outcome after original ownership is released."""
    def __init__(self, identity, result):
        super().__init__('Managed command exited ' + str(result['exit_code']) + ': ' + identity['run'])
        self.identity = identity
        self.result = result


def _completed_command(result, returncode):
    state = (result or {}).get('state') or {}
    return (result is not None and result.get('outcome') == 'exited' and
            type(returncode) is int and returncode >= 0 and
            result.get('exit_code') == returncode and result.get('returncode') == returncode and
            not result.get('stop_requested') and state.get('Running') is False and
            state.get('Status') == 'exited' and state.get('ExitCode') == returncode and
            not state.get('OOMKilled') and not state.get('Error'))


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
        if not _completed_command(result, process.returncode):
            raise RuntimeError('Managed container did not complete successfully; inspect ' + str(destination))
        command_result = result
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
    # The nonzero outcome is distinguishable only after the finally block has
    # retained the original result/log and proven cleanup. Never turn a cleanup,
    # timeout, stopped or changed-result failure into an expected command exit.
    identity, final_result, _ = result_for(receipt)
    if (owns_active(identity) or final_result != command_result or
            not _completed_command(final_result, process.returncode)):
        raise RuntimeError('Managed command ownership or original result is unresolved; inspect ' + str(receipt))
    if final_result['exit_code']:
        raise ManagedCommandFailure(identity, final_result)
    return final_result
