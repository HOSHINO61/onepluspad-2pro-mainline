# SPDX-License-Identifier: GPL-2.0-only
"""RAM desktop images must identify their root independently of old outputs."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('ram_boot', TOOLS / 'build-mainline-boot.py')
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


class RamRootBuildTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.image = self.root / 'root.squashfs'
        self.image.write_bytes(b'explicit root input')
        self.url = 'http://192.0.2.1:8000/desktop.squashfs'
        self.output = self.root / 'boot'

    def invoke(self, *args):
        with patch.object(sys, 'argv', [str(TOOLS / 'build-mainline-boot.py'),
                          '--output', str(self.output), *args]):
            boot.main()

    def rejected(self, *args):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            self.invoke(*args)
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.output.exists())

    def test_desktop_has_no_implicit_root(self):
        self.rejected('--profile', 'desktop')

    def test_both_file_and_url_are_required(self):
        self.rejected('--profile', 'desktop', '--rootfs', str(self.image))
        self.rejected('--profile', 'desktop', '--rootfs-url', self.url)

    def test_installed_profile_does_not_accept_a_ram_root(self):
        self.rejected('--profile', 'persistent', '--rootfs', str(self.image),
                      '--rootfs-url', self.url)

    def test_extra_cmdline_cannot_replace_the_identified_root(self):
        for extra in ('erhai.rootfs=http://other/root', 'erhai.rootfs.sha256=wrong',
                      'erhai.root=PARTLABEL=other'):
            with self.subTest(extra=extra):
                self.rejected('--profile', 'desktop', '--rootfs', str(self.image),
                              '--rootfs-url', self.url, '--cmdline-extra', extra)

    def test_url_cannot_insert_a_kernel_argument(self):
        self.rejected('--profile', 'desktop', '--rootfs', str(self.image),
                      '--rootfs-url', self.url + ' erhai.root=/dev/other')

    def test_packer_and_manifest_identify_the_same_root(self):
        image = self.root / 'arch/arm64/boot/Image'
        image.parent.mkdir(parents=True)
        image.write_bytes(b'kernel fixture')
        dtb = self.root / 'board.dtb'
        dtb.write_bytes(b'dtb fixture')
        ramdisk = self.root / 'initramfs'
        ramdisk.write_bytes(b'ramdisk fixture')
        calls = []

        def run(command, **kwargs):
            if command[0] == 'git':
                return subprocess.CompletedProcess(command, 0,
                    stdout='commit\n' if command[-1] == 'HEAD' else '')
            calls.append(command)
            Path(command[command.index('--output') + 1]).write_bytes(b'boot fixture')
            return subprocess.CompletedProcess(command, 0)

        with patch.object(boot.subprocess, 'run', side_effect=run), \
                patch.object(boot, 'sink_layout', return_value='none'), \
                contextlib.redirect_stdout(io.StringIO()):
            self.invoke('--profile', 'desktop', '--rootfs', str(self.image),
                        '--rootfs-url', self.url, '--kernel-out', str(self.root),
                        '--dtb', str(dtb), '--initramfs', str(ramdisk))
        expected = hashlib.sha256(self.image.read_bytes()).hexdigest()
        manifest = json.loads((self.output / 'manifest.json').read_text())
        self.assertEqual(manifest['ram_rootfs'], {'url': self.url, 'sha256': expected})
        cmdline = calls[0][calls[0].index('--cmdline') + 1]
        self.assertEqual(manifest['cmdline'], cmdline)
        self.assertIn('erhai.rootfs.sha256=' + expected, cmdline.split())
        self.assertIn('erhai.rootfs=' + self.url, cmdline.split())
        self.assertIn('erhai.watchdog=900', cmdline.split())
        self.assertIn('erhai.session=5400', cmdline.split())


if __name__ == '__main__':
    unittest.main()
