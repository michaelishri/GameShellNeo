"""Replay actual inventory host routes over local channels; no collector or SSH."""
from contextlib import contextmanager, redirect_stdout
import copy
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import charge_inventory as inventory
import charge_result
import inventory_result
import remote
from test_charge_inventory import metadata, register_data, checkpoint
from test_charge_baseline import sample

spec = importlib.util.spec_from_file_location('inventory_result_host', TOOLS/'check-charge-inventory.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
PAIRS = [(f'0.1.0-diagnostic.{20+i}', f'6.18.54-gameshellneo{19+i}') for i in range(4)]


def representative(pair=PAIRS[0]):
    version, kernel = pair
    profile, volatile = inventory.profile_for(kernel, version)
    registers = register_data(**{'78': 0xf0, '79': 0x1d})
    for index, (address, entry) in enumerate(registers.items()):
        entry['source'] = 'volatile-regmap-read' if int(address, 16) in volatile else 'regmap-cache-possible'
        entry['before'] = checkpoint(100_000_001_000+index*1000, offset=50_000_000)['clock']
        entry['after'] = checkpoint(100_000_001_100+index*1000, offset=50_000_000)['clock']
    masked = pair in (inventory.MASKED_ADC_PROFILE, inventory.NO_LEGACY_PTY_PROFILE)
    return dict(schema_version=4, kind='axp223-charge-inventory', completed=True,
        limits=list(inventory.LIMITS), kernel=kernel,
        image=dict(version=version, kernel=kernel, board='gameshellneo-cpi31'),
        before=checkpoint(100_000_000_000, offset=50_000_000),
        after=checkpoint(100_000_100_000, offset=50_000_000),
        cache_profile=profile, adc_width_masked=masked,
        metadata=metadata(volatile_b8=0xb8 in volatile), registers=registers,
        supplies=sample(0)['supplies'], assessment=inventory.decode(registers, adc_width_masked=masked))


class ScriptedChannel:
    def __init__(self, client):
        self.client = client
        self.closed = False
        self.timeout = None
        self.receives = 0

    def settimeout(self, value):
        self.timeout = value

    def set_combine_stderr(self, value):
        assert value is True

    def exec_command(self, command):
        self.client.command = command
        self.client.launches += 1
        with (self.client.local/'pm-stages.lock').open('a') as guard:
            try:
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.client.pm_lock_held = True
            else:
                raise AssertionError('Original PM lock is not held')
        self.parts = [self.client.raw[:7], self.client.raw[7:], b'']

    def sendall(self, value):
        self.client.stdin += value

    def shutdown_write(self):
        self.client.stdin_closed = True

    def recv(self, size):
        assert size == 65536 and self.client.stdin_closed
        self.receives += 1
        if self.client.response_error and self.receives == 2:
            raise self.client.response_error
        return self.parts.pop(0)

    def recv_exit_status(self):
        return self.client.exit_code

    def close(self):
        self.closed = True


class ScriptedClient:
    def __init__(self, raw, local, *, exit_code=0, response_error=None):
        self.raw, self.local = raw, local
        self.exit_code, self.response_error = exit_code, response_error
        self.stdin, self.stdin_closed = b'', False
        self.launches = 0
        self.pm_lock_held = self.context_exited = False
        self.command = self.channel = None

    def get_transport(self):
        return self

    def open_session(self, timeout):
        assert timeout == 10
        self.channel = ScriptedChannel(self)
        return self.channel


@contextmanager
def local_device(client, config, route):
    assert config == {'fixture_only': True} and route == 'usb'
    try:
        yield client
    finally:
        client.context_exited = True


class HostInventoryAdmission(unittest.TestCase):
    def exercise(self, name, result, *, family, pair=PAIRS[0], accept=False,
                 raw=None, exit_code=0, timeout=False, error=ValueError):
        raw = raw if raw is not None else (json.dumps(result, indent=2)+'\n').encode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'build').mkdir(); (root/'tools').mkdir()
            lock = json.loads((host.ROOT/'build/sources.lock.json').read_text())
            version, kernel = pair
            lock['image_version'] = version
            lock['linux']['localversion'] = kernel[len(lock['linux']['tag'])-1:]
            lock_path = root/'build/sources.lock.json'
            lock_path.write_text(json.dumps(lock, indent=2)+'\n')
            payload = (TOOLS/'charge_inventory.py').read_bytes()
            (root/'tools/charge_inventory.py').write_bytes(payload)
            client = ScriptedClient(raw, root/'.local', exit_code=exit_code,
                response_error=TimeoutError('scripted original response inactivity timeout') if timeout else None)
            stdout = io.StringIO(); caught = None
            with patch.object(host, 'ROOT', root), patch.object(host, 'LOCAL', client.local), \
                    patch.object(remote, 'LOCAL', client.local), \
                    patch.object(host, 'load_env', return_value={'fixture_only': True}), \
                    patch.object(host, 'device', side_effect=lambda config, route:local_device(client, config, route)), \
                    redirect_stdout(stdout):
                try:
                    host.main()
                except Exception as failure:
                    caught = failure
            # Preserve actual observations before assertions, including an
            # unexpected regression, rather than losing its temporary capture.
            lock_released = False
            if (client.local/'pm-stages.lock').exists():
                with (client.local/'pm-stages.lock').open('a') as guard:
                    try:
                        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        lock_released = True
            target = os.environ.get('NEO_INVENTORY_ADMISSION_RESULTS_DIR')
            if target:
                out = Path(target)/name; out.mkdir(parents=True)
                diagnostics = client.local/'diagnostics'
                observed_captures = list(diagnostics.iterdir()) if diagnostics.exists() else []
                observed_capture = observed_captures[0] if len(observed_captures) == 1 else None
                for filename in ['inventory.json', 'provenance.json', 'inventory.admission.json']:
                    if observed_capture is not None and (observed_capture/filename).exists():
                        (out/filename).write_bytes((observed_capture/filename).read_bytes())
                retained_raw = (out/'inventory.json').read_bytes() if (out/'inventory.json').exists() else b''
                (out/'host-stdout.txt').write_text(stdout.getvalue())
                (out/'observed.json').write_text(json.dumps(dict(schema=1, variant=name, family=family,
                    admitted=caught is None, expected_accept=accept, expected_image=version, expected_kernel=kernel,
                    supported_historical_fixture=pair in PAIRS,
                    current27_fixture=pair == ('0.1.0-diagnostic.27', '6.18.54-gameshellneo26'),
                    current27_eligibility_claimed=False, error_type=type(caught).__name__ if caught else None,
                    error=str(caught) if caught else None, raw_sha256=hashlib.sha256(retained_raw).hexdigest(),
                    actual_main=True, actual_remote_run_used=client.launches == 1,
                    actual_python_command_used=host.python_command is remote.python_command,
                    payload_sha256=hashlib.sha256(client.stdin).hexdigest(), payload_bytes=len(client.stdin),
                    payload_bytes_unchanged=client.stdin == payload, command=client.command,
                    response_timeout=client.channel.timeout if client.channel else None, session_timeout=10,
                    separate_remote_process_deadline=False,
                    original_timeout_identity_preserved=(caught is client.response_error) if timeout else None,
                    pm_lock_held=client.pm_lock_held, pm_lock_released=lock_released,
                    channel_closed=client.channel.closed if client.channel else False,
                    device_context_exited=client.context_exited, stdin_closed=client.stdin_closed,
                    capture=str(observed_capture) if observed_capture else None,
                    preserved_before_assertions=True, no_collector_entrypoint=True, no_ssh_or_sysfs=True), indent=2)+'\n')
            self.assertEqual(caught is None, accept)
            self.assertTrue(lock_released)
            if not accept:
                self.assertIsInstance(caught, error)
            if timeout:
                self.assertIs(caught, client.response_error)
            if exit_code:
                self.assertEqual(str(caught), 'Remote command failed (exit 7)')
            captures = list((client.local/'diagnostics').iterdir())
            self.assertEqual(len(captures), 1)
            capture = captures[0]; saved = (capture/'inventory.json').read_bytes()
            self.assertEqual(saved, raw[:7] if timeout else raw)
            self.assertEqual(client.launches, 1)
            self.assertTrue(client.pm_lock_held and client.stdin_closed and client.context_exited and client.channel.closed)
            self.assertEqual(client.channel.timeout, 40)
            self.assertEqual(client.stdin, payload)
            self.assertEqual(shlex.split(client.command), ['sudo', '-n', 'python3', '-B', '-',
                '--kernel', kernel, '--image', version])
            provenance = json.loads((capture/'provenance.json').read_text())
            self.assertEqual(provenance, dict(helper_sha256=hashlib.sha256(payload).hexdigest(),
                sources_lock_sha256=hashlib.sha256(lock_path.read_bytes()).hexdigest(), route='usb', linux='v6.18.54'))
            receipt = capture/'inventory.admission.json'
            self.assertEqual(receipt.exists(), accept)
            if accept:
                admitted = json.loads(receipt.read_text())
                self.assertEqual(admitted['raw_sha256'], hashlib.sha256(saved).hexdigest())
                self.assertEqual(admitted['assessment'], result['assessment'])
                self.assertEqual(admitted['register_count'], 11)
                self.assertEqual(admitted['awake_validation']['observation_count'], 24)
                self.assertFalse(admitted['calibrated'] or admitted['charging_safety_qualified'] or
                    admitted['sleep_charge_measured'] or admitted['current_device_or_image_admitted'] or
                    admitted['clock_reliability_qualified'])
                prefix = 'Private charge inventory: '+str(capture)+'\n'
                self.assertTrue(stdout.getvalue().startswith(prefix))
                self.assertEqual(json.loads(stdout.getvalue()[len(prefix):]),
                    dict(boot_id=result['before']['boot_id'], assessment=result['assessment'], limits=result['limits']))
            with (client.local/'pm-stages.lock').open('a') as guard:
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_supported_controls(self):
        for index, pair in enumerate(PAIRS):
            name = 'A-historical20' if index == 0 else f'historical{20+index}'
            with self.subTest(name=name):
                self.exercise(name, representative(pair), family='supported_controls', pair=pair, accept=True)
        result = representative()
        clocks = [result['before']['clock'], result['after']['clock']]
        clocks += [entry[point] for entry in result['registers'].values() for point in ('before', 'after')]
        for value in clocks:
            value.update(offset_low_ns=-123456789, offset_high_ns=123456789)
        self.exercise('valid-raw-forged-stored-offsets', result, family='supported_controls', accept=True)

    def test_missing_and_legacy(self):
        result = representative(PAIRS[1])
        minimal = {key:result[key] for key in ('kind', 'completed', 'assessment', 'limits')}
        minimal['before'] = {'boot_id':result['before']['boot_id']}
        self.exercise('B-missing-raw', minimal, family='missing_legacy', pair=PAIRS[1])
        for name, key in [('missing-schema','schema_version'), ('missing-before','before'),
                          ('missing-after','after'), ('missing-metadata','metadata'), ('missing-supplies','supplies')]:
            result = representative(); del result[key]
            with self.subTest(name=name):self.exercise(name, result, family='missing_legacy')
        result = representative(); result['schema_version'] = 3
        self.exercise('legacy-schema3', result, family='missing_legacy')

    def test_operation_profile_and_limits(self):
        for name in ['wrong-kernel','wrong-image','wrong-board','unaudited-pair','unsupported-current27',
                     'wrong-cache-profile','wrong-adc-width','wrong-limits']:
            result = representative(); pair = PAIRS[0]
            if name == 'wrong-kernel':result['kernel'] = 'wrong'
            elif name == 'wrong-image':result['image']['version'] = 'wrong'
            elif name == 'wrong-board':result['image']['board'] = 'wrong'
            elif name in ('unaudited-pair','unsupported-current27'):
                pair = (PAIRS[0][0],PAIRS[1][1]) if name == 'unaudited-pair' else ('0.1.0-diagnostic.27','6.18.54-gameshellneo26')
                result['kernel'] = result['image']['kernel'] = pair[1]
                result['image']['version'] = pair[0]
            elif name == 'wrong-cache-profile':result['cache_profile'] = 'not-an-audited-profile'
            elif name == 'wrong-adc-width':result['adc_width_masked'] = True
            else:result['limits'] = []
            with self.subTest(name=name):self.exercise(name, result, family='operation_profile_limits', pair=pair)

    def test_register_records(self):
        for name in ['missing-register','extra-register','boolean-value','float-value','value256',
                     'wrong-source','missing-register-clock','duplicate-json-register-key']:
            result = representative(); raw = None
            if name == 'missing-register':del result['registers']['00']
            elif name == 'extra-register':result['registers']['02'] = copy.deepcopy(result['registers']['00'])
            elif name == 'boolean-value':result['registers']['00']['value'] = False
            elif name == 'float-value':result['registers']['00']['value'] = 0.0
            elif name == 'value256':result['registers']['00']['value'] = 256
            elif name == 'wrong-source':result['registers']['00']['source'] = 'regmap-cache-possible'
            elif name == 'missing-register-clock':del result['registers']['00']['before']
            else:
                raw = (json.dumps(result, indent=2)+'\n').encode()
                duplicate = raw.replace(b'"value": 0,', b'"value": 0, "value": 0,', 1)
                self.assertNotEqual(raw, duplicate); raw = duplicate
            with self.subTest(name=name):self.exercise(name, result, family='register_records', raw=raw)

    def test_clock_pm_and_boot(self):
        for name in ['C-changed-success','changed-fail','changed-boot','raw-boolean','raw-float','raw-negative',
                     'bracket-wide','bracket-backward','offset-shift-positive','offset-shift-negative','register-clock-out-of-order']:
            pair = PAIRS[2] if name == 'C-changed-success' else PAIRS[0]
            result = representative(pair); clock = result['registers']['00']['before']
            if name == 'C-changed-success':result['after']['pm']['success'] = '12'
            elif name == 'changed-fail':result['after']['pm']['fail'] = '1'
            elif name == 'changed-boot':result['after']['boot_id'] = 'different'
            elif name == 'raw-boolean':clock['boottime_ns'] = True
            elif name == 'raw-float':clock['boottime_ns'] = float(clock['boottime_ns'])
            elif name == 'raw-negative':clock['boottime_ns'] = -1
            elif name == 'bracket-wide':clock['monotonic_after_ns'] = clock['monotonic_before_ns']+1_000_001
            elif name == 'bracket-backward':clock['monotonic_after_ns'] = clock['monotonic_before_ns']-1
            elif name.startswith('offset-shift'):
                clock['boottime_ns'] += 2_000_000 if name.endswith('positive') else -2_000_000
            else:
                for key in ('monotonic_before_ns','boottime_ns','monotonic_after_ns'):
                    result['registers']['01']['before'][key] -= 10_000
            with self.subTest(name=name):self.exercise(name, result, family='clock_pm_boot', pair=pair)

    def test_metadata(self):
        for name in ['E-bad-metadata-profile-width','cache-bypass','wrong-range','missing-access-row','wrong-b8-policy']:
            result = representative()
            if name == 'E-bad-metadata-profile-width':
                result['metadata']['cache_bypass'] = 'Y'
                result['cache_profile'] = 'not-an-audited-profile'; result['adc_width_masked'] = True
            elif name == 'cache-bypass':result['metadata']['cache_bypass'] = 'Y'
            elif name == 'wrong-range':result['metadata']['range'] = '0-ff'
            elif name == 'missing-access-row':result['metadata']['access'] = '\n'.join(result['metadata']['access'].splitlines()[:-1])
            else:result['metadata']['access'] = result['metadata']['access'].replace('b8: y n n n','b8: y n y n')
            with self.subTest(name=name):self.exercise(name, result, family='metadata')

    def test_recomputed_assessment(self):
        for name in ['D-raw-adc-stored-assessment','forged-capacity','forged-gauge','forged-numeric-type']:
            pair = PAIRS[3] if name == 'D-raw-adc-stored-assessment' else PAIRS[0]
            result = representative(pair)
            if name == 'D-raw-adc-stored-assessment':result['registers']['78']['value'] ^= 1
            elif name == 'forged-capacity':result['assessment']['cached_configuration']['configured_capacity_uah'] += 1
            elif name == 'forged-gauge':result['assessment']['gauge_result']['percent'] = 99
            else:
                voltage = result['assessment']['battery_voltage_bytes']
                voltage['linux_helper_formula_uv'] = float(voltage['linux_helper_formula_uv'])
            with self.subTest(name=name):self.exercise(name, result, family='assessment', pair=pair)

    def test_original_errors(self):
        result = representative(PAIRS[1]); raw = (json.dumps(result, indent=2)+'\n').encode()[:-11]
        self.exercise('F-truncated-json', result, family='original_errors', pair=PAIRS[1], raw=raw, error=json.JSONDecodeError)
        self.exercise('G-original-exit7', representative(PAIRS[2]), family='original_errors', pair=PAIRS[2], exit_code=7, error=RuntimeError)
        self.exercise('H-original-response-timeout', representative(PAIRS[3]), family='original_errors', pair=PAIRS[3], timeout=True, error=TimeoutError)

    def test_pure_replay_does_not_mutate_or_invoke_collectors(self):
        result = representative(); original = copy.deepcopy(result)
        self.assertIs(inventory_result.checkpoint, charge_result.checkpoint)
        with patch.object(inventory, 'inspect', side_effect=AssertionError('collector entrypoint')), \
                patch.object(inventory, 'read', side_effect=AssertionError('collector read')), \
                patch.object(inventory, 'clock', side_effect=AssertionError('collector clock')), \
                patch.object(charge_result.sampler, 'capture', side_effect=AssertionError('sampler entrypoint')):
            admitted = inventory_result.admit(result, kernel=PAIRS[0][1], image=PAIRS[0][0])
        self.assertEqual(result, original)
        self.assertEqual(admitted['awake_validation']['observation_count'], 24)
        self.assertIn('boundary', admitted['register_clock_context'])

    def test_receipt_is_exclusive_and_refused_raw_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'inventory.json'; raw = (json.dumps(representative())+'\n').encode()
            path.write_bytes(raw)
            inventory_result.admit_capture(path, kernel=PAIRS[0][1], image=PAIRS[0][0])
            receipt = path.with_suffix('.admission.json'); first = receipt.read_bytes()
            with self.assertRaises(FileExistsError):
                inventory_result.admit_capture(path, kernel=PAIRS[0][1], image=PAIRS[0][0])
            self.assertEqual(path.read_bytes(), raw); self.assertEqual(receipt.read_bytes(), first)
            refused = Path(directory)/'refused.json'; rejected = b'{"completed": true}\n'; refused.write_bytes(rejected)
            with self.assertRaises(ValueError):
                inventory_result.admit_capture(refused, kernel=PAIRS[0][1], image=PAIRS[0][0])
            self.assertEqual(refused.read_bytes(), rejected)
            self.assertFalse(refused.with_suffix('.admission.json').exists())
