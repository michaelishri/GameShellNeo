"""A directory label is insufficient clock provenance; reject before arming."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import development_clock as dc
import clock_deployment as cd
from test_clock_deployment import contract as original_contract, snapshot as original_snapshot


def contract():
    c = original_contract()
    image = dict(board='gameshellneo-cpi31', version='test', kernel=c['kernel'],
                 root_partuuid='12345678-02', sources={'instrumented': True})
    image_raw = (json.dumps(image, indent=1) + '\n').encode()
    d = dict(schema=1, operation='development-directory-clock-admission', slot='diag27',
        store_partuuid='12345678-03', store_uuid='aabbccdd-1111-2222-3333-abcdefabcdef',
        card_cid='ab' * 16, source_image_sha256='12' * 32, source_manifest_sha256=dc.digest(image_raw),
        source_manifest_text=image_raw.decode(), image=image,
        adapter_files={name: '23' * 32 for name in dc.ADAPTERS}, reader_receipt_sha256='34' * 32,
        reader_original_linux={'localversion': '-old-reader'}, offline_runtime_boot_id='historical',
        pm_admission=False, clock_health_qualified=False)
    release = dict(schema=1, board=image['board'], slot=d['slot'], kernel=c['kernel'],
        store_partuuid=d['store_partuuid'], source_image_sha256=d['source_image_sha256'],
        source_manifest_sha256=d['source_manifest_sha256'], source_fstab_sha256=dc.digest(b'source fstab'),
        immutable_files={'usr/local/lib/gameshellneo/battery_guard.py': dc.digest(b'original guard')})
    deployment = dict(image, deployment='development-directory', slot=d['slot'],
        source_image_sha256=d['source_image_sha256'], source_manifest_sha256=d['source_manifest_sha256'],
        source_fstab_sha256=release['source_fstab_sha256'], root_partuuid=d['store_partuuid'])
    c['image_sha256'] = release['deployment_manifest_sha256'] = dc.digest(dc.json_bytes(deployment))
    release['immutable_files']['etc/gameshellneo/image.json'] = c['image_sha256']
    for item in c['runtime'].values():
        p = item['path'].lstrip('/')
        release['immutable_files']['usr/' + p if p.startswith('lib/') else p] = item['sha256']
    d['release'] = release
    d['release_sha256'] = dc.digest(dc.json_bytes(release))
    c['development'] = d
    return c, deployment


class ReaderAbiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.archive = Path(temporary.name) / 'linux.tar.xz'
        self.files = {name: name.encode() for name in dc.READER_ABI_FILES}
        self.digests = {name: dc.digest(raw) for name, raw in self.files.items()}

    def write_archive(self):
        with tarfile.open(self.archive, 'w:xz') as archive:
            for name, raw in self.files.items():
                member = tarfile.TarInfo('linux-6.18.54/' + name)
                member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))

    def test_exact_ten_sources_are_read_and_verified(self):
        self.assertEqual(len(self.digests), 10)
        self.write_archive()
        self.assertEqual(dc.verify_reader_abi(self.digests, self.archive, '6.18.54'), self.digests)

    def test_empty_partial_extra_or_malformed_receipt_refused_before_archive_read(self):
        incomplete = [{}, None, [], list(self.digests)]
        incomplete.extend({k: v for k, v in self.digests.items() if k != missing}
                          for missing in self.digests)
        incomplete.append(dict(self.digests, unexpected='a' * 64))
        for value in incomplete:
            with self.subTest(value=value), patch.object(dc.tarfile, 'open') as archive:
                with self.assertRaisesRegex(ValueError, 'exact ten'):
                    dc.verify_reader_abi(value, self.archive, '6.18.54')
                archive.assert_not_called()
        for value in ('', 'A' * 64, '0' * 63, None, 0):
            wrong = dict(self.digests)
            wrong[dc.READER_ABI_FILES[0]] = value
            with self.subTest(digest=value), patch.object(dc.tarfile, 'open') as archive:
                with self.assertRaisesRegex(ValueError, 'digest'):
                    dc.verify_reader_abi(wrong, self.archive, '6.18.54')
                archive.assert_not_called()

    def test_complete_receipt_with_changed_header_hash_is_refused(self):
        self.write_archive()
        wrong = dict(self.digests)
        wrong[dc.READER_ABI_FILES[0]] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'headers differ'):
            dc.verify_reader_abi(wrong, self.archive, '6.18.54')

    def test_missing_archive_header_is_refused_even_with_complete_receipt(self):
        del self.files[dc.READER_ABI_FILES[-1]]
        self.write_archive()
        with self.assertRaisesRegex(ValueError, 'headers differ'):
            dc.verify_reader_abi(self.digests, self.archive, '6.18.54')


class ContractTests(unittest.TestCase):
    def test_distinct_original_and_deployment_manifests_and_reader_version(self):
        c, _ = contract()
        dc.validate_development_contract(c)
        self.assertNotEqual(c['image_sha256'], c['development']['source_manifest_sha256'])
        self.assertEqual(c['development']['reader_original_linux']['localversion'], '-old-reader')
        self.assertFalse(c['development']['pm_admission'])

    def test_forged_or_inconsistent_contract_is_refused(self):
        for key, value in [('slot', '../diag27'), ('slot', 'recovery'), ('store_partuuid', '12345678-02'),
            ('card_cid', 'wrong'), ('store_uuid', 'wrong'), ('release_sha256', '0' * 64),
            ('source_manifest_sha256', '0' * 64), ('source_image_sha256', '0' * 64),
            ('source_manifest_text', '{}'), ('adapter_files', {}), ('pm_admission', True),
            ('clock_health_qualified', True)]:
            c, _ = contract(); c['development'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                dc.validate_development_contract(c)
        c, _ = contract(); c['runtime']['libc']['sha256'] = 'f' * 64
        with self.assertRaises(ValueError):
            dc.validate_development_contract(c)

    def test_original_image_snapshot_guard_still_refuses_directory_manifest(self):
        c = original_contract()
        s = original_snapshot(c)
        s['image_sha256'] = contract()[0]['image_sha256']
        with self.assertRaisesRegex(ValueError, 'image_sha256'):
            cd.validate_snapshot(s, c)

    def test_staged_adapter_has_no_unprovided_host_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            for name in (*dc.ADAPTERS, 'clock_boundary.py', 'clock_provenance.py', 'clock_deployment.py'):
                (p / name).write_bytes((ROOT / 'tools' / name).read_bytes())
            value, _ = contract()
            (p / 'contract.json').write_text(json.dumps(value))
            source = ('import sys,json;sys.path.insert(0,sys.argv[1]);import development_clock as d;'
                      'd.validate_development_contract(json.load(open(sys.argv[1]+"/contract.json")))')
            subprocess.run([sys.executable, '-I', '-S', '-B', '-c', source, directory],
                           check=True, capture_output=True, timeout=10)

    def test_old_raw_host_requires_explicit_complete_adapter_before_any_ssh(self):
        spec = importlib.util.spec_from_file_location('development_test_host', ROOT / 'tools/check-clock-boundary.py')
        host = importlib.util.module_from_spec(spec); spec.loader.exec_module(host)
        c, _ = contract()
        with patch.object(host, 'run') as run:
            for extras, runner in [({}, 'capture-development-clock.py'), ({'x': Path('/unused')}, 'other'),
                                   ({'x': Path('/unused')}, 'capture-development-clock.py'),
                                   ({}, 'capture-clock-boundary.py')]:
                with self.subTest(runner=runner), self.assertRaises(ValueError):
                    host.execute(None, ROOT, c, ROOT, extra_files=extras, runner=runner)
            run.assert_not_called()

    def test_large_realistic_contract_retains_all_evidence_with_original_bound(self):
        spec = importlib.util.spec_from_file_location('development_contract_host', ROOT / 'tools/check-clock-boundary.py')
        host = importlib.util.module_from_spec(spec); spec.loader.exec_module(host)
        value = {'immutable_files': {'usr/' + str(i) + '/path': 'a' * 64 for i in range(24000)}}
        self.assertGreater(len(json.dumps(value, indent=2).encode()), 2 * 1024 * 1024)
        raw = host.contract_bytes(value)
        self.assertLessEqual(len(raw), 2 * 1024 * 1024)
        self.assertEqual(json.loads(raw), value)
        with self.assertRaisesRegex(ValueError, '2 MiB'):
            host.contract_bytes({'too_large': 'x' * (2 * 1024 * 1024)})

    def test_complete_staging_path_transfers_the_exact_bounded_large_contract(self):
        spec = importlib.util.spec_from_file_location('development_staging_host', ROOT / 'tools/check-clock-boundary.py')
        host = importlib.util.module_from_spec(spec); spec.loader.exec_module(host)
        c, _ = contract()
        r = c['development']['release']
        r['immutable_files'].update({'usr/' + str(i) + '/path': 'a' * 64 for i in range(23000)})
        c['development']['release_sha256'] = dc.digest(dc.json_bytes(r))
        self.assertGreater(len(json.dumps(c, indent=2).encode()), 2 * 1024 * 1024)
        stage, staged = '/tmp/gameshellneo-clock-boundary.12345678', {}
        sftp = Mock()
        sftp.__enter__ = Mock(return_value=sftp); sftp.__exit__ = Mock(return_value=False)
        sftp.open.side_effect = lambda path, mode: io.BytesIO(staged[path])
        sftp.stat.side_effect = FileNotFoundError
        client = Mock(); client.open_sftp.return_value = sftp
        terminal = {'terminal': True}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); reader = p / 'reader'; capture = p / 'capture'
            (reader / 'tools').mkdir(parents=True); capture.mkdir()
            for name in cd.FILES:
                target = reader / name if name.endswith('.so') else reader / 'tools' / name
                target.write_bytes(name.encode()); c['files'][name] = dc.sha(target)
            extras = {name: ROOT / 'tools' / name for name in dc.ADAPTERS}
            c['development']['adapter_files'] = {name: dc.sha(path) for name, path in extras.items()}

            def upload(sftp, source, target):
                staged[target] = Path(source).read_bytes()

            with patch.object(host, 'run', return_value=stage.encode()), patch.object(host, 'upload', side_effect=upload), \
                    patch.object(host, 'supervise', return_value=terminal) as supervise:
                self.assertEqual(host.execute(client, reader, c, capture, extra_files=extras,
                    runner='capture-development-clock.py'), terminal)
                self.assertEqual(staged[stage + '/contract.json'], (capture / 'contract.json').read_bytes())
                self.assertEqual(staged[stage + '/contract.json'], host.contract_bytes(c))
                self.assertLessEqual(len(staged[stage + '/contract.json']), 2 * 1024 * 1024)
                supervise.assert_called_once_with(client, unittest.mock.ANY, stage, capture,
                                                  runner='capture-development-clock.py')

    def test_offline_failure_never_loads_transport_or_contacts_device(self):
        spec = importlib.util.spec_from_file_location('development_clock_entry', ROOT / 'tools/check-development-clock.py')
        host = importlib.util.module_from_spec(spec); spec.loader.exec_module(host)
        with tempfile.TemporaryDirectory() as d:
            argv = ['entry', '--image-checkout', d, '--reader-build', d, '--runtime-capture', d,
                    '--release-manifest', d, '--boot-id', 'wrong', '--card-cid', 'wrong',
                    '--store-uuid', 'wrong', '--apply', '--hardware-checkout', d]
            with patch.object(sys, 'argv', argv), patch.object(host, 'offline_inputs', side_effect=ValueError('stale')), \
                    patch.object(host, 'load_hardware') as load:
                with self.assertRaisesRegex(ValueError, 'stale'):
                    host.main()
                load.assert_not_called()


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Path(self.temporary.name) / 'store'
        self.directory = self.store / 'systems/diag27'
        self.root = self.directory / 'root'
        self.root.mkdir(parents=True)
        self.c, deployment = contract()
        self.d = self.c['development']
        entries = {'release.json': dc.json_bytes(self.d['release']),
            'source-image.json': self.d['source_manifest_text'].encode(), 'source-fstab': b'source fstab',
            'root/etc/gameshellneo/image.json': dc.json_bytes(deployment),
            'root/etc/gameshellneo/development-slot': f'schema=1\nid=diag27\nkernel={self.c["kernel"]}\n'.encode(),
            'root/usr/local/lib/gameshellneo/battery_guard.py': b'original guard'}
        for relative, raw in entries.items():
            p = self.directory / relative; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
        (self.store / 'RELEASES.JSON').write_text(json.dumps({'diag27': {'manifest_sha256': self.d['release_sha256']}}))
        self.marker = entries['root/etc/gameshellneo/development-slot']
        self.cmdline = f'root=PARTUUID=12345678-03 neo.dev=1 neo.slot=diag27 neo.store=PARTUUID=12345678-03'
        self.cid = self.d['card_cid']
        self.uuid = self.d['store_uuid']
        n = self.store.stat().st_dev
        self.mount = dict(target=str(self.store), source='/dev/mmcblk0p3', fstype='ext4', fsroot='/',
                          **{'maj:min': f'{os.major(n)}:{os.minor(n)}'})
        self.root_mount = dict(target='/', fstype='ext4', fsroot='/systems/diag27/root',
                               **{'maj:min': self.mount['maj:min']})
        bounded = dc.bounded

        def read(path, maximum=2 * 1024 * 1024):
            values = {'/sys/class/block/mmcblk0/device/cid': self.cid.encode(),
                      '/proc/cmdline': self.cmdline.encode(), '/run/gameshellneo-development-slot': self.marker}
            return values[str(path)] if str(path) in values else bounded(path, maximum)

        def command(*args):
            if args[0] == 'findmnt':
                return json.dumps({'filesystems': [self.mount if args[3] == str(self.store) else self.root_mount]})
            return self.d['store_partuuid'] if args[2] == 'PARTUUID' else self.uuid

        self.addCleanup(patch.stopall)
        patch.object(dc, 'bounded', side_effect=read).start()
        patch.object(dc, 'command', side_effect=command).start()
        patch.object(Path, 'is_mount', return_value=True).start()

    def observe(self, root=None):
        return dc.deployment_snapshot(self.c, store=self.store, root=root or self.root)

    def test_actual_directory_inode_and_exact_sources_are_observed(self):
        result = self.observe()
        self.assertEqual(result['root_inode'], self.root.stat().st_ino)
        self.assertEqual(result['source_image_sha256'], self.d['source_image_sha256'])
        self.assertFalse(result['clock_health_qualified'])

    def test_other_directory_inode_is_refused(self):
        other = Path(self.temporary.name) / 'other'; other.mkdir()
        with self.assertRaisesRegex(ValueError, 'actual root'):
            self.observe(other)

    def test_partial_or_aliased_store_and_root_mounts_are_refused(self):
        for key, value in [('fsroot', '/systems/diag27/root'), ('source', '/dev/loop0'),
                           ('fstype', 'overlay'), ('maj:min', '999:9')]:
            old = self.mount[key]; self.mount[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.observe()
            self.mount[key] = old
        self.root_mount['fsroot'] = '/systems/other/root'
        with self.assertRaises(ValueError):
            self.observe()

    def test_card_filesystem_and_duplicate_boot_arguments_are_refused(self):
        for name, value in [('cid', 'cd' * 16), ('uuid', 'different'),
                            ('cmdline', self.cmdline + ' neo.slot=other'), ('marker', b'other')]:
            old = getattr(self, name); setattr(self, name, value)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.observe()
            setattr(self, name, old)

    def test_changed_release_source_deployment_marker_guard_or_catalog_is_refused(self):
        paths = [self.directory / p for p in ('release.json', 'source-image.json', 'source-fstab',
            'root/etc/gameshellneo/image.json', 'root/etc/gameshellneo/development-slot',
            'root/usr/local/lib/gameshellneo/battery_guard.py')]
        paths.append(self.store / 'RELEASES.JSON')
        for path in paths:
            raw = path.read_bytes(); path.write_bytes(b'{}')
            with self.subTest(path=path), self.assertRaises((ValueError, KeyError)):
                self.observe()
            path.write_bytes(raw)

    def test_symlink_metadata_and_root_alias_are_refused(self):
        p = self.directory / 'source-image.json'; raw = p.read_bytes(); p.unlink()
        target = Path(self.temporary.name) / 'source'; target.write_bytes(raw); p.symlink_to(target)
        with self.assertRaises(ValueError):
            self.observe()


if __name__ == '__main__':
    unittest.main()
