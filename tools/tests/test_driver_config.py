"""Kconfig's hidden disabled symbols must not invalidate compile-only matrices."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kernel_checks import check_overrides


class ResolvedConfiguration(unittest.TestCase):
    def test_disabled_hidden_and_explicit_symbols_are_equivalent(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / '.config'
            config.write_text('# CONFIG_SUSPEND is not set\nCONFIG_PM=y\n')
            check_overrides(config, ['CONFIG_SUSPEND=n', 'CONFIG_PM_SLEEP=n', 'CONFIG_PM=y'])

    def test_unexpected_enabled_missing_enabled_and_tristate_mismatch_reject(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / '.config'
            config.write_text('CONFIG_PM_SLEEP=y\nCONFIG_USB_MUSB_HDRC=m\n')
            for setting in ('CONFIG_PM_SLEEP=n', 'CONFIG_SUSPEND=y', 'CONFIG_USB_MUSB_HDRC=y'):
                with self.subTest(setting=setting), self.assertRaises(RuntimeError):
                    check_overrides(config, [setting])
            check_overrides(config, ['CONFIG_USB_MUSB_HDRC=m'])
