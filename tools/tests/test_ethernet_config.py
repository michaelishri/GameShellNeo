"""Reject comparisons that accidentally remove the device's recovery network."""
import importlib.util
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('ethernet_config', TOOLS/'check-ethernet-config.py')
ethernet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ethernet)


class EthernetConfig(unittest.TestCase):
    def setUp(self):
        self.before = {name: 'y' for name in ethernet.KEEP}
        self.before.update(CONFIG_BRCMFMAC='m', CONFIG_USB_U_ETHER='m', CONFIG_USB_F_ECM='m',
                           CONFIG_SUN4I_EMAC='y', CONFIG_STMMAC_ETH='y')
        self.after = {name: value for name, value in self.before.items()
                      if name not in ('CONFIG_SUN4I_EMAC', 'CONFIG_STMMAC_ETH')}

    def test_recovery_paths_preserved_with_both_controllers_removed(self):
        changes = ethernet.compare_configs(self.before, self.after)
        self.assertEqual(changes, {'CONFIG_SUN4I_EMAC': ['y', 'n'], 'CONFIG_STMMAC_ETH': ['y', 'n']})

    def test_loss_or_build_mode_change_in_any_recovery_dependency_fails(self):
        for name in ethernet.KEEP:
            for value in ('n', 'm' if self.after[name] == 'y' else 'y'):
                with self.subTest(name=name, value=value):
                    after = dict(self.after, **{name: value})
                    with self.assertRaisesRegex(ValueError, 'Required network support changed'):
                        ethernet.compare_configs(self.before, after)

    def test_disabled_baseline_recovery_path_is_not_accepted(self):
        for name in ethernet.KEEP:
            with self.subTest(name=name):
                before = dict(self.before); after = dict(self.after)
                before.pop(name); after.pop(name)
                with self.assertRaisesRegex(ValueError, 'Required network support changed'):
                    ethernet.compare_configs(before, after)

    def test_missing_baseline_controller_or_incomplete_removal_fails(self):
        for name in ('CONFIG_SUN4I_EMAC', 'CONFIG_STMMAC_ETH'):
            with self.subTest(name=name):
                before = dict(self.before); before.pop(name)
                with self.assertRaisesRegex(ValueError, 'Expected enabled baseline'):
                    ethernet.compare_configs(before, self.after)
                for value in ('y', 'm'):
                    after = dict(self.after, **{name: value})
                    with self.assertRaisesRegex(ValueError, 'Expected enabled baseline'):
                        ethernet.compare_configs(self.before, after)

    def test_kconfig_disabled_and_absent_forms_have_same_meaning(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'.config'
            path.write_text('CONFIG_USB_F_ECM=m\n# CONFIG_SUN4I_EMAC is not set\nCONFIG_STMMAC_ETH=n\n')
            values = ethernet.config_values(path)
        self.assertEqual(values.get('CONFIG_SUN4I_EMAC', 'n'), 'n')
        self.assertEqual(values['CONFIG_STMMAC_ETH'], 'n')
        self.assertEqual(values['CONFIG_USB_F_ECM'], 'm')

    def test_unrelated_configuration_change_fails(self):
        before = dict(self.before, CONFIG_PM='y')
        after = dict(self.after, CONFIG_PM='n')
        with self.assertRaisesRegex(ValueError, 'Unaudited configuration change'):
            ethernet.compare_configs(before, after)

    def test_pair_rejects_changed_provenance_or_recovery_modules(self):
        before = dict(compile=dict(scratch='baseline', config_sha256='baseline-config',
                                   shared_source={'tree_sha256': 'source'}, builder={'image': 'compiler'}),
                      compiler_sha256='compiler-version', files={
                          ethernet.DTB: {'sha256': 'board', 'bytes': 100},
                          'drivers/usb/gadget/function/usb_f_ecm.ko': {'sha256': 'usb', 'bytes': 100},
                          'drivers/net/wireless/brcmfmac.ko': {'sha256': 'wifi', 'bytes': 200}})
        after = copy.deepcopy(before)
        after['compile'].update(scratch='candidate', config_sha256='candidate-config')
        self.assertEqual(ethernet.validate_pair(before, after), 2)
        mutations = [
            lambda value: value['compile'].update(scratch='baseline'),
            lambda value: value['compile'].update(config_sha256='baseline-config'),
            lambda value: value['compile']['shared_source'].update(tree_sha256='other-source'),
            lambda value: value['compile']['builder'].update(image='other-compiler'),
            lambda value: value.update(compiler_sha256='other-version'),
            lambda value: value['files'][ethernet.DTB].update(sha256='other-board'),
            lambda value: value['files'].pop('drivers/usb/gadget/function/usb_f_ecm.ko'),
            lambda value: value['files']['drivers/net/wireless/brcmfmac.ko'].update(sha256='other-wifi'),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                changed = copy.deepcopy(after); mutate(changed)
                with self.assertRaises(ValueError):
                    ethernet.validate_pair(before, changed)

    def test_paired_output_space_is_checked_on_the_actual_scratch_filesystem(self):
        path = Path('/comparison-storage/not-created')
        with patch.object(ethernet, 'filesystem', return_value=(9, 12*1024**3-1, '/comparison-storage')):
            with self.assertRaisesRegex(ValueError, '12 GiB'):
                ethernet.comparison_space(path)
        with patch.object(ethernet, 'filesystem', return_value=(9, 12*1024**3, '/comparison-storage')) as storage:
            result = ethernet.comparison_space(path)
        storage.assert_called_once_with(path)
        self.assertEqual(result['required_bytes'], 12*1024**3)
        self.assertEqual(result['path'], '/comparison-storage')

    def test_layout_retains_duplicate_static_symbol_names_and_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'symbols.txt'
            path.write_text(''.join(f'{0x1000+index*0x100:x} B {name}\n'
                                    for index, name in enumerate(ethernet.BOUNDARIES))+
                            '00001500 00000004 b same_name\n'
                            '00001508 00000004 b same_name\n'
                            '00001510 00000008 B other_name\n')
            result = ethernet.symbol_layout(path)
        self.assertEqual(result['kernel_address_span'], 0x600)
        self.assertEqual(result['first_sized_bss_symbol'], 0x1500)
        self.assertEqual(result['bss_symbol_sizes'], [['other_name', 8, 1], ['same_name', 4, 2]])

    def test_incomplete_layout_cannot_support_a_memory_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'symbols.txt'; path.write_text('00001000 00000004 B value\n')
            with self.assertRaisesRegex(ValueError, 'layout symbols missing'):
                ethernet.symbol_layout(path)


if __name__ == '__main__':
    unittest.main()
