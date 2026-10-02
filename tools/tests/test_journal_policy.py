"""Reject misleading journal restoration evidence; exercise actual Armbian guards."""
from copy import deepcopy
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import journal_policy as journal

ROOT = TOOLS.parent
POLICY = {name: (ROOT / 'runtime' / name).read_text() for name in journal.FILES}


def snapshot():
    return dict(boot_id='same', files=deepcopy(POLICY), journal='early kernel\nfirmware',
        units={'systemd-journald.service': {'MainPID': '119', 'ExecMainStartTimestampMonotonic': '6000000'},
               'logrotate.service': {'LoadState': 'loaded', 'ExecStartPre': '', 'ExecStartPost': '',
                                     'ExecStart': '/usr/sbin/logrotate /etc/logrotate.conf'},
               'armbian-ramlog.service': {'LoadState': 'masked'}},
        stores={'/var/log.hdd/journal': {'files': ['old immutable journal']}},
        open_journals=['/var/log/journal/machine/system.journal'])


class Evidence(unittest.TestCase):
    def test_empty_systemd_properties_are_requested_and_retained(self):
        with patch.object(journal, 'command', return_value='ExecStartPre=\nExecStartPost=') as command:
            self.assertEqual(journal.properties('logrotate.service'),
                             {'ExecStartPre': '', 'ExecStartPost': ''})
            self.assertIn('--all', command.call_args.args)

    def test_ordinary_rotation_preserves_evidence(self):
        before = snapshot(); after = deepcopy(before)
        after['journal'] += '\nnew kernel entry'
        journal.validate_policy(after, POLICY)
        journal.validate_continuity(before, after)

    def test_systemd_omitted_empty_arrays_are_allowed_only_for_a_loaded_unit(self):
        value = snapshot()
        del value['units']['logrotate.service']['ExecStartPre']
        del value['units']['logrotate.service']['ExecStartPost']
        journal.validate_policy(value, POLICY)
        value['units']['logrotate.service']['LoadState'] = 'not-found'
        with self.assertRaises(ValueError):
            journal.validate_policy(value, POLICY)

    def test_runtime_only_or_deleted_file_is_not_persistence(self):
        for files in ([], ['/run/log/journal/machine/system.journal'],
                      ['/var/log/journal/machine/system.journal (deleted)']):
            value = snapshot(); value['open_journals'] = files
            with self.assertRaises(ValueError):
                journal.validate_policy(value, POLICY)

    def test_mask_alone_does_not_disable_direct_helper(self):
        for field in ('ExecStartPre', 'ExecStartPost'):
            value = snapshot(); value['units']['logrotate.service'][field] = '/usr/lib/armbian/armbian-ramlog write'
            with self.assertRaises(ValueError):
                journal.validate_policy(value, POLICY)
        value = snapshot(); value['files'][journal.FILES[0]] = 'ENABLED=true\n'
        with self.assertRaises(ValueError):
            journal.validate_policy(value, POLICY)

    def test_reboot_restart_journal_loss_and_displacement_are_failures(self):
        before = snapshot()
        for field in ('boot', 'pid', 'start', 'journal', 'store'):
            after = deepcopy(before)
            if field == 'boot': after['boot_id'] = 'new'
            if field == 'pid': after['units']['systemd-journald.service']['MainPID'] = '384'
            if field == 'start': after['units']['systemd-journald.service']['ExecMainStartTimestampMonotonic'] = '81000000'
            if field == 'journal': after['journal'] = 'later kernel only'
            if field == 'store': after['stores']['/var/log.hdd/journal']['files'].append('moved journal')
            with self.subTest(field=field), self.assertRaises(ValueError):
                journal.validate_continuity(before, after)

    def test_partial_file_update_is_not_a_policy_pass(self):
        for name in POLICY:
            value = snapshot(); value['files'][name] = None
            with self.subTest(name=name), self.assertRaises(ValueError):
                journal.validate_policy(value, POLICY)

    def test_skipped_rotation_is_not_execution_credit(self):
        before = snapshot(); after = deepcopy(before)
        for value in (before, after):
            value['units']['logrotate.service'].update(ExecMainStartTimestampMonotonic='100', ActiveState='inactive')
        with self.assertRaises(ValueError):
            journal.validate_rotation(before, after)
        after['units']['logrotate.service']['ExecMainStartTimestampMonotonic'] = '200'
        journal.validate_rotation(before, after)
        after['units']['logrotate.service']['ActiveState'] = 'failed'
        with self.assertRaises(ValueError):
            journal.validate_rotation(before, after)

    def test_pinned_helpers_stop_before_any_operations_with_disabled_policy(self):
        base = ROOT / '.local/sources/armbian/packages/bsp/common/usr/lib/armbian'
        if not base.exists():
            self.skipTest('Prepared locked Armbian source is not available')
        for name in ('armbian-ramlog', 'armbian-truncate-logs'):
            source = (base / name).read_text()
            guard = '[ "$ENABLED" != true ] && exit 0'
            self.assertEqual(source.count(guard), 1)
            # Execute the actual pre-operation prefix, replacing only its fixed
            # config path. The marker is a negative control, never real helper I/O.
            prefix = source[:source.index(guard) + len(guard)]
            with tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / 'armbian-ramlog'
                script = prefix.replace('/etc/default/armbian-ramlog', shlex.quote(str(config)))
                script += '\nprintf "REACHED_OPERATIONS\\n"\n'
                for enabled, expected in ((True, 'REACHED_OPERATIONS\n'), (False, '')):
                    config.write_text('ENABLED=true\n' if enabled else POLICY[journal.FILES[0]])
                    result = subprocess.run(['bash', '-c', script], text=True, capture_output=True, check=True)
                    self.assertEqual(result.stdout, expected, name)


if __name__ == '__main__':
    unittest.main()
