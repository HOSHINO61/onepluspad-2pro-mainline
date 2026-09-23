# SPDX-License-Identifier: GPL-2.0-only
"""Seat authorization and manual/automatic blanking arbitration."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / (
    'packaging/erhai-display-power/tree/usr/sbin/erhai-display-power')
loader = importlib.machinery.SourceFileLoader('display_power', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
power = importlib.util.module_from_spec(spec)
loader.exec_module(power)


class DisplayPowerTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.paths = tuple(Path(self.directory.name) / name for name in ('master', 'slave'))
        for path in self.paths:
            path.write_text('0\n')
        self.lights = power.Backlights(self.paths)

    def test_active_seat_controls_both_leds(self):
        self.assertEqual(self.lights.request('AUTO 3', 1000, 1000), 3)
        self.assertEqual([p.read_text() for p in self.paths], ['4\n', '4\n'])
        self.assertEqual(self.lights.request('AUTO 0', 1000, 1000), 0)
        self.assertEqual([p.read_text() for p in self.paths], ['0\n', '0\n'])

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

    def test_partial_write_failure_restores_first_led(self):
        self.lights.paths = (self.paths[0], Path(self.directory.name) / 'absent' / 'slave')
        with self.assertRaises(OSError):
            self.lights.request('KEY 3', 0, 1000)
        self.assertEqual(self.paths[0].read_text(), '0\n')

    def test_invalid_command_does_not_change_state(self):
        for request in ('AUTO -1', 'AUTO 4', 'KEY 3 extra', 'UNKNOWN 0'):
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.lights.request(request, 0, 1000)
        self.assertEqual(self.lights.mode(), 0)


if __name__ == '__main__':
    unittest.main()
