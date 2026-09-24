#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Stage the complete, verified Kbuild module set without installing on the host."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(argv, **kwargs):
    return subprocess.check_output(list(map(str, argv)), text=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-source', type=Path, required=True)
    parser.add_argument('--kernel-out', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cross-compile', default='aarch64-linux-gnu-')
    args = parser.parse_args()
    src, out, stage = (path.resolve() for path in
                       (args.kernel_source, args.kernel_out, args.output))
    with (out / '.build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        build = json.loads((out / 'build-result.json').read_text())
        head = run(['git', '-C', src, 'rev-parse', 'HEAD']).strip()
        if head != build['kernel_commit'] or run(['git', '-C', src, 'status', '--porcelain']).strip():
            parser.error('source differs from the completed module build')
        release = build['kernel_release']
        if not re.fullmatch(r'[a-z0-9.+-]{1,64}', release):
            parser.error('invalid kernel release')
        if (out / 'include/config/kernel.release').read_text().strip() != release:
            parser.error('kernel release changed after the build')
        if not build.get('modules') or not build.get('localversion'):
            parser.error('a completed, distinct-ABI module build is required')
        for group in ('files', 'modules', 'module_metadata'):
            for name, digest in build[group].items():
                path = Path(name)
                if path.is_absolute() or '..' in path.parts or sha(out / path) != digest:
                    parser.error('changed or invalid build input: ' + name)
        compiler = shutil.which(args.cross_compile + 'gcc')
        strip = shutil.which(args.cross_compile + 'strip')
        depmod = shutil.which('depmod')
        if not compiler or not strip or not depmod or sha(compiler) != build['compiler_sha256']:
            parser.error('the recorded compiler, target strip and depmod are required')
        stage.mkdir(parents=True, exist_ok=True)
        module_dir = stage / 'usr/lib/modules' / release
        if module_dir.exists() or (stage / 'lib').exists() or (stage / 'lib').is_symlink():
            parser.error('select a fresh staging tree')
        env = dict(os.environ, ARCH='arm64', CROSS_COMPILE=args.cross_compile)
        install_log = run(['make', '-C', src, f'O={out}',
                           f'LOCALVERSION={build["localversion"]}',
                           f'MODLIB={module_dir}', 'INSTALL_MOD_STRIP=1',
                           'DEPMOD=true', 'modules_install'], env=env)
        # Runtime packages do not point into a developer's source/build tree.
        for name in ('build', 'source'):
            path = module_dir / name
            if path.is_symlink():
                path.unlink()
        expected = {'kernel/' + name for name in build['modules']}
        installed = {str(path.relative_to(module_dir)) for path in module_dir.rglob('*.ko')}
        if installed != expected:
            parser.error('Kbuild installed a different module closure')
        # Older depmod versions use /lib/modules. This temporary staging link
        # provides Ubuntu's usr-merged layout and is not included in payloads.
        (stage / 'lib').symlink_to('usr/lib', target_is_directory=True)
        try:
            subprocess.run([depmod, '-C', '/dev/null', '-b', str(stage), '-a', release], check=True)
        finally:
            (stage / 'lib').unlink()
        for name in ('modules.dep', 'modules.alias', 'modules.builtin',
                     'modules.builtin.modinfo', 'modules.dep.bin', 'modules.alias.bin'):
            if not (module_dir / name).is_file():
                parser.error('missing runtime module index: ' + name)
        vermagic = None
        for path in sorted(module_dir.rglob('*.ko')):
            value = run(['modinfo', '-F', 'vermagic', path]).strip()
            if value.split()[0] != release or (vermagic is not None and value != vermagic):
                parser.error('module/kernel ABI mismatch: ' + str(path))
            vermagic = value
        if run(['git', '-C', src, 'rev-parse', 'HEAD']).strip() != head:
            parser.error('source changed during installation')
        builtin_metadata = {'modules.order', 'modules.builtin', 'modules.builtin.modinfo',
                            'modules.builtin.ranges'}
        files, indices = {}, {}
        for path in sorted(module_dir.rglob('*')):
            if not path.is_file():
                continue
            entries = files if path.suffix == '.ko' or path.name in builtin_metadata else indices
            entries[str(path.relative_to(stage))] = sha(path)
        metadata = {'status': 'OFFLINE_STAGED_NOT_DEVICE_TESTED',
                    'kernel_commit': head, 'kernel_release': release,
                    'build_manifest_sha256': sha(out / 'build-result.json'),
                    'module_count': len(installed), 'vermagic': vermagic,
                    'tools_sha256': {'strip': sha(strip), 'depmod': sha(depmod)},
                    'files_sha256': files, 'staged_indices_sha256': indices}
        (stage / 'modules-manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
        (stage / 'modules-install.log').write_text(install_log)
        print(json.dumps({'kernel_release': release, 'modules': len(installed),
                          'status': metadata['status']}))


if __name__ == '__main__':
    main()
