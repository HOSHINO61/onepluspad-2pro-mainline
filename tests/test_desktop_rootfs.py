# SPDX-License-Identifier: GPL-2.0-only
"""Test the root manifest's byte-safe file identities and original-input boundary."""
import contextlib
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'tools'))
spec = importlib.util.spec_from_file_location('desktop_rootfs', REPO / 'tools/build-desktop-rootfs.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class DesktopRootTest(unittest.TestCase):
    def test_manifest_preserves_names_links_and_content_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            root = out / 'root'
            root.mkdir()
            (root / 'with space').mkdir()
            name = 'with space/中文\nfile'
            (root / name).write_bytes(b'content\x00with binary data')
            os.link(root / name, root / 'alias')
            (root / 'link').symlink_to(name)
            (root / '\\leading').write_bytes(b'')
            with (out / 'file-hashes.raw').open('wb') as sink:
                subprocess.run(['sha256sum', '--zero', './alias', './' + name,
                                './\\leading'], cwd=root, stdout=sink, check=True)
            with (out / 'file-metadata.raw').open('wb') as sink:
                subprocess.run(['find', str(root), '-xdev', '-printf',
                                r'%P\0%y\0%m\0%U\0%G\0%s\0%T@\0%l\0%D\0%i\0%n\0'],
                               stdout=sink, check=True)
            count = builder.make_file_manifest(out)
            with gzip.open(out / 'rootfs-files.jsonl.gz', 'rt') as source:
                rows = {item['path']: item for item in map(json.loads, source)}
            self.assertEqual(count, 6)
            self.assertEqual(set(rows), {'', 'with space', name, 'alias', 'link', '\\leading'})
            self.assertEqual(rows['link']['target'], name)
            self.assertEqual(rows[name]['hardlink_to'], 'alias')
            self.assertEqual(rows[name]['sha256'], hashlib.sha256((root / name).read_bytes()).hexdigest())
            self.assertEqual(rows['\\leading']['sha256'], hashlib.sha256(b'').hexdigest())
            self.assertEqual(rows[name]['uid'], os.getuid())

    def test_modified_layer_stops_before_output_or_container(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'minimal.squashfs').write_bytes(b'not the official Desktop layer')
            output = base / 'output'
            argv = ['build-desktop-rootfs.py', '--layers', str(base),
                    '--device-deb', 'unused.deb', '--output', str(output)]
            with mock.patch.object(sys, 'argv', argv), \
                 mock.patch.object(builder, 'run') as command, \
                 contextlib.redirect_stderr(io.StringIO()) as stderr, \
                 self.assertRaises(SystemExit) as raised:
                builder.main()
            self.assertEqual(raised.exception.code, 2)
            self.assertIn('not the pinned original Ubuntu layer', stderr.getvalue())
            command.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
