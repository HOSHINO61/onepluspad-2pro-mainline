# SPDX-License-Identifier: GPL-2.0-only
"""Build the unchanged AOSP ext4-to-sparse converter from pinned inputs."""
import fcntl
import json
from pathlib import Path
import platform
import shutil
import subprocess

from .build_root import REPO, WS, fetch, sha256


def ext2simg():
    source = REPO / 'packaging/install-tools'
    lock = json.loads((source / 'source.json').read_text())
    if platform.machine() != lock['host_architecture']:
        raise RuntimeError('The pinned installer tools currently require an amd64 host')
    code = source / lock['source']['file']
    if sha256(code) != lock['source']['sha256']:
        raise RuntimeError('The upstream ext2simg source differs from its input manifest')
    compiler = shutil.which('cc')
    if not compiler:
        raise RuntimeError('A native C compiler is required to build ext2simg')
    inputs = {'source_lock_sha256': sha256(source / 'source.json'),
              'builder_sha256': sha256(Path(__file__)),
              'compiler_sha256': sha256(Path(compiler).resolve()),
              'compiler_version': subprocess.check_output([compiler, '--version'], text=True).splitlines()[0]}
    cache = WS / 'cache/install-tools'
    cache.mkdir(parents=True, exist_ok=True)
    binary, record = cache / 'ext2simg', cache / 'build.json'
    with (cache / '.lock').open('w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        if record.exists():
            saved = json.loads(record.read_text())
            if saved['inputs'] == inputs and all(
                    (cache / p).is_file() and sha256(cache / p) == digest
                    for p, digest in saved['outputs_sha256'].items()):
                return binary, saved
        sysroot = cache / 'sysroot'
        for entry in lock['packages']:
            package = fetch(entry['url'], cache / entry['file'], entry['sha256'])
            subprocess.run(['dpkg-deb', '-x', str(package), str(sysroot)], check=True)
        libs = sysroot / 'usr/lib/x86_64-linux-gnu'
        command = [compiler, '-O2', '-I' + str(sysroot / 'usr/include'),
                   '-I' + str(sysroot / 'usr/include/android'), str(code),
                   str(libs / 'libext2fs.a'), str(libs / 'libcom_err.a'),
                   str(libs / 'android/libsparse.so.0'),
                   '-Wl,--disable-new-dtags,-rpath,$ORIGIN/sysroot/usr/lib/x86_64-linux-gnu/android',
                   '-o', str(binary)]
        subprocess.run(command, check=True)
        outputs = [binary, *sorted((libs / 'android').glob('*.so.0'))]
        saved = {'inputs': inputs, 'upstream': lock['source'],
                 'packages': lock['packages'],
                 'outputs_sha256': {str(p.relative_to(cache)): sha256(p) for p in outputs}}
        record.write_text(json.dumps(saved, indent=2) + '\n')
        return binary, saved
