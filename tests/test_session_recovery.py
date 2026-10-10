# SPDX-License-Identifier: GPL-2.0-only
"""Run the generated expiry command with a blocked sync and a fake reboot.

The shell and timeout are real. No device, filesystem mount or reboot syscall
is used; these checks establish userspace flow, not hardware recovery.
"""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest


REPO = Path(__file__).resolve().parents[1]


class SessionRecovery(unittest.TestCase):
    def expire(self, sync_body, ram=False):
        source = (REPO / 'initramfs/init-ncm').read_text()
        marker = ('cat > /newroot/etc/systemd/system/erhai-session-expiry.service' if ram
                  else 'cat > /newroot/run/systemd/system/erhai-test-session.service')
        start = source.index(marker)
        unit = source[start:].split('\nEOF', 1)[0]
        command = next(line.removeprefix('ExecStart=') for line in unit.splitlines()
                       if line.startswith('ExecStart='))
        argv = shlex.split(command.replace('$SESSION_SECONDS', '0'))
        self.assertEqual(argv[:2], ['/bin/sh', '-c'])
        # Refuse to run if the actual reboot invocation cannot be substituted.
        self.assertEqual(argv[2].count('/sbin/reboot'), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sync').write_text('#!/bin/sh\n' + sync_body + '\n')
            (root / 'reboot').write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" > "$RECOVERY_TEST_ROOT/reboot-args"\n')
            for name in ('sync', 'reboot'):
                (root / name).chmod(0o755)
            argv[2] = argv[2].replace('/run/erhai-test-session', str(root / 'session')).replace(
                '/dev/kmsg', str(root / 'kmsg')).replace('/sbin/reboot', str(root / 'reboot'))
            started = time.monotonic()
            result = subprocess.run(argv, capture_output=True, text=True, timeout=12,
                                    env={**os.environ, 'PATH': directory + ':' + os.defpath,
                                         'RECOVERY_TEST_ROOT': directory})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertLess(time.monotonic() - started, 10)
            if not ram:
                self.assertEqual((root / 'session.started').read_text(), 'started\n')
            self.assertEqual((root / 'session.expired').read_text(), 'expired\n')
            # Repeating sync in reboot would defeat the preceding timeout.
            self.assertEqual((root / 'reboot-args').read_text(), '-f -n bootloader\n')

    def test_successful_writeback_reaches_reboot(self):
        self.expire('exit 0')

    def test_writeback_error_still_reaches_reboot(self):
        self.expire('exit 1')

    def test_writeback_ignoring_term_cannot_block_reboot(self):
        self.expire("trap '' TERM\nexec sleep 30")

    def test_ram_root_expiry_with_successful_sync(self):
        self.expire('exit 0', ram=True)

    def test_ram_root_expiry_with_failed_sync(self):
        self.expire('exit 1', ram=True)

    def test_ram_root_expiry_with_blocked_sync(self):
        self.expire("trap '' TERM\nexec sleep 30", ram=True)


if __name__ == '__main__':
    unittest.main()
