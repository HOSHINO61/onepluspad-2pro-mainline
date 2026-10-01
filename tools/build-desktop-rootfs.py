#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assemble pinned Ubuntu Desktop layers and explicit device debs in a container."""
import argparse
import errno
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from lib.build_root import REPO, WS, fetch, sha256


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def metadata(path):
    fields = subprocess.check_output(
        ['dpkg-deb', '-f', str(path), 'Package', 'Version', 'Architecture'], text=True)
    return dict(line.split(': ', 1) for line in fields.splitlines())


def make_file_manifest(out):
    hashes = {}
    for record in (out / 'file-hashes.raw').read_bytes().split(b'\0'):
        if record:
            hashes[os.fsdecode(record[66:]).removeprefix('./')] = record[:64].decode()
    fields = (out / 'file-metadata.raw').read_bytes().split(b'\0')
    assert not fields[-1] and (len(fields) - 1) % 11 == 0
    rows = [fields[i:i + 11] for i in range(0, len(fields) - 1, 11)]
    links = {}
    with gzip.open(out / 'rootfs-files.jsonl.gz', 'wt', encoding='utf-8') as output:
        for row in sorted(rows, key=lambda x: x[0]):
            path, kind, mode, uid, gid, size, mtime, target, device, inode, nlink = map(os.fsdecode, row)
            item = {'path': path, 'type': kind, 'mode': mode, 'uid': int(uid),
                    'gid': int(gid), 'size': int(size), 'mtime': mtime}
            if kind == 'f':
                item['sha256'] = hashes[path]
                if int(nlink) > 1:
                    key = (device, inode)
                    if key in links:
                        item['hardlink_to'] = links[key]
                    else:
                        links[key] = path
            elif kind == 'l':
                item['target'] = target
            output.write(json.dumps(item, ensure_ascii=True) + '\n')
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layers', type=Path, required=True,
                        help='Original ISO casper directory, containing the two pinned squashfs files')
    parser.add_argument('--device-deb', type=Path, action='append', required=True,
                        help='Explicit erhai package from a matching component build; repeat as needed')
    parser.add_argument('--output', type=Path, required=True, help='New output directory')
    parser.add_argument('--cache', type=Path, default=WS / 'cache/desktop-rootfs')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--timeout', type=int, default=1800, help='Container assembly limit in seconds')
    args = parser.parse_args()
    if args.jobs < 1 or args.timeout < 1:
        parser.error('--jobs and --timeout must be positive')
    lock_path = REPO / 'packaging/desktop/source.json'
    lock = json.loads(lock_path.read_text())
    for spec in lock['layers']:
        path = args.layers.resolve() / Path(spec['path']).name
        if sha256(path) != spec['sha256']:
            parser.error(f'{path} is not the pinned original Ubuntu layer')
    selected = {}
    selected_paths = {}
    for path in args.device_deb:
        path = path.resolve()
        info = metadata(path)
        name = info['Package']
        if not name.startswith('erhai-') or info['Architecture'] not in ('arm64', 'all'):
            parser.error(f'{path}: expected an arm64/all erhai device package')
        if name in selected:
            parser.error(f'duplicate package input: {name}')
        selected_paths[name] = path
        selected[name] = {'file': path.name, 'sha256': sha256(path), **info}
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / 'repo').mkdir()
    (out / 'native').mkdir()
    assembly_script = out / 'assemble.local.sh'
    assembly_script.write_bytes((REPO / 'tools/lib/desktop-rootfs.sh').read_bytes())
    cache = args.cache.resolve()
    runtime = [fetch(p['url'], cache / p['file'], p['sha256'])
               for p in lock['runtime_packages']]
    native = [fetch(p['url'], cache / p['file'], p['sha256'])
              for p in lock['build_host']['packages']]

    # Immutable archive inputs may share an inode with the download/build cache.
    # Inputs on another filesystem fall back to an ordinary file copy.
    def stage(source, destination):
        try:
            os.link(source, destination)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            shutil.copyfile(source, destination)

    for i, path in enumerate(runtime + list(selected_paths.values())):
        stage(path, out / 'repo' / f'{i:04d}.deb')
    for i, path in enumerate(native):
        stage(path, out / 'native' / f'{i:04d}.deb')
    with (out / 'repo/Packages').open('wb') as index, (out / 'repo-index.log').open('wb') as log:
        run(['dpkg-scanpackages', '--multiversion', '.'], cwd=out / 'repo',
            stdout=index, stderr=log)
    seeds = [f'{name}={info["Version"]}' for name, info in selected.items()]
    seeds += lock['runtime_seeds']
    host_image = lock['build_host']['image']
    image_info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', host_image]))[0]
    if image_info['Architecture'] != lock['build_host']['architecture']:
        parser.error('the assembly container architecture does not match the tool lock')
    inputs = {'source_lock_sha256': sha256(lock_path),
              'integration_commit': subprocess.check_output(
                  ['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip(),
              'integration_dirty': bool(subprocess.check_output(
                  ['git', '-C', str(REPO), 'status', '--porcelain'], text=True)),
              'source_files_sha256': {str(p.relative_to(REPO)): sha256(p) for p in (
                  Path(__file__).resolve(), REPO / 'tools/lib/desktop-rootfs.sh',
                  REPO / 'tools/lib/build_root.py', lock_path)},
              'ubuntu': {'iso': lock['iso'], 'layers': lock['layers']},
              'build_host': lock['build_host'], 'build_host_id': image_info['Id'],
              'device_packages': selected, 'runtime_packages': lock['runtime_packages'],
              'requested_packages': seeds,
              'dpkg_scanpackages_sha256': sha256(shutil.which('dpkg-scanpackages'))}
    (out / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
    name = 'erhai-desktop-build-' + uuid.uuid4().hex[:12]
    command = ['docker', 'run', '--rm', '--name', name, '--network', 'none',
               '--cap-add', 'SYS_ADMIN', '--security-opt', 'apparmor=unconfined',
               '--volume', f'{out}:/work',
               '--volume', f'{args.layers.resolve()}:/layers:ro',
               '--volume', f'{assembly_script}:/assemble:ro',
               host_image, '/bin/bash', '/assemble', str(args.jobs), *seeds]
    (out / 'build-command.local.json').write_text(json.dumps(command, indent=2) + '\n')
    started = time.monotonic()
    try:
        with (out / 'build.log').open('w') as log:
            run(command, stdout=log, stderr=subprocess.STDOUT, timeout=args.timeout)
    except BaseException:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True)
        raise
    count = make_file_manifest(out)
    result = {'status': 'OFFLINE_ASSEMBLED_NOT_DEVICE_TESTED',
              'elapsed_seconds': time.monotonic() - started, 'files': count,
              'rootfs_sha256': sha256(out / 'rootfs.squashfs'),
              'artifacts_sha256': {p.name: sha256(p) for p in (
                  out / 'inputs.json', out / 'rootfs-files.jsonl.gz',
                  out / 'rootfs-xattrs.dump', out / 'rootfs-packages.txt',
                  out / 'audit.txt', out / 'diversions.txt')},
              'scope': 'Official Desktop originals plus APT-installed device/runtime packages; '
                       'no machine data injection, partition activation or hardware validation.'}
    (out / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
