"""Target selection and bounded perf sampling, without access to the device."""
import importlib.util
from pathlib import Path
import unittest

source = Path(__file__).resolve().parents[1] / 'profile-governor.py'
spec = importlib.util.spec_from_file_location('profile_governor', source)
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class GovernorSampling(unittest.TestCase):
    def test_exact_unique_worker_required(self):
        target = dict(pid=66, comm='sugov:0', start_ticks=135)
        self.assertEqual(profile.worker({'66': target, '99': dict(comm='unrelated')}), target)
        for rows in ({}, {'66': dict(comm='sugov:1')}, {'66': target, '67': target}):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                profile.worker(rows)

    def test_kernel_only_targeted_bounded_sampling(self):
        args = profile.record_command(Path('/tmp/perf'), 66, 30, Path('/tmp/perf.data'))
        for option, value in (('-e', 'cpu-clock:k'), ('-F', '99'), ('-m', '64'), ('-p', '66')):
            self.assertEqual(args[args.index(option) + 1], value)
        self.assertEqual(args[-3:], ['--', '/usr/bin/sleep', '30'])
        self.assertNotIn('-a', args)
        self.assertNotIn('-g', args)
        self.assertIn('--no-buildid-cache', args)

    def test_bad_duration_or_identity_rejected(self):
        for pid, seconds in ((0, 30), (-1, 30), (66, 9), (66, 61)):
            with self.subTest(pid=pid, seconds=seconds), self.assertRaises(ValueError):
                profile.record_command(Path('/tmp/perf'), pid, seconds, Path('/tmp/perf.data'))

    def test_empty_or_failed_report_cannot_pass(self):
        for report in ('', '# Samples: 0 of event cpu-clock:k', 'Error: cannot load data'):
            with self.subTest(report=report), self.assertRaises(ValueError):
                profile.require_samples(report)
        profile.require_samples('# header\n# Samples: 1K of event cpu-clock:k\n')
