"""Private journal summaries retain attribution without copying logged source."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('journal_volume',
    Path(__file__).resolve().parents[1]/'report-journal-volume.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class JournalVolumeTests(unittest.TestCase):
    def test_source_fragments_binary_messages_and_private_fields(self):
        records = [dict(SYSLOG_IDENTIFIER='sudo', MESSAGE='COMMAND=python3 -B -c secret source'),
                   dict(SYSLOG_IDENTIFIER='sudo', MESSAGE='source continuation'),
                   dict(_COMM='kernel', MESSAGE=[65, 255]),
                   dict(SYSLOG_IDENTIFIER='private identifier', MESSAGE='private message')]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'capture'; path.write_text(''.join(json.dumps(r)+'\n' for r in records))
            value = report.summarize(path)
            self.assertEqual(value['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(value['entries'], 4)
        self.assertEqual(value['sudo_command_records'], 1)
        self.assertEqual(value['sudo_inline_python_commands'], 1)
        self.assertEqual(value['groups']['kernel']['message_bytes'], 2)
        self.assertEqual(value['groups']['sudo']['entries'], 2)
        for word in ('secret', 'private identifier', 'private message', 'continuation\"'):
            self.assertNotIn(word, json.dumps(value))

    def test_empty_malformed_and_oversized_inputs_fail_without_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'capture'
            for raw in (b'', b'secret invalid json', b'[]', b'{"MESSAGE":[999]}',
                        b'{"MESSAGE":{}}', b'x' * (report.MAX_LINE + 1)):
                path.write_bytes(raw)
                with self.assertRaises(ValueError) as error:
                    report.summarize(path)
                self.assertNotIn('secret', str(error.exception))


if __name__ == '__main__':
    unittest.main()
