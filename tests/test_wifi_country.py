# SPDX-License-Identifier: GPL-2.0-only
"""The Wi-Fi regulatory country follows the system time zone."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'packaging/erhai-device-support/tree'
SCRIPT = ROOT / 'usr/libexec/erhai-wifi-country'
ZONE_TAB = '# comment\nCN\t+3114+12128\tAsia/Shanghai\tBeijing Time\nUS\t+404251-0740023\tAmerica/New_York\tEastern\n'


class WifiCountryTest(unittest.TestCase):
    def run_script(self, zone):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            zoneinfo = tmp / 'usr/share/zoneinfo'
            (zoneinfo / zone).parent.mkdir(parents=True)
            (zoneinfo / zone).write_bytes(b'TZif')
            (zoneinfo / 'zone.tab').write_text(ZONE_TAB)
            localtime = tmp / 'localtime'
            localtime.symlink_to(zoneinfo / zone)
            bin_dir = tmp / 'bin'
            bin_dir.mkdir()
            calls = tmp / 'iw-calls'
            (bin_dir / 'iw').write_text(f'#!/bin/sh\necho "$@" >> {calls}\n')
            (bin_dir / 'iw').chmod(0o755)
            env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}',
                       ERHAI_LOCALTIME=str(localtime), ERHAI_ZONE_TAB=str(zoneinfo / 'zone.tab'))
            result = subprocess.run([str(SCRIPT)], env=env, capture_output=True, text=True,
                                    check=True)
            return result.stdout, calls.read_text() if calls.exists() else ''

    def test_zone_with_a_country_sets_it(self):
        out, calls = self.run_script('Asia/Shanghai')
        # The database is reloaded first: the boot-time load fails before the
        # root file system is mounted and would block every later hint.
        self.assertEqual(calls, 'reg reload\nreg set CN\n')
        self.assertIn('regulatory country CN', out)

    def test_zone_without_a_country_uses_the_world_domain(self):
        out, calls = self.run_script('Etc/UTC')
        self.assertEqual(calls, 'reg reload\nreg set 00\n')
        self.assertIn('using the world domain', out)

    def test_units_follow_the_radio_and_time_zone_changes(self):
        rule = (ROOT / 'usr/lib/udev/rules.d/81-erhai-wifi-country.rules').read_text()
        self.assertIn('SUBSYSTEM=="ieee80211"', rule)
        self.assertIn('ENV{SYSTEMD_WANTS}+="erhai-wifi-country.service"', rule)
        # /etc/localtime is a symlink that a path unit cannot watch; timedated
        # makes the change and starts the service when it exits.
        self.assertFalse((ROOT / 'usr/lib/systemd/system/erhai-wifi-country.path').exists())
        dropin = (ROOT / 'usr/lib/systemd/system/systemd-timedated.service.d/'
                  '80-erhai-wifi-country.conf').read_text()
        self.assertIn('ExecStopPost=-+/usr/bin/systemctl --no-block start '
                      'erhai-wifi-country.service', dropin)


if __name__ == '__main__':
    unittest.main()
