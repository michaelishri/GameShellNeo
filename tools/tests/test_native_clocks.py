"""Raw clock evidence, ELF attribution and a single failed attempt stay intact."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import native_clock_report as report


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, TOOLS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


host = load('native_clock_host_test', 'check-native-clocks.py')
builder = load('native_clock_build_test', 'build-native-clocks.py')


def records(count):
    meta = dict(boot_id='boot', clocksource='arch_sys_counter', affinity=15)
    header = dict(type='header', schema=1, operation='native-clock-comparison', batches=300,
        per_batch=50, pause_ns=100000000, routes=list(report.ROUTES), clocks=list(report.CLOCKS),
        vdso_symbol='__vdso_clock_gettime64', vdso_version='LINUX_2.6', vdso_base_verified=True,
        libc='2.41', before=meta)
    footer = dict(type='footer', complete=True, completed=count, after=deepcopy(meta),
        failure=dict(present=False, sequence=0, clock=0, position=0, stage=0, rc=0, errno=0, sec=0, nsec=0))
    rows = [dict(type='sample', index=i+1, clocks=[dict(cpu_before=i%4, cpu_after=i%4,
        ns=[2**55 + i*10000 + c*1000 + p*100 for p in range(9)]) for c in range(3)]) for i in range(count)]
    return [header, *rows, footer]


def encode(rows):
    return ('\n'.join(json.dumps(row) for row in rows) + '\n').encode()


class NativeClockTests(unittest.TestCase):
    def analyze(self, rows):
        with patch.object(report, 'SAMPLES', 4):
            return report.analyze(encode(rows), 'boot', '2.41')

    def test_all_production_readings_classified_without_float_conversion(self):
        value = report.analyze(encode(records(15000)), 'boot', '2.41')
        self.assertEqual(value['reads'], 405000)
        self.assertEqual(value['discrepancy_sequences'], 0)
        self.assertFalse(value['pm_admission'])
        for stats in value['statistics'].values():
            self.assertEqual(len(stats['adjacent']), 6)
            self.assertEqual(sum(item['count'] for item in stats['adjacent'].values()), 120000)
            self.assertTrue(all(item['min_ns'] == 100 for item in stats['adjacent'].values()))
            self.assertTrue(all(item['count'] == 14999 for item in stats['between'].values()))
            self.assertEqual(sum(stats['cpu_before_counts'].values()), 15000)

    def test_cross_path_only_discrepancy_is_not_mislabeled_as_path_regression(self):
        rows = records(4)
        ns = rows[1]['clocks'][1]['ns']
        ns[2] = ns[1] - 50
        result = self.analyze(rows)
        stats = result['statistics']['4']
        self.assertEqual(result['discrepancy_sequences'], 1)
        self.assertEqual(stats['adjacent']['kernel->vdso']['min_ns'], -50)
        self.assertEqual(sum(v['negative'] for v in stats['within'].values()), 0)
        self.assertEqual(result['first_events'][0]['sample']['clocks'][1]['ns'], ns)
        self.assertFalse(result['vdso_internal_fallback_excluded'])

    def test_individual_route_regressions_and_between_sequence_values_are_retained(self):
        for route, name in enumerate(report.NAMES):
            rows = records(4)
            positions = [i for i, r in enumerate(report.ROUTES) if r == route]
            ns = rows[1]['clocks'][0]['ns']
            ns[positions[1]] = ns[positions[0]] - 7
            result = self.analyze(rows)
            self.assertEqual(result['statistics']['1']['within'][name]['negative'], 1)
            rows = records(4)
            rows[2]['clocks'][0]['ns'] = [n - 12000 for n in rows[2]['clocks'][0]['ns']]
            result = self.analyze(rows)
            self.assertEqual(result['statistics']['1']['between'][name]['negative'], 1)
            reason = next(r for r in result['first_events'][0]['reasons']
                          if r['kind'] == 'between' and r['route'] == name)
            self.assertIn('previous_ns', reason)

    def test_partial_failed_or_changed_identity_cannot_pass(self):
        for change in ('truncate', 'order', 'clock', 'reads', 'bool', 'float', 'overflow', 'negative',
                       'boot', 'clocksource', 'affinity', 'cpu', 'incomplete', 'failure', 'route',
                       'version', 'bounds', 'false-int'):
            rows = records(4)
            if change == 'truncate': rows.pop(2)
            if change == 'order': rows[2]['index'] = 1
            if change == 'clock': rows[1]['clocks'].pop()
            if change == 'reads': rows[1]['clocks'][0]['ns'].pop()
            if change == 'bool': rows[1]['clocks'][0]['ns'][0] = True
            if change == 'float': rows[1]['clocks'][0]['ns'][0] = 1.0
            if change == 'overflow': rows[1]['clocks'][0]['ns'][0] = 2**63
            if change == 'negative': rows[1]['clocks'][0]['ns'][0] = -1
            if change == 'boot': rows[-1]['after']['boot_id'] = 'other'
            if change == 'clocksource': rows[0]['before']['clocksource'] = 'timer'
            if change == 'affinity': rows[-1]['after']['affinity'] = 1
            if change == 'cpu': rows[1]['clocks'][0]['cpu_before'] = 4
            if change == 'incomplete': rows[-1]['complete'] = False
            if change == 'failure': rows[-1]['failure']['present'] = True
            if change == 'route': rows[0]['routes'][0] = 2
            if change == 'version': rows[0]['vdso_version'] = 'LINUX_9'
            if change == 'bounds': rows[0]['batches'] = 301
            if change == 'false-int': rows[0]['routes'][0] = False
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.analyze(rows)

    def test_event_summary_cap_does_not_discard_original_readings(self):
        rows = records(40)
        for row in rows[1:-1]:
            row['clocks'][0]['ns'][2] = row['clocks'][0]['ns'][1] - 1
        data = encode(rows)
        with patch.object(report, 'SAMPLES', 40):
            result = report.analyze(data, 'boot', '2.41')
        self.assertEqual(result['discrepancy_sequences'], 40)
        self.assertEqual(len(result['first_events']), 32)
        self.assertTrue(result['events_truncated'])
        self.assertEqual(data, encode(rows))

    def test_failed_execution_saves_stream_and_postflight_without_retry_or_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory)
            client = MagicMock()
            calls = []
            def remote(client, command, **kwargs):
                calls.append(command)
                if 'mktemp' in command: return b'/tmp/gameshellneo-native-clock.abcdefgh\n'
                if 'sha256sum' in command: return ('a'*64 + '  file\n').encode()
                kwargs['output'].write(b'{"partial":true}\nfailed syscall\n')
                raise RuntimeError('remote failed')
            after = Mock()
            with patch.object(host, 'run', side_effect=remote), patch.object(host, 'upload'), \
                    self.assertRaisesRegex(RuntimeError, 'remote failed'):
                host.execute(client, capture, {'files': {'compare-clocks-native': 'a'*64}}, capture, after)
            after.assert_called_once()
            self.assertEqual(len(calls), 3)
            self.assertEqual(sum('timeout' in c for c in calls), 1)
            self.assertIn(b'failed syscall', (capture / 'native-output.ndjson').read_bytes())
            client.open_sftp.return_value.__enter__.return_value.remove.assert_not_called()

    def test_remote_binary_hash_failure_stops_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory)
            after = Mock()
            with patch.object(host, 'upload'), patch.object(host, 'run',
                    side_effect=[b'/tmp/gameshellneo-native-clock.abcdefgh', b'bad file']) as run, \
                    self.assertRaisesRegex(ValueError, 'Staged native binary'):
                host.execute(MagicMock(), capture, {'files': {'compare-clocks-native': 'a'*64}}, capture, after)
            after.assert_called_once()
            self.assertEqual(run.call_count, 2)

    def test_elf_requires_time64_and_arm_hardfloat_interpreter(self):
        elf = 'ELF32 little endian ARM Version5 EABI hard-float ABI /lib/ld-linux-armhf.so.3 __clock_gettime64@GLIBC_2.34'
        builder.verify_elf(elf)
        for token in ('ELF32', 'Version5 EABI', 'hard-float ABI', '__clock_gettime64@GLIBC_2.34'):
            with self.subTest(token=token), self.assertRaises(ValueError):
                builder.verify_elf(elf.replace(token, 'changed'))
        self.assertEqual(builder.symbols('UND __clock_gettime64@GLIBC_2.34'),
                         builder.symbols('FUNC __clock_gettime64@@GLIBC_2.34'))

    def test_untrusted_capture_name_and_runtime_hash_rejected(self):
        for value in ('', '..', '/tmp/build', 'latest'):
            with self.assertRaises(ValueError): host.capture_path(value)
        inventory = dict(files=dict(libc=dict(path='/usr/lib/arm-linux-gnueabihf/libc.so.6', sha256='a'*64)))
        with patch.object(host, 'run', return_value=('b'*64 + ' file').encode()), \
                self.assertRaisesRegex(ValueError, 'Installed libc changed'):
            host.verify_remote_libc(Mock(), inventory)

    def test_missing_exports_are_valid_inventory_but_not_a_clock_comparison(self):
        meta = dict(boot_id='boot', clocksource='arch_sys_counter', affinity=15)
        value = dict(type='vdso-inventory', schema=1, complete=True, mapping_found=True,
            handle_base_verified=True, version='LINUX_2.6', libc='2.41', before=meta, after=deepcopy(meta),
            symbols={name: dict(versioned=False, unversioned=False, base_verified=False) for name in
                ('__vdso_clock_gettime64', '__vdso_clock_gettime', '__vdso_clock_getres', '__vdso_gettimeofday')})
        self.assertEqual(report.validate_inventory(json.dumps(value), 'boot', '2.41'), value)
        with self.assertRaises(ValueError): report.analyze(json.dumps(value).encode(), 'boot', '2.41')
        for change in ('handle', 'mapping', 'symbol', 'base', 'boot', 'bool'):
            bad = deepcopy(value)
            if change == 'handle': bad['handle_base_verified'] = False
            if change == 'mapping': bad['mapping_found'] = False
            if change == 'symbol': bad['symbols'].pop('__vdso_clock_gettime64')
            if change == 'base': bad['symbols']['__vdso_clock_gettime64']['versioned'] = True
            if change == 'boot': bad['after']['boot_id'] = 'different'
            if change == 'bool': bad['symbols']['__vdso_clock_gettime64']['unversioned'] = 0
            with self.subTest(change=change), self.assertRaises(ValueError):
                report.validate_inventory(json.dumps(bad), 'boot', '2.41')

    def test_build_receipt_tampering_and_unavailable_libc_import_stop_before_remote(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stamp = '20261009T231425.767282Z'
            build = root / 'diagnostics' / stamp
            build.mkdir(parents=True)
            (root / 'tools').mkdir()
            (root / 'tools/compare-clocks-native.c').write_text('source')
            (root / 'tools/build-native-clocks.py').write_text('builder')
            elf = 'ELF32 little endian ARM Version5 EABI hard-float ABI /lib/ld-linux-armhf.so.3\n UND __clock_gettime64@GLIBC_2.34'
            files = {'compare-clocks-native.c': 'source', 'compare-clocks-native': 'binary',
                'native-readelf.txt': elf, 'native-disassembly.txt': 'asm', 'build-output.txt': 'passed', 'build.sh': 'script'}
            for name, data in files.items(): (build / name).write_text(data)
            digest = lambda value: hashlib.sha256(value.encode()).hexdigest()
            lock = dict(builder={'image': 'pinned'}, linux={'commit': 'pinned'})
            receipt = dict(schema=1, complete=True, builder=lock['builder'], abi={'linux': lock['linux']},
                source_sha256=digest('source'), producer_sha256=digest('builder'),
                tests=['host-fixtures', 'arm-qemu-fixtures', 'arm-production-abi-assertions'],
                files={name: digest(value) for name, value in files.items()})
            (build / 'build-receipt.json').write_text(json.dumps(receipt))
            with patch.object(host, 'ROOT', root), patch.object(host, 'LOCAL', root), \
                    patch.object(host, 'load', return_value=builder), \
                    patch.object(host.subprocess, 'run', return_value=SimpleNamespace(stdout=elf.encode())) as readelf:
                self.assertEqual(host.verified_build(stamp, lock, root)[0], build)
                readelf.return_value = SimpleNamespace(stdout=b'no matching symbol')
                with self.assertRaisesRegex(ValueError, 'libc does not provide'):
                    host.verified_build(stamp, lock, root)
                (build / 'compare-clocks-native').write_text('changed')
                with self.assertRaisesRegex(ValueError, 'artifact differs'):
                    host.verified_build(stamp, lock, root)

    def test_offline_replay_verifies_original_raw_hash_and_preserves_original_report(self):
        import remote
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stamp = '20261009T231750.335140Z'
            capture = root / 'diagnostics' / stamp
            capture.mkdir(parents=True)
            output = root / 'replay'; output.mkdir()
            data = encode(records(4))
            (capture / 'native-output.ndjson').write_bytes(data)
            (capture / 'before.json').write_text('{"boot_id":"boot"}')
            (capture / 'analysis.json').write_text('original')
            (capture / 'summary.json').write_text(json.dumps(dict(complete=True, operation='comparison',
                observation_validated=True, raw_sha256=hashlib.sha256(data).hexdigest())))
            with patch.dict(report.os.environ, {'NEO_CAPTURE': stamp}), patch.object(report, 'SAMPLES', 4), \
                    patch.object(remote, 'LOCAL', root), patch.object(remote, 'evidence_directory', return_value=output) as destination:
                report.main()
                self.assertEqual((capture / 'analysis.json').read_text(), 'original')
                self.assertEqual(json.loads((output / 'analysis.json').read_text())['samples'], 4)
                destination.reset_mock()
                (capture / 'native-output.ndjson').write_bytes(data + b' ')
                with self.assertRaisesRegex(ValueError, 'hash'):
                    report.main()
                destination.assert_not_called()


if __name__ == '__main__':
    unittest.main()
