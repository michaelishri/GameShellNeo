#!/usr/bin/env python3
"""Qualify joined native bodies or verify unchanged historical object context."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

from kernel_sources import atomic_json, locked
from managed_container import execute
import musb_combined_lifecycle_source as source

ROOT = Path(__file__).resolve().parents[1]
FLAGS = ('-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror')
MAINTAINED = ('tools/check-musb-combined-lifecycle.py', 'tools/musb_combined_lifecycle_source.py',
              'kernel/tests/musb_combined_lifecycle_test.c', 'tools/kernel_sources.py',
              'tools/kernel-inputs.py', 'tools/kernel_candidates.py',
              'tools/musb_terminal_wake_source.py', 'tools/managed_container.py',
              'tools/docker-stage.py', 'build/sources.lock.json', 'Taskfile.yml',
              'tools/tests/test_musb_combined_lifecycle.py')


def checked_native(result, *, control=None):
    """Admit only the entire predeclared stream, including control failures."""
    if control is None:
        expected = ''.join('CASE ' + name + ' PASS\n' for name in source.CASES)
        expected += 'MUSB combined lifecycle: 14 actual-source families passed\n'
        code = 0
    else:
        name, fields = source.CONTROLS[control]
        expected = ''.join('FAIL ' + name + ' ' + field + '\n' for field in fields)
        expected += 'CASE ' + name + ' FAIL\n'
        expected += f'CONTROL {control} {len(fields)} observations\n'
        code = 1
    if result.returncode != code or result.stdout != expected or result.stderr:
        raise ValueError('Wrong, incomplete or diagnostic-bearing native result')
    return dict(returncode=code, cases=list(source.CASES) if control is None else [name],
                stdout_sha256=hashlib.sha256(expected.encode()).hexdigest())


def run(attempt, name, command, **kwargs):
    result = subprocess.run(command, text=True, capture_output=True, **kwargs)
    (attempt / (name + '.stdout')).write_text(result.stdout)
    (attempt / (name + '.stderr')).write_text(result.stderr)
    atomic_json(attempt / (name + '.result.json'),
                dict(command=command, returncode=result.returncode,
                     stdout_sha256=source.sha256(attempt / (name + '.stdout')),
                     stderr_sha256=source.sha256(attempt / (name + '.stderr'))))
    return result


def native(attempt, texts):
    body, pins = source.native_functions(texts)
    header = attempt / 'musb_combined_lifecycle_functions.h'
    header.write_text(body)
    harness = ROOT / 'kernel/tests/musb_combined_lifecycle_test.c'
    compiler = subprocess.check_output(['cc', '--version'], text=True)
    (attempt / 'compiler.txt').write_text(compiler)
    binary = attempt / 'candidate'
    command = ['cc', *FLAGS, '-I', str(attempt), str(harness), '-o', str(binary)]
    compile_result = run(attempt, 'compile', command)
    if compile_result.returncode:
        raise ValueError('Native compiler failed; original output retained')
    observations = {}
    for control in (None, *source.CONTROLS):
        name = control or 'positive'
        result = run(attempt, name, [str(binary), *([control] if control else [])])
        observations[name] = checked_native(result, control=control)
    sanitized = attempt / 'candidate-sanitize'
    sanitizer = run(attempt, 'sanitize-compile', ['cc', *FLAGS, '-O1', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
        '-I', str(attempt), str(harness), '-o', str(sanitized)])
    if sanitizer.returncode:
        raise ValueError('Sanitizer compiler failed; original output retained')
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')
    for control in (None, *source.CONTROLS):
        name = 'sanitize-' + (control or 'positive')
        result = run(attempt, name, [str(sanitized), *([control] if control else [])],
                     env=environment)
        observations[name] = checked_native(result, control=control)
    return dict(functions=pins, header_sha256=source.sha256(header),
                binary_sha256=source.sha256(binary),
                sanitizer_binary_sha256=source.sha256(sanitized), observations=observations,
                compiler_sha256=source.sha256(attempt / 'compiler.txt'))


def context(receipt_path, metadata):
    """Verify historical executions without changing their recorded base."""
    receipt_path = receipt_path.absolute()
    historical_root = receipt_path.parents[3]
    record = json.loads(receipt_path.read_text())
    expected = metadata['spec']['patches']
    if record.get('queues', {}).get(source.PROFILE) != expected or len(record.get('builds', {})) != 6:
        raise ValueError('Historical complete-object receipt has wrong source/configuration scope')
    verified = {}
    for name, build in record['builds'].items():
        shared = build['shared_source']
        if shared['spec'] != metadata['spec'] or shared['tree_sha256'] != metadata['tree_sha256']:
            raise ValueError('Historical object source differs: ' + name)
        scratch = historical_root / build['scratch']
        configuration = scratch / 'output/.config'
        if source.sha256(configuration) != build['config_sha256']:
            raise ValueError('Historical effective config drift: ' + name)
        text = configuration.read_text()
        if ('CONFIG_USB_MUSB_SUNXI=' not in text or 'CONFIG_PHY_SUN4I_USB=y' not in text or
                'CONFIG_EXTCON=y' not in text):
            raise ValueError('Historical configuration does not select the bounded Sunxi closure')
        objects = {}
        for path, expected_hash in build['objects'].items():
            file = scratch / 'output' / path
            if source.sha256(file) != expected_hash:
                raise ValueError('Historical object bytes drift: ' + name + ':' + path)
            with file.open('rb') as stream:
                if stream.read(4) != b'\x7fELF':
                    raise ValueError('Historical object is not ELF: ' + path)
            objects[path] = expected_hash
        verified[name] = dict(config_sha256=build['config_sha256'], objects=objects,
                              historical_build=build)
    return dict(historical_receipt=dict(path=str(receipt_path), sha256=source.sha256(receipt_path)),
                builds=verified, new_object_execution=False)


ORIGINAL_NATIVE_REF = 'c39f8b248245e3af397e1a90b5c0113570392a04'


def _git_blob(reference, name):
    return subprocess.check_output(['git', 'show', reference + ':' + name], cwd=ROOT)


def _native_contract(text):
    tree = ast.parse(text)
    functions = {node.name: ast.get_source_segment(text, node) for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in ('native', 'checked_native', 'run')}
    flags = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
             and any(isinstance(target, ast.Name) and target.id == 'FLAGS' for target in node.targets)]
    if len(functions) != 3 or len(flags) != 1:
        raise ValueError('Incomplete original native execution/validator contract')
    return dict(functions=functions, flags=flags[0])


def _task_blocks(text):
    import re
    result = {}
    for name in ('test:musb-combined-lifecycle', 'check:musb-combined-lifecycle-context'):
        blocks = re.findall(r'^  ' + re.escape(name) + r':\n.*?(?=^  \S|\Z)', text, re.M | re.S)
        if len(blocks) != 1:
            raise ValueError('Missing or duplicate original joined Task block: ' + name)
        result[name] = blocks[0]
    return result


def native_admission(previous, receipt, *, source_ref=None):
    current = {name: source.sha256(ROOT / name) for name in MAINTAINED}
    if previous.get('stage') != 'native':
        raise ValueError('ARM stage requires a successful native execution')
    differences = {name: dict(historical=previous.get('inputs', {}).get(name), current=value)
                   for name, value in current.items() if previous.get('inputs', {}).get(name) != value}
    if source_ref is None:
        if differences:
            raise ValueError('ARM stage requires exact native inputs or explicit original source equivalence')
        return dict(admission='exact whole-file native inputs', inputs=current)
    if source_ref != ORIGINAL_NATIVE_REF:
        raise ValueError('Historical admission requires the exact original nativec39 source SHA')
    original = {name: _git_blob(source_ref, name) for name in MAINTAINED}
    historical = {name: hashlib.sha256(data).hexdigest() for name, data in original.items()}
    if previous.get('inputs') != historical:
        raise ValueError('Original native receipt does not match actual original Git blobs')
    allowed = {'Taskfile.yml', 'tools/check-musb-combined-lifecycle.py'}
    if set(differences) - allowed:
        raise ValueError('Native C/type/projector/queue/locking input changed')
    checker = 'tools/check-musb-combined-lifecycle.py'
    if _native_contract(original[checker].decode()) != _native_contract((ROOT / checker).read_text()):
        raise ValueError('Native execution, flags or complete result validator changed')
    tasks = _task_blocks(original['Taskfile.yml'].decode())
    if tasks != _task_blocks((ROOT / 'Taskfile.yml').read_text()):
        raise ValueError('Original joined native/context Task behavior changed')
    # Read genuine original full streams, not synthesized summaries. Never
    # execute or alter the retained binaries/source/receipt in this admission.
    for control in (None, *source.CONTROLS):
        for sanitized in (False, True):
            name = ('sanitize-' if sanitized else '') + (control or 'positive')
            result_file = receipt.parent / (name + '.result.json')
            record = json.loads(result_file.read_text())
            stdout_file = receipt.parent / (name + '.stdout')
            stderr_file = receipt.parent / (name + '.stderr')
            if (source.sha256(stdout_file) != record['stdout_sha256'] or
                    source.sha256(stderr_file) != record['stderr_sha256']):
                raise ValueError('Original native result/output hash changed')
            result = subprocess.CompletedProcess(record['command'], record['returncode'],
                stdout_file.read_text(), stderr_file.read_text())
            if checked_native(result, control=control) != previous['observations']['observations'][name]:
                raise ValueError('Original native full output differs from successful receipt')
    for name, key in (('candidate', 'binary_sha256'), ('candidate-sanitize', 'sanitizer_binary_sha256'),
                      ('compiler.txt', 'compiler_sha256')):
        if source.sha256(receipt.parent / name) != previous['observations'][key]:
            raise ValueError('Original native artifact changed: ' + name)
    return dict(admission='explicit historical execution with exact native closure equivalence',
                original_source_ref=source_ref, original_git_blob_hashes=historical,
                original_receipt_sha256=source.sha256(receipt), current_inputs=current,
                changed_whole_file_pins=differences,
                original_task_blocks={name: hashlib.sha256(data.encode()).hexdigest()
                                      for name, data in tasks.items()}, original_full_outputs_readmitted=True)


def arm(attempt, texts, native_receipt, *, source_ref=None):
    previous = json.loads(native_receipt.read_text())
    body, pins = source.native_functions(texts)
    header = attempt / 'musb_combined_lifecycle_functions.h'
    header.write_text(body)
    admission = native_admission(previous, native_receipt, source_ref=source_ref)
    if (previous['observations']['functions'] != pins or
            previous['observations']['header_sha256'] != source.sha256(header)):
        raise ValueError('ARM stage requires the exact successful native closure')
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    builder = lock['builder']
    # Each program's complete output and raw result are validated inside one
    # positive managed command. There is no observer timeout or restart.
    program = '''import importlib.util,json,pathlib,subprocess,sys
sys.dont_write_bytecode=True
sys.path.insert(0,'tools')
from kernel_sources import atomic_json
from musb_combined_lifecycle_source import CONTROLS,sha256
spec=importlib.util.spec_from_file_location('joined_check','tools/check-musb-combined-lifecycle.py')
check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)
attempt=pathlib.Path('/project')/sys.argv[1]
cross=sys.argv[2]
flags=json.loads(sys.argv[3])
binary=attempt/'candidate-arm'
subprocess.run([cross+'gcc',*flags,'-static','-I',str(attempt),
    'kernel/tests/musb_combined_lifecycle_test.c','-o',str(binary)],check=True)
records={}
for control in (None,*CONTROLS):
    name='arm-'+(control or 'positive')
    result=check.run(attempt,name,['qemu-arm',str(binary),*([control] if control else [])])
    records[name]=check.checked_native(result,control=control)
atomic_json(attempt/'arm-observations.json',dict(observations=records,
    binary_sha256=sha256(binary),compiler=subprocess.check_output([cross+'gcc','--version'],text=True),
    emulator=subprocess.check_output(['qemu-arm','--version'],text=True)))
'''
    result = execute('musb-combined-lifecycle-arm', ['--pull=never', '--network', 'none',
        '--cpus=1', '--memory=256m',
        '--user', f'{os.getuid()}:{os.getgid()}', '--platform', builder['platform'],
        '--entrypoint', 'python3', '-v', f'{ROOT}:/project:ro',
        '-v', f'{attempt}:/project/{attempt.relative_to(ROOT).as_posix()}',
        '-w', '/project', builder['image'],
        '-c', program, attempt.relative_to(ROOT).as_posix(), builder['cross_compile'],
        json.dumps(FLAGS)], attempt / 'managed-arm', timeout=None)
    return dict(managed_result=result, native_admission=admission, reference_native=dict(path=str(native_receipt),
        sha256=source.sha256(native_receipt)), header_sha256=source.sha256(header),
        functions=pins, **json.loads((attempt / 'arm-observations.json').read_text()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verified-source', type=Path, required=True)
    parser.add_argument('--stage', choices=('native', 'arm', 'context'), default='native')
    parser.add_argument('--object-receipt', type=Path)
    parser.add_argument('--native-receipt', type=Path)
    parser.add_argument('--native-source-ref', help='Explicit originalc39 native provenance admission only')
    args = parser.parse_args()
    if (args.stage == 'context') != (args.object_receipt is not None):
        parser.error('--object-receipt belongs only to --stage context')
    if (args.stage == 'arm') != (args.native_receipt is not None):
        parser.error('--native-receipt belongs only to --stage arm')
    if args.native_source_ref is not None and args.stage != 'arm':
        parser.error('--native-source-ref belongs only to --stage arm')
    work = ROOT / '.local/build/musb-combined-lifecycle'
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.lock'):
        attempt = work / ('attempt-' + uuid.uuid4().hex)
        attempt.mkdir()
        inputs = {name: source.sha256(ROOT / name) for name in MAINTAINED}
        atomic_json(attempt / 'plan.json', dict(stage=args.stage, cases=source.CASES,
            controls=source.CONTROLS, inputs=inputs, limits=source.LIMITS,
            existing_source=str(args.verified_source), fixture_frameworks='modeled'))
        try:
            texts, metadata = source.verified_source(ROOT, args.verified_source)
            if args.stage == 'native':
                observations = native(attempt, texts)
            elif args.stage == 'arm':
                observations = arm(attempt, texts, args.native_receipt, source_ref=args.native_source_ref)
            else:
                observations = context(args.object_receipt, metadata)
            if inputs != {name: source.sha256(ROOT / name) for name in MAINTAINED}:
                raise ValueError('Maintained inputs changed during observation')
            result = dict(schema=1, stage=args.stage, inputs=inputs, source=metadata,
                          observations=observations, limits=source.LIMITS)
            atomic_json(attempt / 'evidence.json', result)
            print('Joined lifecycle evidence:', attempt / 'evidence.json', flush=True)
        except BaseException as error:
            atomic_json(attempt / 'failure.json', dict(error=type(error).__name__, message=str(error),
                                                       inputs=inputs))
            print('Original failed attempt retained:', attempt, flush=True)
            raise


if __name__ == '__main__':
    main()
