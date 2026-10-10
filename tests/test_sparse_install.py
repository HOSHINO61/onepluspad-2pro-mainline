#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Apply the real converter's output to old nonzero storage, then check ext4."""
import json
import hashlib
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from lib.install_tools import ext2simg
spec = importlib.util.spec_from_file_location('installer', Path(__file__).resolve().parents[1] / 'tools/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def main():
    converter, _ = ext2simg()
    with tempfile.TemporaryDirectory(prefix='erhai-sparse-test-') as temporary:
        work = Path(temporary)
        tree = work / 'tree'
        tree.mkdir()
        (tree / 'payload').write_text('fresh installation\n')
        raw, sparse, target = (work / name for name in ('raw', 'sparse', 'target'))
        with raw.open('wb') as stream:
            stream.truncate(256 << 20)
        subprocess.run(['mke2fs', '-q', '-t', 'ext4', '-F', '-b', '4096', '-m', '0',
                        '-E', 'lazy_itable_init=0,lazy_journal_init=0', '-d', str(tree), str(raw)], check=True)
        runner = installer.Installer(SimpleNamespace(work=work, serial='OFFLINE_FIXTURE'))
        try:
            digest = runner.convert_sparse(converter, raw, sparse)
        finally:
            runner.log.close()
        assert hashlib.sha256(sparse.read_bytes()).hexdigest() == digest
        with target.open('wb') as stream:
            for _ in range(256):
                stream.write(b'\xa5' * (1 << 20))
        skipped = 0
        with sparse.open('rb') as source, target.open('r+b') as output:
            magic, major, minor, header, chunk, block, blocks, count, crc = struct.unpack('<I4H4I', source.read(28))
            assert (magic, major, header, chunk) == (0xed26ff3a, 1, 28, 12)
            offset = 0
            for _ in range(count):
                kind, reserved, length, total = struct.unpack('<2H2I', source.read(chunk))
                size = length * block
                output.seek(offset)
                if kind == 0xcac1:
                    data = source.read(total - chunk)
                    assert len(data) == size
                    output.write(data)
                elif kind == 0xcac2:
                    assert total == chunk + 4
                    output.write(source.read(4) * (size // 4))
                elif kind == 0xcac3:
                    assert total == chunk
                    skipped += size
                else:
                    raise AssertionError(f'unexpected chunk {kind:x}')
                offset += size
            assert offset == blocks * block == raw.stat().st_size
            assert not source.read() and skipped > 0
        subprocess.run(['e2fsck', '-fn', str(target)], check=True)
        payload = subprocess.check_output(['debugfs', '-R', 'cat /payload', str(target)], stderr=subprocess.DEVNULL)
        assert payload == (tree / 'payload').read_bytes()
        print(json.dumps({'status': 'PASS', 'prefill': '0xa5', 'filesystem': 'ext4',
                          'unallocated_bytes_left_untouched': skipped, 'file_content': 'verified'}))


if __name__ == '__main__':
    main()
