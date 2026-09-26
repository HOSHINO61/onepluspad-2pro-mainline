# SPDX-License-Identifier: GPL-2.0-only
"""erhai-audio: the topology guard against unopenable PCMs and dangling routes."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
INPUTS = REPO / 'packaging/audio'


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


build = load(REPO / 'tools/build-debs.py', 'build_debs')
SOURCE = json.loads((INPUTS / 'source.json').read_text())
WIDGETS = SOURCE['kernel_dai_widgets']


def recipe_conf():
    """The board recipe expanded with m4 against the pinned upstream archive."""
    archive = build.WS / 'cache' / SOURCE['archive']
    if not shutil.which('m4') or not archive.is_file():
        raise unittest.SkipTest('m4 or the pinned audioreach-topology archive is missing')
    with tempfile.TemporaryDirectory() as directory:
        with tarfile.open(archive) as tar:
            tar.extractall(directory, filter='data')
        upstream = Path(directory) / SOURCE['directory']
        return subprocess.run(['m4', '-I', str(INPUTS), '-I', str(upstream),
                               str(INPUTS / (SOURCE['model'] + '.m4'))],
                              capture_output=True, text=True, check=True).stdout


class TopologyGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conf = recipe_conf()

    def rejects(self, text, widgets=WIDGETS):
        with self.assertRaises(SystemExit) as caught:
            build.check_topology(text, widgets)
        return str(caught.exception)

    def test_board_recipe_passes(self):
        build.check_topology(self.conf, WIDGETS)

    def test_front_end_format_the_platform_cannot_serve(self):
        # The 0.1.36 speaker graph: S32_LE only, so aplay failed with EINVAL
        # at open and the kernel said nothing about it.
        start = self.conf.index('SectionPCMCapabilities."MultiMedia1 Playback"')
        old = self.conf[:start] + self.conf[start:].replace('"S16_LE"', '"S32_LE"', 1)
        self.assertIn("offers ['S32_LE']", self.rejects(old))

    def test_routes_must_end_at_real_widgets_and_controls(self):
        renamed = self.conf.replace('"Secondary TDM0 Playback, , device40.tdm_rx1"',
                                    '"Secondary TDM Playback, , device40.tdm_rx1"')
        self.assertIn("'Secondary TDM Playback'", self.rejects(renamed))
        control = self.conf.replace('Secondary TDM0 Audio Mixer, MultiMedia1, stream0.logger1',
                                    'Secondary TDM0 Audio Mixer, MultiMedia2, stream0.logger1')
        self.assertIn("no mixer control 'MultiMedia2'", self.rejects(control))

    def test_front_end_must_reach_a_back_end(self):
        cut = self.conf.replace('"device40.mfc1, , device40.logger1"', '')
        self.assertIn("'MultiMedia1 Playback' reaches no back-end", self.rejects(cut))
        cut = self.conf.replace('"device120.logger1, , device120.codec_dma_tx1"', '')
        self.assertIn("'MultiMedia3 Capture' reaches no back-end", self.rejects(cut))

    def test_every_declared_back_end_is_used(self):
        self.assertIn('Quinary TDM0 Playback',
                      self.rejects(self.conf, WIDGETS + ['Quinary TDM0 Playback']))


if __name__ == '__main__':
    unittest.main()
