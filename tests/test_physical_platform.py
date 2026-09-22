# SPDX-License-Identifier: GPL-2.0-only
"""The device-tree workaround must not mask another board or a real guest."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

HELPER = Path(__file__).resolve().parents[1] / (
    'packaging/erhai-device-support/tree/usr/libexec/erhai-physical-platform')


class PlatformBoundaryTest(unittest.TestCase):
    def rejected(self, model='OnePlus Pad 2 Pro', chassis='tablet', vmid=3,
                 compatible='qcom,gunyah-hypervisor', bound=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / 'firmware/devicetree/base'
            vm = base / 'hypervisor/qcom,gunyah-vm'
            vm.mkdir(parents=True)
            (base / 'model').write_bytes(model.encode() + b'\0')
            (base / 'chassis-type').write_bytes(chassis.encode() + b'\0')
            (base / 'hypervisor/compatible').write_bytes(compatible.encode() + b'\0')
            (vm / 'qcom,vmid').write_bytes(vmid.to_bytes(4, 'big'))
            if bound:
                (root / 'bus/platform/devices/hypervisor/driver').mkdir(parents=True)
            commands = root / 'commands'
            commands.mkdir()
            marker = root / 'mount-called'
            (commands / 'mount').write_text(
                '#!/bin/sh\nprintf called >' + shlex.quote(str(marker)) + '\n')
            (commands / 'mount').chmod(0o755)
            result = subprocess.run(['sh', str(HELPER), str(root)], text=True,
                                    capture_output=True, env={**os.environ,
                                    'PATH': str(commands) + os.pathsep + os.environ['PATH']})
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists(), 'rejected platform reached mount')

    def test_other_board(self):
        self.rejected(model='Generic ARM guest')

    def test_other_form_factor(self):
        self.rejected(chassis='handset')

    def test_secondary_gunyah_guest(self):
        self.rejected(vmid=4)

    def test_kvm_is_not_hidden(self):
        self.rejected(compatible='linux,kvm')

    def test_bound_hypervisor_driver(self):
        self.rejected(bound=True)


if __name__ == '__main__':
    unittest.main()
