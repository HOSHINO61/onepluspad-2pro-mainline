# SPDX-License-Identifier: GPL-2.0-only
"""The Wi-Fi regulatory country is set to CN once the radio exists."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'packaging/erhai-device-support/tree'
UNITS = ROOT / 'usr/lib/systemd/system'


class WifiCountryTest(unittest.TestCase):
    def test_the_radio_add_event_sets_cn(self):
        rule = (ROOT / 'usr/lib/udev/rules.d/81-erhai-wifi-country.rules').read_text()
        self.assertIn('SUBSYSTEM=="ieee80211"', rule)
        self.assertIn('ENV{SYSTEMD_WANTS}+="erhai-wifi-country.service"', rule)
        service = (UNITS / 'erhai-wifi-country.service').read_text()
        self.assertIn('Type=oneshot', service)
        self.assertIn('ExecStart=/usr/sbin/iw reg set CN', service)

    def test_no_time_zone_machinery_is_left(self):
        self.assertFalse((ROOT / 'usr/libexec/erhai-wifi-country').exists())
        self.assertFalse((UNITS / 'erhai-wifi-country.path').exists())
        self.assertFalse((UNITS / 'systemd-timedated.service.d').exists())


if __name__ == '__main__':
    unittest.main()
