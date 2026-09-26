# SPDX-License-Identifier: GPL-2.0-only
"""Authentication boundaries of the tablet's power-key policy."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / (
    'packaging/erhai-device-support/tree/usr/sbin/erhai-power-key')
loader = importlib.machinery.SourceFileLoader('power_key', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
key = importlib.util.module_from_spec(spec)
loader.exec_module(key)


class PowerKeyTest(unittest.TestCase):
    standard = False

    def run_action(self, mode, session_class='user', locked='no', failure=None):
        calls = []
        info = {'User': '1000', 'Class': session_class, 'LockedHint': locked}

        def screen(_info, method, *args):
            calls.append((method, *args))
            if failure and method == 'Lock':
                raise RuntimeError(failure)
            return '(true,)'

        def power(_info, value=None):
            if value is not None:
                calls.append(('power', value))
            return mode

        def unused(_info, value=None):
            raise AssertionError('the other display backend was used')

        wake = Mock()
        used, other = ('mutter_mode', 'power_mode') if self.standard else (
            'power_mode', 'mutter_mode')
        with patch.object(key, 'active_session', return_value=info), \
                patch.object(key, 'standard_path', return_value=self.standard), \
                patch.object(key, 'screensaver', side_effect=screen), \
                patch.object(key, used, side_effect=power), \
                patch.object(key, other, side_effect=unused):
            if failure:
                with self.assertRaises(RuntimeError):
                    key.toggle(wake)
            else:
                key.toggle(wake)
        return calls, wake

    def test_user_is_locked_before_display_is_blanked(self):
        calls, wake = self.run_action(0)
        self.assertLess(calls.index(('Lock',)), calls.index(('power', 3)))
        wake.wake.assert_not_called()

    def test_lock_failure_does_not_hide_an_unlocked_desktop(self):
        calls, _ = self.run_action(0, failure='lock denied')
        self.assertNotIn(('power', 3), calls)

    def test_greeter_keeps_its_login_policy(self):
        calls, _ = self.run_action(0, session_class='greeter')
        self.assertEqual(calls, [('power', 3)])

    def test_greeter_wake_does_not_hide_the_login_dialog(self):
        calls, wake = self.run_action(3, session_class='greeter')
        self.assertEqual(calls, [('power', 0)])
        wake.wake.assert_called_once_with()

    def test_repeated_blank_of_locked_session(self):
        calls, _ = self.run_action(0, locked='yes')
        self.assertNotIn(('Lock',), calls)
        self.assertIn(('power', 3), calls)

    def test_wake_never_deactivates_the_lock_screen(self):
        for mode in (1, 2, 3):
            with self.subTest(mode=mode):
                calls, wake = self.run_action(mode, locked='yes')
                self.assertEqual(calls, [('power', 0)])
                wake.wake.assert_called_once_with()

    def test_unknown_display_state_does_not_change_power(self):
        calls, wake = self.run_action(-1, failure='unknown')
        self.assertEqual(calls, [])
        wake.wake.assert_not_called()


class StandardPathTest(PowerKeyTest):
    """The same boundaries when the key drives Mutter's PowerSaveMode."""
    standard = True


class MutterBackendTest(unittest.TestCase):
    info = {'User': '1000', 'Class': 'greeter'}

    def test_reads_and_sets_power_save_mode(self):
        calls = []

        def session(_info, dest, path, method, *args):
            calls.append((dest, path, method, *args))
            return '(<3>,)'
        with patch.object(key, 'call_session', side_effect=session):
            self.assertEqual(key.mutter_mode(self.info), 3)
            self.assertEqual(key.mutter_mode(self.info, 0), 0)
        interface = 'org.gnome.Mutter.DisplayConfig'
        self.assertEqual(calls, [
            (interface, '/org/gnome/Mutter/DisplayConfig',
             'org.freedesktop.DBus.Properties.Get', interface, 'PowerSaveMode'),
            (interface, '/org/gnome/Mutter/DisplayConfig',
             'org.freedesktop.DBus.Properties.Set', interface, 'PowerSaveMode', '<0>')])

    def test_unreadable_reply_is_refused(self):
        for reply in ('', '(<"on">,)', '(3,)'):
            with self.subTest(reply=reply), \
                    patch.object(key, 'call_session', return_value=reply), \
                    self.assertRaises(RuntimeError):
                key.mutter_mode(self.info)

    def test_marker_selects_the_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, etc = Path(tmp) / 'run-marker', Path(tmp) / 'etc-marker'
            with patch.object(key, 'MODE_MARKERS', (run, etc)):
                self.assertFalse(key.standard_path())
                etc.write_text('compat\n')
                self.assertFalse(key.standard_path())
                etc.write_text('standard\n')
                self.assertTrue(key.standard_path())
                etc.unlink()
                run.write_text('standard\n')
                self.assertTrue(key.standard_path())


if __name__ == '__main__':
    unittest.main()
