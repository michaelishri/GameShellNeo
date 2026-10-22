"""Host transport and checkpoint failure evidence; no network or block devices."""
import contextlib
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from dev_store_transport import load_hardware

specification = importlib.util.spec_from_file_location('checkpoint_dev_store_test', TOOLS / 'checkpoint-dev-store.py')
checkpoint = importlib.util.module_from_spec(specification)
specification.loader.exec_module(checkpoint)


class HardwareContextTests(unittest.TestCase):
    names = ('private_config', 'host_timing', 'forward_socket', 'socket_observation', 'remote')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.old_directory = Path.cwd()
        self.saved = {name: sys.modules.pop(name, None) for name in self.names}
        self.addCleanup(self.restore_context)
        (self.root / '.git').write_text('gitdir: preserved-checkout\n')
        tools = self.root / 'tools'
        tools.mkdir()
        (self.root / '.env').write_text('private fixture data\n')
        for name in self.names:
            (tools / (name + '.py')).write_text('ORIGIN = __file__\n')
        (tools / 'private_config.py').write_text('''from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load_env(path):return {'fixture':Path(path).read_text()}
''')
        (tools / 'remote.py').write_text('''from pathlib import Path
from private_config import load_env
ROOT=Path(__file__).resolve().parents[1]
LOCAL=ROOT/'.local'
''')

    def restore_context(self):
        os.chdir(self.old_directory)
        for name, module in self.saved.items():
            sys.modules.pop(name, None)
            if module is not None:
                sys.modules[name] = module

    def test_explicit_context_loads_original_helpers_and_configuration(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            remote, config = load_hardware(self.root)
        self.assertEqual(remote.ROOT, self.root)
        self.assertEqual(config, {'fixture': 'private fixture data\n'})
        self.assertEqual(Path.cwd(), self.root)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual((self.root / '.env').read_text(), 'private fixture data\n')

    def test_original_private_env_symlink_is_preserved(self):
        target = self.root / 'canonical.env'
        target.write_text('canonical fixture data\n')
        (self.root / '.env').unlink()
        (self.root / '.env').symlink_to(target)
        _, config = load_hardware(self.root)
        self.assertEqual(config['fixture'], target.read_text())
        self.assertTrue((self.root / '.env').is_symlink())

    def test_existing_wrong_module_origin_is_rejected(self):
        module = types.ModuleType('private_config')
        module.__file__ = __file__
        sys.modules['private_config'] = module
        with self.assertRaisesRegex(ValueError, 'different origin'):
            load_hardware(self.root)
        self.assertEqual(Path.cwd(), self.old_directory)

    def test_explicit_checkout_and_real_helper_paths_are_required(self):
        with self.assertRaisesRegex(ValueError, 'explicitly'):
            load_hardware(None)
        linked = self.root / 'linked'
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'real Git checkout'):
            load_hardware(linked)
        source = self.root / 'tools/private_config.py'
        moved = self.root / 'real-private.py'
        source.rename(moved)
        source.symlink_to(moved)
        with self.assertRaisesRegex(ValueError, 'existing real file'):
            load_hardware(self.root)

    def test_missing_checkout_marker_is_rejected(self):
        (self.root / '.git').unlink()
        with self.assertRaisesRegex(ValueError, 'real Git checkout'):
            load_hardware(self.root)


class Channel:
    def __init__(self, payload, *, interrupted=False):
        middle = max(1, len(payload) // 2)
        self.chunks = [payload[:middle], payload[middle:]]
        self.stderr = [b'original stream diagnostic\n']
        self.interrupted = interrupted
        self.reads = 0
        self.closed = False

    def settimeout(self, _):
        pass

    def exec_command(self, command):
        self.command = command

    def shutdown_write(self):
        pass

    def recv_ready(self):
        return bool(self.chunks)

    def recv(self, _):
        self.reads += 1
        if self.interrupted and self.reads == 2:
            raise OSError('original transport interruption')
        return self.chunks.pop(0)

    def recv_stderr_ready(self):
        return bool(self.stderr)

    def recv_stderr(self, _):
        return self.stderr.pop(0)

    def exit_status_ready(self):
        return not self.chunks

    def recv_exit_status(self):
        return 0

    def close(self):
        self.closed = True


class CheckpointStreamTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.raw = bytes(range(256)) * 32
        self.packed = gzip.compress(self.raw, mtime=0)
        self.plan = dict(checkpoint='checkpoint-fixture', boot_id='d0b799de-3241-481c-953a-acd064cf5467',
                         remote='/var/lib/fixture/checkpoint-fixture', regions={
                             'prefix': dict(file='prefix.img.gz', offset_bytes=0, raw_bytes=len(self.raw), partition=None)})

    def invoke(self, *, packed=None, digest=None, interrupted=False):
        packed = self.packed if packed is None else packed
        channel = Channel(packed, interrupted=interrupted)
        self.channel = channel
        client = types.SimpleNamespace(get_transport=lambda: types.SimpleNamespace(open_session=lambda **_: channel))
        receipt = dict(name='prefix', offset_bytes=0, raw_bytes=len(self.raw),
                       raw_sha256=digest or hashlib.sha256(self.raw).hexdigest(),
                       gzip_bytes=len(packed), gzip_sha256=hashlib.sha256(packed).hexdigest(),
                       checkpoint=self.plan['checkpoint'], boot_id=self.plan['boot_id'], source_unmounted=True)
        remote = types.SimpleNamespace(run=lambda *_args, **_kwargs: checkpoint.json_bytes(receipt),
                                       python_command=lambda *_args: dict(command='fixture'))
        with contextlib.redirect_stdout(io.StringIO()):
            return checkpoint.stream_region(remote, client, self.plan, 'prefix', self.directory)

    def test_complete_gzip_and_raw_hashes_and_reserved_prefix_are_verified(self):
        region, prefix = self.invoke()
        self.assertTrue(region['verified_full_decompressed'])
        self.assertEqual((self.directory / region['file']).read_bytes(), self.packed)
        self.assertEqual(prefix, (self.raw[:512].hex(), hashlib.sha256(self.raw[512:]).hexdigest()))
        self.assertFalse((self.directory / 'prefix.img.gz.part').exists())
        self.assertTrue(self.channel.closed)

    def test_decompressed_hash_failure_retains_original_partial_and_stderr(self):
        with self.assertRaisesRegex(ValueError, 'Full decompressed'):
            self.invoke(digest='0' * 64)
        self.assertEqual((self.directory / 'prefix.img.gz.part').read_bytes(), self.packed)
        self.assertEqual((self.directory / 'prefix-stderr.txt').read_bytes(), b'original stream diagnostic\n')
        self.assertTrue((self.directory / 'prefix-source.json').exists())
        self.assertFalse((self.directory / 'prefix.img.gz').exists())
        self.assertFalse((self.directory / 'prefix-verified.json').exists())

    def test_transport_failure_preserves_received_bytes_and_never_repeats(self):
        with self.assertRaisesRegex(OSError, 'original transport'):
            self.invoke(interrupted=True)
        self.assertEqual((self.directory / 'prefix.img.gz.part').read_bytes(), self.packed[:len(self.packed) // 2])
        self.assertTrue((self.directory / 'prefix-stderr.txt').exists())
        self.assertTrue(self.channel.closed)
        with self.assertRaises(FileExistsError):
            self.invoke()
        self.assertFalse(hasattr(self.channel, 'command'))

    def test_truncated_gzip_cannot_create_a_verified_backup(self):
        with self.assertRaises((EOFError, OSError)):
            self.invoke(packed=self.packed[:-9])
        self.assertTrue((self.directory / 'prefix.img.gz.part').exists())
        self.assertFalse((self.directory / 'prefix-verified.json').exists())

    def test_saved_remote_programs_compile_without_executing_actions(self):
        for name in ('COMMON', 'ADMISSION', 'STREAM', 'FINALIZE'):
            with self.subTest(name=name):
                scope = {'__name__': 'compile_only'}
                exec(compile(getattr(checkpoint, name), name, 'exec'), scope)
                self.assertTrue(callable(scope['identity']))
        scope = {'__name__': 'compile_only'}
        exec(checkpoint.COMMON, scope)
        mounts = self.directory / 'mountinfo'
        mounts.write_text('36 25 179:3 / /mnt/store\\040alias rw - ext4 /dev/mmcblk0p3 rw,noatime\n')
        self.assertEqual(scope['mounts'](mounts)[0]['point'], '/mnt/store alias')


class CheckpointPlanningTests(unittest.TestCase):
    def test_output_reuse_symlinks_and_relative_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local = root / '.local'
            local.mkdir()
            boot_id = 'd0b799de-3241-481c-953a-acd064cf5467'
            with mock.patch.object(checkpoint, 'ROOT', root), \
                    mock.patch.object(checkpoint.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=16 * 1024**3)):
                with self.assertRaisesRegex(ValueError, 'absolute'):
                    checkpoint.checkpoint_plan(boot_id, Path('relative'))
                plan, output = checkpoint.checkpoint_plan(boot_id, local / 'fresh')
                self.assertEqual(plan['state'], 'planned-not-yet-submitted')
                self.assertEqual(json.loads((output / 'planned.json').read_bytes()), plan)
                with self.assertRaisesRegex(ValueError, 'preserve previous'):
                    checkpoint.checkpoint_plan(boot_id, output)
                (local / 'linked').symlink_to(output, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, 'preserve previous'):
                    checkpoint.checkpoint_plan(boot_id, local / 'linked')


class CheckpointAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.scope = {'__name__': 'admission_tests'}
        exec(checkpoint.COMMON, self.scope)

    def mbr(self):
        data = bytearray(512)
        data[440:444] = bytes.fromhex('81b6dab9')
        data[510:] = b'\x55\xaa'
        for index, name in enumerate(('boot', 'recovery', 'store')):
            start = 446 + index * 16
            part = checkpoint.PARTITIONS[name]
            data[start + 4] = 14 if index == 0 else 131
            data[start + 8:start + 12] = part['start_sector'].to_bytes(4, 'little')
            data[start + 12:start + 16] = (part['bytes'] // 512).to_bytes(4, 'little')
        return data

    def test_actual_fat16_mbr_is_admitted_and_other_geometry_is_rejected(self):
        value = {'partitions': checkpoint.PARTITIONS}
        self.scope['verify_mbr'](self.mbr(), value)
        for name, offset in (('FAT32 type', 450), ('changed p3 start', 486),
                             ('changed p3 length', 490), ('changed disk ID', 440), ('fourth partition', 494)):
            with self.subTest(name=name):
                changed = self.mbr()
                changed[offset] ^= 1
                with self.assertRaises(ValueError):
                    self.scope['verify_mbr'](changed, value)

    def test_missing_mount_in_private_namespace_is_safe_but_aliases_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, records in ((1, '36 25 179:3 / /mnt/neo-devstore rw - ext4 /dev/mmcblk0p3 rw\n'),
                                   (2, '25 0 179:2 / / rw - ext4 /dev/mmcblk0p2 rw\n')):
                process = root / str(index)
                (process / 'ns').mkdir(parents=True)
                (process / 'ns/mnt').symlink_to('/namespace/' + str(index))
                (process / 'mountinfo').write_text(records)
            self.scope['other_mounts']({'179:3': '/mnt/neo-devstore'}, mounted=True, process_root=root)
            (root / '2/mountinfo').write_text('37 25 179:3 /subtree /elsewhere rw - ext4 /dev/mmcblk0p3 rw\n')
            with self.assertRaisesRegex(ValueError, 'alias'):
                self.scope['other_mounts']({'179:3': '/mnt/neo-devstore'}, mounted=True, process_root=root)
            with self.assertRaisesRegex(ValueError, 'remains mounted'):
                self.scope['other_mounts']({'179:3': '/mnt/neo-devstore'}, mounted=False, process_root=root)

    def test_successful_remain_after_exit_is_terminal_but_live_or_unresolved_units_are_rejected(self):
        complete = dict(ActiveState='active', SubState='exited', Result='success', MainPID='0', Job='',
                        ExecMainPID='123', ExecMainCode='1', ExecMainStatus='0')
        self.assertTrue(self.scope['terminal_unit'](complete))
        for changes in ({'MainPID': '456'}, {'Job': '5'}, {'ExecMainPID': '0'}, {'ExecMainCode': '0'},
                        {'ExecMainStatus': '1'}, {'Result': 'exit-code'}, {'SubState': 'running'},
                        {'ActiveState': 'activating'}):
            with self.subTest(changes=changes):
                self.assertFalse(self.scope['terminal_unit'](dict(complete, **changes)))

    def test_private_regular_settings_are_pinned_without_reading_symlink_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            store = base / 'store'
            root = store / 'systems/diag25/root'
            expected = {'etc/private.conf': b'private configuration\n', 'root/.ssh/private-key': b'private fixture key\n',
                        'home/owner/.settings': b'owner state\n', 'var/lib/fixture/state': b'persistent state\n'}
            for relative, data in expected.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                path.write_bytes(data)
                path.chmod(0o600)
            outside = base / 'outside'
            outside.mkdir()
            (outside / 'never-read').write_bytes(b'outside settings scope\n')
            (root / 'home/escape').symlink_to(outside, target_is_directory=True)
            (root / 'etc/escape').symlink_to(outside / 'never-read')
            (root / 'etc/dangling').symlink_to(base / 'missing')
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                pins, summary = self.scope['settings_files'](store, ['diag25'])
            self.assertEqual(pins, {'systems/diag25/root/' + name: hashlib.sha256(data).hexdigest()
                                    for name, data in expected.items()})
            self.assertEqual(summary['scope'], ['etc', 'root', 'home', 'var/lib'])
            self.assertEqual(summary['files'], len(expected))
            self.assertEqual(summary['bytes'], sum(map(len, expected.values())))
            self.assertEqual(summary['releases']['diag25']['symlinks_skipped'], 3)
            self.assertEqual(output.getvalue(), '')

    def test_missing_scopes_and_symlink_scope_are_skipped_and_special_objects_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            store = base / 'store'
            root = store / 'systems/diag27/root'
            (root / 'etc').mkdir(parents=True)
            outside = base / 'outside'
            outside.mkdir()
            (outside / 'outside-file').write_text('do not include\n')
            (root / 'home').symlink_to(outside, target_is_directory=True)
            pins, summary = self.scope['settings_files'](store, ['diag27'])
            self.assertEqual(pins, {})
            self.assertEqual(summary['releases']['diag27']['symlinks_skipped'], 1)
            os.mkfifo(root / 'etc/unsafe-fifo')
            with self.assertRaisesRegex(ValueError, 'non-regular'):
                self.scope['settings_files'](store, ['diag27'])


if __name__ == '__main__':
    unittest.main()
