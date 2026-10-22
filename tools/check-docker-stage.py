#!/usr/bin/env python3
"""Bounded offline reproduction of build-lock loss after host interruption."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '57a6c225e0001dd0e2cb0e7d11713cc5f333f438'
LABEL = 'org.gameshellneo.neo194.fixture'
DOCKER = os.environ.get('NEO_BUILD_DOCKER') or shutil.which('docker')


def docker(*args, timeout=30, check=True):
    return subprocess.run([DOCKER, *args], capture_output=True, text=True,
                          timeout=timeout, check=check)


def owned(name, token):
    result = docker('inspect', '--type', 'container', name, check=False)
    if result.returncode:
        if 'No such' in result.stderr:
            return None
        raise RuntimeError('Cannot determine fixture container state: ' + result.stderr)
    value, = json.loads(result.stdout)
    if value['Config']['Labels'].get(LABEL) != token:
        raise RuntimeError('Refusing to act on a container without the fixture identity')
    return value


def baseline():
    os.umask(0o077)
    token = uuid.uuid4().hex
    attempt = ROOT / '.local/build/docker-ownership/attempts' / token
    fixture = attempt / 'workspace'
    (fixture / 'tools').mkdir(parents=True)
    original = subprocess.run(['git', 'show', BASELINE + ':tools/run-logged.sh'],
                              cwd=ROOT, capture_output=True, check=True).stdout
    wrapper = fixture / 'tools/run-logged.sh'
    wrapper.write_bytes(original)
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    image = lock['builder']['image']
    name = 'gameshellneo-neo194-fixture-' + token
    evidence = dict(schema=1, attempt=token, baseline_commit=BASELINE,
                    wrapper_sha256=hashlib.sha256(original).hexdigest(), image=image)
    print('Docker ownership evidence:', attempt, flush=True)
    parent = None
    waiter = None
    try:
        with (attempt / 'host.log').open('wb') as output:
            parent = subprocess.Popen(['bash', str(wrapper), 'fixture', DOCKER, 'run',
                '--rm', '--network=none', '--pull=never', '--name', name,
                '--label', LABEL + '=' + token, '--entrypoint', '/bin/sh', image,
                '-c', 'echo fixture-start; sleep 20; echo fixture-finished'],
                cwd=fixture, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 15
            state = None
            while time.monotonic() < deadline:
                state = owned(name, token)
                if state and state['State']['Running']:
                    break
                if parent.poll() is not None:
                    raise RuntimeError('Fixture host exited before the container started')
                time.sleep(0.1)
            if not state or not state['State']['Running']:
                raise RuntimeError('Fixture container did not start')
            evidence['container_id'] = state['Id']
            # Simulate the host command tree disappearing. Killing only the
            # shell could leave a CLI child holding its inherited flock.
            os.killpg(parent.pid, signal.SIGKILL)
            evidence['host_returncode'] = parent.wait(timeout=5)
            state = owned(name, token)
            assert state and state['Id'] == evidence['container_id'] and state['State']['Running']
            evidence['container_live_after_host_exit'] = True
            marker = fixture / 'second-writer'
            script = 'from pathlib import Path; Path(' + repr(str(marker)) + ').write_text("admitted\\n")'
            successor = subprocess.run(['bash', str(wrapper), 'second', sys.executable, '-c', script],
                                       cwd=fixture, capture_output=True, timeout=5)
            (attempt / 'successor.log').write_bytes(successor.stdout + successor.stderr)
            evidence['successor_returncode'] = successor.returncode
            evidence['second_writer_admitted'] = marker.is_file()
            waiter = subprocess.Popen([DOCKER, 'wait', evidence['container_id']],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            logs = docker('logs', '--follow', evidence['container_id'])
            (attempt / 'container.log').write_text(logs.stdout + logs.stderr)
            code, error = waiter.communicate(timeout=5)
            assert waiter.returncode == 0, error
            evidence['container_exit_code'] = int(code.strip())
            assert evidence['container_exit_code'] == 0 and 'fixture-finished' in logs.stdout
    finally:
        if parent is not None and parent.poll() is None:
            os.killpg(parent.pid, signal.SIGKILL)
            parent.wait(timeout=5)
        if waiter is not None and waiter.poll() is None:
            waiter.kill()
            waiter.communicate(timeout=5)
        (attempt / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
        state = owned(name, token)
        if state and state['State']['Running']:
            docker('rm', '--force', state['Id'])
        # --rm may still be completing after docker wait returns. Observe its
        # retirement rather than racing a second removal operation against it.
        deadline = time.monotonic() + 5
        while owned(name, token) is not None and time.monotonic() < deadline:
            time.sleep(0.1)
        if owned(name, token) is not None:
            raise RuntimeError('Fixture container cleanup did not finish')
    if not evidence.get('second_writer_admitted'):
        raise RuntimeError('Historical lock-loss baseline did not reproduce')
    raise RuntimeError('Baseline reproduced: a second writer was admitted while the original container was live')


def fixture_call(workspace, *arguments, timeout=45, env=None):
    return subprocess.run([sys.executable, str(workspace / 'tools/docker-stage.py'), *arguments],
                          cwd=workspace, capture_output=True, text=True, timeout=timeout, env=env)


def workspace_for(attempt, name):
    workspace = attempt / name / 'workspace with spaces'
    (workspace / 'tools/build-bin').mkdir(parents=True)
    for relative in ('run-logged.sh', 'docker-stage.py', 'build-bin/docker',
                     'managed_container.py', 'kernel_sources.py'):
        shutil.copy2(ROOT / 'tools' / relative, workspace / 'tools' / relative)
    return workspace


def candidate_case(attempt, name, exit_code):
    workspace = workspace_for(attempt, name)
    wrapper = workspace / 'tools/run-logged.sh'
    image = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']['image']
    command = ['bash', str(wrapper), 'fixture', 'docker', 'run', '--rm',
               '--network=none', '--pull=never', '--entrypoint', '/bin/sh', image,
               '-c', 'echo fixture-start; sleep 15; echo fixture-finished; exit ' + str(exit_code)]
    record = workspace / '.local/build/container-active.json'
    parent = None
    job = None
    summary = dict(case=name, expected_exit_code=exit_code)
    try:
        with (workspace.parent / 'host.log').open('wb') as output:
            parent = subprocess.Popen(command, cwd=workspace, stdout=output,
                                      stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if record.exists():
                    job = json.loads(record.read_text())
                    if job.get('id'):
                        status = fixture_call(workspace, 'status')
                        if status.returncode == 0 and json.loads(status.stdout)['container_state']['Running']:
                            break
                if parent.poll() is not None:
                    raise RuntimeError('Managed fixture exited before it became observable')
                time.sleep(0.1)
            else:
                raise RuntimeError('Managed fixture never became ready')
            os.killpg(parent.pid, signal.SIGKILL)
            summary['host_returncode'] = parent.wait(timeout=5)
        status = fixture_call(workspace, 'status')
        assert status.returncode == 0 and json.loads(status.stdout)['container_state']['Running']
        if exit_code:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                status = fixture_call(workspace, 'status')
                assert status.returncode == 0
                if json.loads(status.stdout)['container_state']['Status'] == 'exited':
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError('Fixture did not reach its expected terminal state')
            summary['unobserved_terminal_state_retained'] = True
        initial_log = workspace / '.local/build/fixture.log'
        original = initial_log.read_bytes()
        marker = workspace / 'second-writer'
        script = 'from pathlib import Path; Path(' + repr(str(marker)) + ').touch()'
        second = subprocess.run(['bash', str(wrapper), 'fixture', sys.executable, '-c', script],
                                cwd=workspace, capture_output=True, text=True, timeout=5)
        (workspace.parent / 'blocked-writer.log').write_text(second.stdout + second.stderr)
        assert second.returncode != 0 and not marker.exists()
        assert initial_log.read_bytes() == original
        summary['second_writer_rejected_before_log_rotation'] = True
        resume = fixture_call(workspace, 'resume')
        (workspace.parent / 'resume.log').write_text(resume.stdout + resume.stderr)
        assert resume.returncode == exit_code, resume.stdout + resume.stderr
        assert not record.exists()
        result_path = workspace / '.local/build/container-stages' / job['run'] / 'result.json'
        result = json.loads(result_path.read_text())
        log = result_path.with_name('container.log').read_bytes()
        assert result['job']['id'] == job['id'] and result['exit_code'] == exit_code
        assert b'fixture-start' in log and b'fixture-finished' in log
        assert hashlib.sha256(log).hexdigest() == result['log_sha256']
        assert 'fixture-start' in resume.stdout and 'fixture-finished' in resume.stdout
        retired = docker('inspect', '--type', 'container', job['id'], check=False)
        assert retired.returncode != 0 and 'No such' in retired.stderr
        summary['same_container_resumed_and_collected'] = True
        summary['actual_exit_code'] = result['exit_code']
        second = subprocess.run(['bash', str(wrapper), 'after', sys.executable, '-c', script],
                                cwd=workspace, capture_output=True, text=True, timeout=5)
        assert second.returncode == 0 and marker.exists()
        summary['writer_admitted_after_verified_retirement'] = True
        return summary
    finally:
        if parent is not None and parent.poll() is None:
            os.killpg(parent.pid, signal.SIGKILL)
            parent.wait(timeout=5)
        if record.exists() and job and job.get('id'):
            # The helper verifies workspace/stage/run labels and exact ID.
            stopped = fixture_call(workspace, 'stop')
            (workspace.parent / 'cleanup.log').write_text(stopped.stdout + stopped.stderr)
            if record.exists():
                raise RuntimeError('Managed fixture cleanup remains pending; inspect its saved ownership record')


def command_case(attempt):
    workspace = workspace_for(attempt, 'command-contract')
    image = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']['image']
    result = fixture_call(workspace, 'run', 'command', '--', '--rm', '--network=none',
        '--pull=never', '--user', f'{os.getuid()}:{os.getgid()}', '-v', f'{workspace}:/fixture',
        '-w', '/fixture', '-e', 'NEO_FIXTURE_VALUE=literal value', '--entrypoint', '/bin/sh', image,
        '-c', 'test "$NEO_FIXTURE_VALUE" = "literal value"; echo payload > written; '
              'echo standard-output; echo standard-error >&2; exit 3')
    (workspace.parent / 'command.json').write_text(json.dumps(dict(
        returncode=result.returncode, stdout=result.stdout, stderr=result.stderr), indent=2) + '\n')
    assert result.returncode == 3 and result.stdout == 'standard-output\n' and result.stderr == 'standard-error\n'
    assert (workspace / 'written').read_text() == 'payload\n'
    assert not (workspace / '.local/build/container-active.json').exists()
    return dict(case='command-contract', stdout_stderr_exit_environment_volume_user_and_workdir_preserved=True)


def created_case(attempt):
    workspace = workspace_for(attempt, 'created-recovery')
    image = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']['image']
    record = workspace / '.local/build/container-active.json'
    foreign_name = 'gameshellneo-neo194-control-' + uuid.uuid4().hex
    token = uuid.uuid4().hex
    foreign = None
    job = None
    try:
        failed = fixture_call(workspace, 'run', 'created', '--', '--rm', '--network=none',
                              '--pull=never', '--entrypoint', '/missing-fixture-executable', image)
        assert failed.returncode != 0 and record.exists()
        job = json.loads(record.read_text())
        errors = list((record.parent / 'container-stages' / job['run']).glob('docker-start-*.json'))
        assert errors and '/missing-fixture-executable' in json.loads(errors[0].read_text())['stderr']
        status = fixture_call(workspace, 'status')
        assert status.returncode == 0 and json.loads(status.stdout)['container_state']['Status'] == 'created'
        unavailable = workspace / 'unavailable-docker'
        unavailable.write_text('#!/bin/sh\necho "Cannot connect to fixture daemon" >&2\nexit 1\n')
        unavailable.chmod(0o700)
        unknown = fixture_call(workspace, 'admit', env=dict(os.environ, NEO_BUILD_DOCKER=str(unavailable)))
        assert unknown.returncode != 0 and record.exists() and 'unavailable' in unknown.stderr
        foreign = docker('create', '--name', foreign_name, '--label', LABEL + '=' + token,
                         '--network=none', '--entrypoint', '/bin/sh', image, '-c', 'exit 0').stdout.strip()
        altered = dict(job, id=foreign)
        record.write_text(json.dumps(altered))
        rejected = fixture_call(workspace, 'stop')
        assert rejected.returncode != 0 and owned(foreign_name, token)['Id'] == foreign
        record.write_text(json.dumps(job))
        # Inject the point after daemon create but before the ID was persisted.
        pending = dict(job)
        del pending['id']
        record.write_text(json.dumps(pending))
        deferred = fixture_call(workspace, 'stop')
        (workspace.parent / 'deferred-stop.log').write_text(deferred.stdout + deferred.stderr)
        assert deferred.returncode != 0 and record.exists()
        path = workspace / '.local/build/container-stages' / job['run']
        saved = json.loads((path / 'cancellation.json').read_text())
        assert saved['start_state'] == 'pending' and '/missing-fixture-executable' in saved['state']['Error']
        assert not (path / 'result.json').exists()
        assert json.loads(record.read_text())['id'] == job['id']
        assert owned(foreign_name, token)['Id'] == foreign
        return dict(case='created-recovery', failed_start_retains_ownership=True,
                    unavailable_daemon_does_not_admit_writer=True,
                    foreign_identity_rejected=True, missing_id_reconciled_by_labels=True,
                    unresolved_failure_retains_created_state=True)
    finally:
        if job and record.exists():
            record.write_text(json.dumps(job))
            # This controlled fixture's entrypoint cannot execute, and its
            # only start call has returned. Retire just this known test object;
            # production recovery deliberately preserves unresolved starts.
            value, = json.loads(docker('inspect', '--type', 'container', job['id']).stdout)
            labels = value['Config']['Labels']
            assert value['Id'] == job['id'] and value['State']['Status'] == 'created'
            assert value['Config']['Entrypoint'] == ['/missing-fixture-executable']
            assert all(labels['org.gameshellneo.build.' + key] == job[key] for key in ('workspace', 'stage', 'run'))
            docker('rm', job['id'])
            fixture_call(workspace, 'stop')
        if foreign:
            state = owned(foreign_name, token)
            if state:
                assert state['Id'] == foreign and not state['State']['Running']
                docker('rm', foreign)


def reservation_case(attempt):
    workspace = workspace_for(attempt, 'creation-reservation')
    image = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']['image']
    record = workspace / '.local/build/container-active.json'
    job = None
    try:
        missing_image = 'gameshellneo-neo194-absent-' + uuid.uuid4().hex + ':fixture'
        failed = fixture_call(workspace, 'run', 'reservation', '--', '--rm', '--network=none',
                              '--pull=never', '--entrypoint', '/bin/sh', missing_image)
        assert failed.returncode != 0 and record.exists()
        job = json.loads(record.read_text())
        assert 'id' not in job
        cancelled = fixture_call(workspace, 'stop')
        assert cancelled.returncode == 125 and not record.exists()
        result_path = workspace / '.local/build/container-stages' / job['run'] / 'result.json'
        original = result_path.read_bytes()
        saved = json.loads(original)
        assert saved['exit_code'] is None and not saved['log_complete']
        assert saved['outcome'] == 'container-absent-on-cancel'
        # Controlled late-create seam: daemon-side creation can complete after
        # its observer disappears, but no caller remains to start this job.
        labels = [argument for key in ('workspace', 'stage', 'run') for argument in
                  ('--label', 'org.gameshellneo.build.' + key + '=' + job[key])]
        late = docker('create', '--name', job['name'], *labels, '--network=none',
                      '--entrypoint', '/bin/sh', image, '-c', 'echo must-not-run').stdout.strip()
        rejected = fixture_call(workspace, 'resume')
        assert rejected.returncode != 0 and 'cancelled' in rejected.stderr
        assert record.exists() and json.loads(record.read_text())['id'] == late
        status = fixture_call(workspace, 'status')
        assert status.returncode == 0 and json.loads(status.stdout)['container_state']['Status'] == 'created'
        stopped = fixture_call(workspace, 'stop')
        assert stopped.returncode == 125 and not record.exists()
        assert result_path.read_bytes() == original
        assert list(result_path.parent.glob('reconciliation-*.json'))
        return dict(case='creation-reservation', failed_create_keeps_reservation=True,
                    absent_cancellation_has_no_invented_exit_status=True,
                    late_create_recovered_without_starting_cancelled_job=True,
                    original_result_preserved=True)
    finally:
        if job and record.exists():
            fixture_call(workspace, 'stop')


def running_stop_case(attempt):
    workspace = workspace_for(attempt, 'running-stop')
    image = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']['image']
    record = workspace / '.local/build/container-active.json'
    wrapper = workspace / 'tools/run-logged.sh'
    parent = None
    try:
        with (workspace.parent / 'host.log').open('wb') as output:
            parent = subprocess.Popen(['bash', str(wrapper), 'stop-control', 'docker', 'run',
                '--rm', '--network=none', '--pull=never', '--entrypoint', '/bin/sh', image,
                '-c', "trap 'echo fixture-stopped; exit 23' TERM; echo fixture-start; while :; do sleep 0.1; done"],
                cwd=workspace, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 15
            log = workspace / '.local/build/stop-control.log'
            while time.monotonic() < deadline:
                if record.exists() and log.exists() and b'fixture-start' in log.read_bytes():
                    job = json.loads(record.read_text())
                    break
                if parent.poll() is not None:
                    raise RuntimeError('Stop-control fixture exited before readiness')
                time.sleep(0.1)
            else:
                raise RuntimeError('Stop-control fixture did not become ready')
            stopped = fixture_call(workspace, 'stop')
            (workspace.parent / 'stop.log').write_text(stopped.stdout + stopped.stderr)
            assert stopped.returncode == 23, stopped.stdout + stopped.stderr
            assert parent.wait(timeout=40) == 23
        assert not record.exists()
        path = workspace / '.local/build/container-stages' / job['run'] / 'result.json'
        saved = json.loads(path.read_text())
        assert saved['exit_code'] == 23 and saved['stop_requested']
        assert b'fixture-stopped' in path.with_name('container.log').read_bytes()
        return dict(case='running-stop', only_recorded_container_stopped=True,
                    concurrent_observers_keep_actual_exit_status=True, stop_intent_retained=True)
    finally:
        if record.exists():
            fixture_call(workspace, 'stop')
        if parent is not None and parent.poll() is None:
            os.killpg(parent.pid, signal.SIGKILL)
            parent.wait(timeout=5)


def removal_case(attempt):
    workspace = workspace_for(attempt, 'removal-retry')
    image = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']['image']
    marker = workspace / 'remove-rejected-once'
    proxy = workspace / 'docker-with-removal-failure'
    proxy.write_text('#!' + sys.executable + '\nimport os, sys\nfrom pathlib import Path\n'
                     'marker = Path(' + repr(str(marker)) + ')\n'
                     'if sys.argv[1] == "rm" and not marker.exists():\n'
                     '    marker.touch(); print("fixture removal failure", file=sys.stderr); sys.exit(1)\n'
                     'os.execv(' + repr(DOCKER) + ', [' + repr(DOCKER) + '] + sys.argv[1:])\n')
    proxy.chmod(0o700)
    record = workspace / '.local/build/container-active.json'
    try:
        failed = fixture_call(workspace, 'run', 'removal', '--', '--rm', '--network=none',
            '--pull=never', '--entrypoint', '/bin/sh', image, '-c', 'echo retained-terminal-output',
            env=dict(os.environ, NEO_BUILD_DOCKER=str(proxy)))
        assert failed.returncode != 0 and marker.exists() and record.exists()
        job = json.loads(record.read_text())
        target = record.parent / 'container-stages' / job['run']
        original = (target / 'result.json').read_bytes()
        log = (target / 'container.log').read_bytes()
        assert json.loads(original)['exit_code'] == 0
        assert b'retained-terminal-output' in log
        assert fixture_call(workspace, 'admit').returncode != 0
        resumed = fixture_call(workspace, 'resume')
        assert resumed.returncode == 0 and not record.exists()
        assert (target / 'result.json').read_bytes() == original
        assert (target / 'container.log').read_bytes() == log
        assert list(target.glob('docker-rm-*.json')) and list(target.glob('reconciliation-*.json'))
        return dict(case='removal-retry', terminal_saved_before_remove=True,
                    failed_removal_keeps_ownership=True, retry_preserves_original_logs_and_result=True)
    finally:
        if record.exists():
            fixture_call(workspace, 'stop')


def logging_case(attempt, policy):
    workspace = workspace_for(attempt, 'logging-' + policy)
    image = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']['image']
    record = workspace / '.local/build/container-active.json'
    proxy = workspace / 'docker-with-log-policy'
    flags = ['--log-opt', 'max-size=1k'] if policy == 'rotation' else ['--log-opt', 'mode=non-blocking']
    proxy.write_text('#!' + sys.executable + '\nimport os, sys\n'
                     'arguments = sys.argv[1:]\n'
                     'if arguments[0] == "create": arguments[1:1] = ' + repr(flags) + '\n'
                     'os.execv(' + repr(DOCKER) + ', [' + repr(DOCKER) + '] + arguments)\n')
    proxy.chmod(0o700)
    try:
        failed = fixture_call(workspace, 'run', 'logging', '--', '--rm', '--network=none',
            '--pull=never', '--entrypoint', '/bin/sh', image, '-c', 'echo must-not-start',
            env=dict(os.environ, NEO_BUILD_DOCKER=str(proxy)))
        (workspace.parent / 'run.log').write_text(failed.stdout + failed.stderr)
        assert failed.returncode != 0 and record.exists(), 'Unsafe logging policy started the original job'
        job = json.loads(record.read_text())
        resumed = fixture_call(workspace, 'resume')
        (workspace.parent / 'resume.log').write_text(resumed.stdout + resumed.stderr)
        assert resumed.returncode != 0 and record.exists(), 'Created resume bypassed logging admission'
        state = fixture_call(workspace, 'status')
        assert state.returncode == 0 and json.loads(state.stdout)['container_state']['Status'] == 'created'
        assert fixture_call(workspace, 'stop').returncode == 125 and not record.exists()
        result = record.parent / 'container-stages' / job['run'] / 'result.json'
        assert json.loads(result.read_text())['exit_code'] is None
        assert b'must-not-start' not in result.with_name('container.log').read_bytes()
        return dict(case='logging-' + policy, original_and_resume_refuse_lossy_logging=True,
                    created_container_never_started=True)
    finally:
        if record.exists():
            fixture_call(workspace, 'stop')


def cancellation_case(attempt):
    workspace = workspace_for(attempt, 'created-cancellation')
    image = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']['image']
    record = workspace / '.local/build/container-active.json'
    proxy = workspace / 'docker-with-lost-removal-reply'
    proxy.write_text('#!' + sys.executable + '\nimport os, subprocess, sys\n'
                     'if sys.argv[1] == "create": sys.argv[2:2] = ["--log-opt", "max-size=1k"]\n'
                     'if sys.argv[1] == "rm":\n'
                     '    subprocess.run([' + repr(DOCKER) + '] + sys.argv[1:], check=True)\n'
                     '    sys.exit(99)\n'
                     'os.execv(' + repr(DOCKER) + ', [' + repr(DOCKER) + '] + sys.argv[1:])\n')
    proxy.chmod(0o700)
    try:
        failed = fixture_call(workspace, 'run', 'cancellation', '--', '--rm', '--network=none',
            '--pull=never', '--entrypoint', '/bin/sh', image, '-c', 'echo must-not-start',
            env=dict(os.environ, NEO_BUILD_DOCKER=str(proxy)))
        assert failed.returncode != 0 and record.exists()
        job = json.loads(record.read_text())
        interrupted = fixture_call(workspace, 'stop', env=dict(os.environ, NEO_BUILD_DOCKER=str(proxy)))
        (workspace.parent / 'interrupted-stop.log').write_text(interrupted.stdout + interrupted.stderr)
        assert interrupted.returncode != 0 and record.exists()
        absent = docker('inspect', '--type', 'container', job['id'], check=False)
        assert absent.returncode != 0 and 'No such' in absent.stderr
        target = record.parent / 'container-stages' / job['run']
        receipt = target / 'cancellation.json'
        assert receipt.exists(), 'Removal lost the original created-state evidence'
        original = receipt.read_bytes()
        saved = json.loads(original)
        assert saved['job']['id'] == job['id'] and saved['state']['Status'] == 'created'
        assert saved['start_state'] == 'unrequested'
        assert fixture_call(workspace, 'stop').returncode == 125 and not record.exists()
        terminal = json.loads((target / 'result.json').read_text())
        assert terminal['exit_code'] is None and not terminal['log_complete']
        assert receipt.read_bytes() == original
        return dict(case='created-cancellation', state_preserved_before_removal=True,
                    lost_reply_retains_ownership=True, original_created_state_survives_recovery=True)
    finally:
        if record.exists():
            fixture_call(workspace, 'stop')


def attachment_case(attempt):
    for code in (0, 7):
        workspace = workspace_for(attempt, 'attachment-race-' + str(code))
        image = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']['image']
        record = workspace / '.local/build/container-active.json'
        ready = workspace / 'observer-ready'
        proceed = workspace / 'observer-proceed'
        proxy = workspace / 'docker-with-delayed-observer'
        proxy.write_text('#!' + sys.executable + '\nimport os, sys, time\nfrom pathlib import Path\n'
                         'if sys.argv[1:3] == ["logs", "--follow"]:\n'
                         '    Path(' + repr(str(ready)) + ').touch()\n'
                         '    deadline = time.monotonic() + 15\n'
                         '    while not Path(' + repr(str(proceed)) + ').exists():\n'
                         '        if time.monotonic() >= deadline: sys.exit(98)\n'
                         '        time.sleep(0.05)\n'
                         'os.execv(' + repr(DOCKER) + ', [' + repr(DOCKER) + '] + sys.argv[1:])\n')
        proxy.chmod(0o700)
        parent = None
        try:
            with (workspace.parent / 'original-observer.log').open('wb') as output:
                parent = subprocess.Popen([sys.executable, str(workspace / 'tools/docker-stage.py'),
                    'run', 'attachment', '--', '--rm', '--network=none', '--pull=never',
                    '--entrypoint', '/bin/sh', image, '-c', 'echo retained-output; exit ' + str(code)],
                    cwd=workspace, env=dict(os.environ, NEO_BUILD_DOCKER=str(proxy)),
                    stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                deadline = time.monotonic() + 12
                while not ready.exists():
                    if time.monotonic() >= deadline or parent.poll() is not None:
                        raise RuntimeError('Delayed observer did not become ready')
                    time.sleep(0.05)
                job = json.loads(record.read_text())
                resumed = fixture_call(workspace, 'resume')
                assert resumed.returncode == code and not record.exists()
                result = record.parent / 'container-stages' / job['run'] / 'result.json'
                original = result.read_bytes()
                proceed.touch()
                observed = parent.wait(timeout=15)
                assert observed == code, f'Late observer returned {observed} instead of saved exit {code}'
                assert result.read_bytes() == original
        finally:
            proceed.touch()
            if record.exists():
                fixture_call(workspace, 'stop')
            if parent is not None and parent.poll() is None:
                os.killpg(parent.pid, signal.SIGKILL)
                parent.wait(timeout=5)
    return dict(case='attachment-race', removed_container_observers_reconcile_saved_exit=True,
                success_and_failure_results_preserved=True)


def delayed_start_case(attempt):
    workspace = workspace_for(attempt, 'delayed-start')
    image = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']['image']
    record = workspace / '.local/build/container-active.json'
    proceed = workspace / 'late-start-proceed'
    finished = workspace / 'late-start-finished'
    proxy = workspace / 'docker-with-delayed-start'
    proxy.write_text('#!' + sys.executable + '\nimport os, subprocess, sys, time\nfrom pathlib import Path\n'
                     'if sys.argv[1] == "start": sys.exit(99)\n'
                     'if sys.argv[1] == "rm":\n'
                     '    Path(' + repr(str(proceed)) + ').touch()\n'
                     '    deadline = time.monotonic() + 12\n'
                     '    while not Path(' + repr(str(finished)) + ').exists():\n'
                     '        if time.monotonic() >= deadline: sys.exit(98)\n'
                     '        time.sleep(0.05)\n'
                     'os.execv(' + repr(DOCKER) + ', [' + repr(DOCKER) + '] + sys.argv[1:])\n')
    proxy.chmod(0o700)
    worker = None
    try:
        failed = fixture_call(workspace, 'run', 'delayed', '--', '--rm', '--network=none',
            '--pull=never', '--entrypoint', '/bin/sh', image, '-c', 'echo delayed-output; exit 7',
            env=dict(os.environ, NEO_BUILD_DOCKER=str(proxy)))
        assert failed.returncode != 0 and record.exists()
        job = json.loads(record.read_text())
        # Controlled seam for a start RPC whose caller disappeared. Stop's
        # removal seam lets that original request start and exit first.
        code = ('import subprocess,time\nfrom pathlib import Path\n'
                'deadline=time.monotonic()+20\n'
                'while not Path(' + repr(str(proceed)) + ').exists():\n'
                ' if time.monotonic()>=deadline: raise RuntimeError("Late start was not released")\n'
                ' time.sleep(0.05)\n'
                'subprocess.run([' + repr(DOCKER) + ',"start",' + repr(job['id']) + '],check=True)\n'
                'subprocess.run([' + repr(DOCKER) + ',"wait",' + repr(job['id']) + '],check=True)\n'
                'Path(' + repr(str(finished)) + ').touch()\n')
        with (workspace.parent / 'late-start.log').open('wb') as output:
            worker = subprocess.Popen([sys.executable, '-c', code], stdout=output,
                                      stderr=subprocess.STDOUT, start_new_session=True)
            stopped = fixture_call(workspace, 'stop', env=dict(os.environ, NEO_BUILD_DOCKER=str(proxy)))
            (workspace.parent / 'stop.log').write_text(stopped.stdout + stopped.stderr)
            assert stopped.returncode != 125 and record.exists(), 'Cancellation discarded the delayed terminal result'
            state = fixture_call(workspace, 'status')
            assert state.returncode == 0 and json.loads(state.stdout)['container_state']['Status'] == 'created'
            assert fixture_call(workspace, 'resume').returncode != 0
            receipt = record.parent / 'container-stages' / job['run'] / 'start.json'
            original = receipt.read_bytes()
            receipt.unlink()
            assert fixture_call(workspace, 'stop').returncode != 125 and record.exists()
            assert fixture_call(workspace, 'resume').returncode != 0 and record.exists()
            receipt.write_bytes(original)
            proceed.touch()
            assert worker.wait(timeout=15) == 0
        resumed = fixture_call(workspace, 'resume')
        assert resumed.returncode == 7 and not record.exists()
        target = record.parent / 'container-stages' / job['run']
        result = json.loads((target / 'result.json').read_text())
        assert result['exit_code'] == 7 and b'delayed-output' in (target / 'container.log').read_bytes()
        return dict(case='delayed-start', unresolved_start_blocks_cancellation_and_restart=True,
                    missing_legacy_metadata_retains_ownership=True,
                    eventual_original_output_and_exit_preserved=True)
    finally:
        proceed.touch()
        if worker is not None and worker.poll() is None:
            worker.wait(timeout=15)
        if record.exists():
            fixture_call(workspace, 'stop')


def managed_runner_case(attempt):
    workspace = workspace_for(attempt, 'managed-runners')
    image = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']['image']
    script = workspace / 'fixture.py'
    script.write_text('''import json, pathlib, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent / 'tools'))
from managed_container import execute
root = pathlib.Path(__file__).parent
mode, image = sys.argv[1:]
destination = root / '.local' / mode
arguments = ['--network=none', '--pull=never', '--entrypoint=/bin/sh', image,
             '-c', ("trap 'exit 42' TERM; echo original-output; while :; do sleep 1; done"
                    if mode == 'timeout' else 'echo original-output; exit ' + mode)]
try:
    result = execute('fixture', arguments, destination, timeout=8 if mode == 'timeout' else 20)
    assert mode == '0' and result['exit_code'] == 0
except subprocess.TimeoutExpired:
    assert mode == 'timeout'
except RuntimeError:
    assert mode == '7'
saved = json.loads((destination / 'managed-result.json').read_text())
assert saved['exit_code'] == (42 if mode == 'timeout' else int(mode))
assert saved['stop_requested'] == (mode == 'timeout')
assert 'original-output' in (destination / 'container.log').read_text()
assert not (root / '.local/build/container-active.json').exists()
''')
    command = ['bash', str(workspace / 'tools/run-logged.sh'), 'managed-fixture',
               sys.executable, str(script)]
    for mode in ('0', '7'):
        result = subprocess.run([*command, mode, image], cwd=workspace,
                                capture_output=True, text=True, timeout=45)
        (workspace.parent / ('host-' + mode + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError('Managed runner fixture failed: ' + result.stderr)
    worker = None
    record = workspace / '.local/build/container-active.json'
    job = None
    try:
        with (workspace.parent / 'host-timeout.log').open('w') as output:
            worker = subprocess.Popen([*command, 'timeout', image], cwd=workspace,
                                      stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 7
            while time.monotonic() < deadline:
                status = fixture_call(workspace, 'status')
                value = json.loads(status.stdout)
                if value['active'] and (value['container_state'] or {}).get('Running'):
                    job = value['active']
                    break
                if worker.poll() is not None:
                    raise RuntimeError('Managed timeout fixture exited before its container started')
                time.sleep(0.1)
            if job is None:
                raise RuntimeError('Managed timeout fixture did not start')
            rejected = fixture_call(workspace, 'stop', '--run', 'f' * 32)
            assert rejected.returncode != 0 and 'differs' in rejected.stderr
            assert json.loads(record.read_text())['run'] == job['run']
            assert json.loads(fixture_call(workspace, 'status').stdout)['container_state']['Running']
            assert worker.wait(timeout=40) == 0
        assert not record.exists()
        observed = json.loads((workspace / '.local/timeout/interrupted-state.json').read_text())
        assert json.loads(observed['stdout'])['active']['run'] == job['run']
        return dict(case='managed-runners', success_and_failure_results_retained=True,
                    timeout_observation_and_original_logs_retained=True,
                    mismatched_run_rejected_without_stopping_live_container=True,
                    timed_out_run_confirmed_retired=True)
    finally:
        if worker is not None and worker.poll() is None:
            os.killpg(worker.pid, signal.SIGKILL)
            worker.wait(timeout=5)
        if record.exists() and job is not None:
            fixture_call(workspace, 'stop', '--run', job['run'])


CASES = {
    'interrupted-success': lambda attempt: candidate_case(attempt, 'interrupted-success', 0),
    'interrupted-failure': lambda attempt: candidate_case(attempt, 'interrupted-failure', 7),
    'command-contract': command_case,
    'created-recovery': created_case,
    'creation-reservation': reservation_case,
    'running-stop': running_stop_case,
    'removal-retry': removal_case,
    'logging-rotation': lambda attempt: logging_case(attempt, 'rotation'),
    'logging-nonblocking': lambda attempt: logging_case(attempt, 'nonblocking'),
    'created-cancellation': cancellation_case,
    'attachment-race': attachment_case,
    'delayed-start': delayed_start_case,
    'managed-runners': managed_runner_case,
}


def candidate(selected=None):
    os.umask(0o077)
    attempt = ROOT / '.local/build/docker-ownership/attempts' / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    print('Docker ownership evidence:', attempt, flush=True)
    inputs = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        'tools/run-logged.sh', 'tools/docker-stage.py', 'tools/build-bin/docker',
        'tools/check-docker-stage.py', 'tools/managed_container.py',
        'tools/kernel_sources.py', 'build/sources.lock.json')}
    (attempt / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
    results = []
    cases = {selected: CASES[selected]} if selected else CASES
    for case in cases.values():
        results.append(case(attempt))
        (attempt / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
        print(results[-1]['case'] + ' passed', flush=True)
    assert inputs == {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in inputs}
    print('Docker ownership candidate cases passed', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--baseline', action='store_true')
    selection.add_argument('--case', choices=CASES, default=os.environ.get('NEO_DOCKER_OWNERSHIP_CASE') or None)
    options = parser.parse_args()
    if options.case and options.case not in CASES:
        parser.error('Unknown Docker ownership fixture case')
    baseline() if options.baseline else candidate(options.case)
