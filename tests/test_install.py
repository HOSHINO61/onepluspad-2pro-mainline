# SPDX-License-Identifier: GPL-2.0-only
"""Refusal boundaries before any device transition or partition write."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('erhai_install', TOOLS / 'install.py')
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class InstallBoundaries(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.work = Path(self.directory.name)
        self.args = SimpleNamespace(work=self.work, serial='TEST_DEVICE', erase_linux=True)
        self.installer = install.Installer(self.args)
        self.installer.run = Mock(side_effect=AssertionError('device command reached'))
        self.plan = {'serial': self.args.serial, 'slot': '_a', 'firmware': 'fixture',
                     'partitions': {'linux_rootfs': {'bytes': 4096}, 'linux_data': {'bytes': 4096}}}
        self.installer.load_backup = Mock(return_value=self.plan)
        self.installer.inspect = Mock(return_value=self.plan)

    def tearDown(self):
        self.installer.log.close()
        self.directory.cleanup()

    def test_explicit_erase_is_required_before_inspection(self):
        self.args.erase_linux = False
        with self.assertRaisesRegex(RuntimeError, '--erase-linux'):
            self.installer.install()
        self.installer.inspect.assert_not_called()
        self.installer.run.assert_not_called()

    def test_changed_layout_is_rejected_before_transition(self):
        self.installer.inspect.return_value = {**self.plan, 'slot': '_b'}
        with self.assertRaisesRegex(RuntimeError, 'layout or firmware changed'):
            self.installer.install()
        self.installer.run.assert_not_called()

    def test_prepared_image_for_another_device_is_rejected(self):
        (self.work / 'prepared.json').write_text(json.dumps({'serial': 'OTHER_DEVICE'}))
        with self.assertRaisesRegex(RuntimeError, 'another tablet'):
            self.installer.install()
        self.installer.run.assert_not_called()

    def test_android_userdata_cannot_be_a_flash_target(self):
        (self.work / 'prepared.json').write_text(json.dumps({
            'serial': self.args.serial, 'images': {'userdata': {}}}))
        with self.assertRaisesRegex(RuntimeError, 'Unexpected flash target'):
            self.installer.install()
        self.installer.run.assert_not_called()

    def test_incomplete_linux_set_is_rejected(self):
        (self.work / 'prepared.json').write_text(json.dumps({
            'serial': self.args.serial, 'images': {}}))
        with self.assertRaisesRegex(RuntimeError, 'Both Linux images'):
            self.installer.install()
        self.installer.run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
