# SPDX-License-Identifier: GPL-2.0-only
"""Backlight discovery, seat authorization and manual/automatic blanking arbitration."""
import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / (
    'packaging/erhai-display-power/tree/usr/sbin/erhai-display-power')
loader = importlib.machinery.SourceFileLoader('display_power', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
power = importlib.util.module_from_spec(spec)
loader.exec_module(power)


def add_backlight(root, name, compatible=None):
    """A sysfs-shaped backlight: bl_power plus device/of_node/compatible."""
    device = root / name
    device.mkdir(parents=True)
    (device / 'bl_power').write_text('0\n')
    if compatible is not None:
        node = device / 'device/of_node'
        node.mkdir(parents=True)
        node.joinpath('compatible').write_bytes(compatible.encode() + b'\0')
    return device


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / 'backlight'
        self.root.mkdir()

    def test_single_led_backlight_is_selected(self):
        add_backlight(self.root, 'backlight', 'led-backlight')
        self.assertEqual(power.find_backlight(self.root),
                         self.root / 'backlight' / 'bl_power')

    def test_led_backlight_is_preferred_over_raw_chip(self):
        add_backlight(self.root, 'ktz8866-backlight', 'kinetic,ktz8868')
        add_backlight(self.root, 'backlight', 'led-backlight')
        self.assertEqual(power.find_backlight(self.root),
                         self.root / 'backlight' / 'bl_power')

    def test_no_backlight_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'found: none'):
            power.find_backlight(self.root)

    def test_separate_chip_backlights_are_refused(self):
        # The layout before led-backlight: two raw devices, one per chip.
        add_backlight(self.root, 'ktz8868-master', 'kinetic,ktz8868')
        add_backlight(self.root, 'ktz8868-slave', 'kinetic,ktz8868')
        with self.assertRaisesRegex(RuntimeError, 'ktz8868-master.*ktz8868-slave'):
            power.find_backlight(self.root)

    def test_single_unidentified_backlight_is_refused(self):
        add_backlight(self.root, 'ktz8868-slave')
        with self.assertRaisesRegex(RuntimeError, 'no OF node'):
            power.find_backlight(self.root)

    def test_two_led_backlights_are_refused(self):
        add_backlight(self.root, 'backlight', 'led-backlight')
        add_backlight(self.root, 'backlight-1', 'led-backlight')
        with self.assertRaises(RuntimeError):
            power.find_backlight(self.root)

    def test_missing_class_directory_is_refused(self):
        with self.assertRaises(RuntimeError):
            power.find_backlight(self.root / 'absent')

    def test_exec_condition_skips_ambiguous_layouts(self):
        add_backlight(self.root, 'ktz8868-master', 'kinetic,ktz8868')
        add_backlight(self.root, 'ktz8868-slave', 'kinetic,ktz8868')
        original = power.find_backlight
        discover = lambda: original(self.root)
        with mock.patch.object(power, 'find_backlight', discover), \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(power.check(), 1)
        self.assertIn('expected exactly one led-backlight', stderr.getvalue())
        add_backlight(self.root, 'backlight', 'led-backlight')
        with mock.patch.object(power, 'find_backlight', discover):
            self.assertEqual(power.check(), 0)

    def test_unit_names_no_backlight_device(self):
        unit = (SOURCE.parents[1] / 'lib/systemd/system/erhai-display-power.service').read_text()
        self.assertNotIn('ktz8868', unit)
        self.assertIn('ExecCondition=/usr/sbin/erhai-display-power --check', unit)


class DisplayPowerTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'bl_power'
        self.path.write_text('0\n')
        self.lights = power.Backlight(self.path)

    def test_active_seat_controls_the_backlight(self):
        self.assertEqual(self.lights.request('AUTO 3', 1000, 1000), 3)
        self.assertEqual(self.path.read_text(), '4\n')
        self.assertEqual(self.lights.request('AUTO 0', 1000, 1000), 0)
        self.assertEqual(self.path.read_text(), '0\n')

    def test_inactive_user_cannot_change_display(self):
        with self.assertRaises(PermissionError):
            self.lights.request('AUTO 3', 1001, 1000)
        self.assertEqual(self.lights.mode(), 0)

    def test_session_cannot_impersonate_system_key_handler(self):
        with self.assertRaises(PermissionError):
            self.lights.request('KEY 3', 1000, 1000)
        self.assertEqual(self.lights.mode(), 0)

    def test_lock_animation_cannot_undo_manual_blank(self):
        self.lights.request('KEY 3', 0, 1000)
        self.assertEqual(self.lights.request('AUTO 0', 1000, 1000), 3)
        self.assertEqual(self.lights.request('KEY 0', 0, 1000), 0)

    def test_new_active_session_does_not_inherit_old_manual_intent(self):
        self.lights.request('KEY 3', 0, 1000)
        self.assertEqual(self.lights.request('AUTO 0', 1001, 1001), 0)

    def test_write_failure_tries_to_restore_the_backlight(self):
        writes = []

        class FailingBlank:
            def read_text(self):
                return writes[-1] if writes else '0\n'

            def write_text(self, value):
                writes.append(value)
                if value != '0\n':
                    raise OSError('write failed')

        self.lights.path = FailingBlank()
        with self.assertRaises(OSError):
            self.lights.request('KEY 3', 0, 1000)
        self.assertEqual(writes, ['4\n', '0\n'])

    def test_unexpected_power_state_is_rejected(self):
        self.path.write_text('1\n')
        with self.assertRaises(RuntimeError):
            self.lights.mode()

    def test_invalid_command_does_not_change_state(self):
        for request in ('AUTO -1', 'AUTO 4', 'KEY 3 extra', 'UNKNOWN 0'):
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.lights.request(request, 0, 1000)
        self.assertEqual(self.lights.mode(), 0)


if __name__ == '__main__':
    unittest.main()
