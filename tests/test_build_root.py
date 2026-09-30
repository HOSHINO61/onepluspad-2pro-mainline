# SPDX-License-Identifier: GPL-2.0-only
"""A cached SDK is reusable only with the same pinned input identity."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'tools/lib/build_root.py'
spec = importlib.util.spec_from_file_location('roots', path)
roots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(roots)


class BuildRoot(unittest.TestCase):
    def test_pinned_cache_reused_without_running_apt(self):
        pins = {'build_root': {'sha256': 'base'}, 'apt': {'snapshot': 'fixed'}}
        with tempfile.TemporaryDirectory() as folder, patch.object(roots, 'chroot') as run:
            work = Path(folder)
            (work / 'root').mkdir()
            (work / 'root.json').write_text(json.dumps(pins))
            self.assertEqual(roots.prepare_root(work, pins, None, None), work / 'root')
            run.assert_not_called()
            pins['apt']['snapshot'] = 'changed'
            with self.assertRaises(SystemExit):
                roots.prepare_root(work, pins, None, None)
            run.assert_not_called()

    def test_unidentified_root_is_not_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            (work / 'root').mkdir()
            with self.assertRaises(SystemExit):
                roots.prepare_root(work, {'build_root': {}, 'apt': {}}, None, None)

    def test_verified_download_cache_needs_no_network(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(roots.urllib.request, 'urlopen') as fetch:
            path = Path(folder) / 'source'
            path.write_bytes(b'pinned source')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(roots.fetch('https://example.invalid/source', path, digest), path)
            fetch.assert_not_called()
