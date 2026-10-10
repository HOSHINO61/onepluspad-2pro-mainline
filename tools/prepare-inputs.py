#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare pinned build inputs without accessing a tablet or extracting a ROM."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

from lib.build_root import REPO, WS, fetch, sha256


def read_json(path):
    return json.loads(path.read_text())


def verify(path, expected):
    if not path.is_file() or sha256(path) != expected:
        raise SystemExit(f'Input does not match its manifest: {path}')


def prepare_tools():
    inputs = read_json(REPO / 'kernel/source.json')['tool_inputs']
    cache = WS / 'cache'
    tools = cache / 'tools'
    tools.mkdir(parents=True, exist_ok=True)
    for name in ('busybox-arm64', 'mkbootimg.py', 'avbtool.py'):
        spec = inputs[name]
        if 'bundled_archive' in spec:
            archive = REPO / spec['bundled_archive']
            verify(archive, spec['archive_sha256'])
        else:
            archive = fetch(spec['url'], cache / 'downloads' / spec['archive'],
                            spec['archive_sha256'])
        target = WS / spec['destination']
        if name == 'busybox-arm64':
            with tempfile.TemporaryDirectory(dir=cache) as work:
                subprocess.run(['dpkg-deb', '--extract', str(archive), work], check=True)
                shutil.copyfile(Path(work) / spec['archive_path'], target)
        else:
            with tarfile.open(archive) as source:
                if name == 'mkbootimg.py':
                    source.extractall(tools, filter='data')
                else:
                    target.write_bytes(source.extractfile(spec['archive_path']).read())
        target.chmod(0o755)
        verify(target, spec['sha256'])
        print(f'Prepared {target.relative_to(WS)}', flush=True)
    audio = read_json(REPO / 'packaging/audio/source.json')
    archive = REPO / audio['bundled_archive']
    verify(archive, audio['sha256'])
    shutil.copyfile(archive, cache / audio['archive'])


def prepare_stock():
    directory = REPO / 'packaging/boot-reference'
    spec = read_json(directory / 'source.json')
    archive = directory / spec['archive']
    verify(archive, spec['archive_sha256'])
    destination = WS / spec['destination']
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as source:
        for entry in spec['files']:
            path = destination / entry['path']
            if path.is_file() and sha256(path) == entry['sha256']:
                continue
            source.extract(entry['path'], destination, filter='data')
            verify(path, entry['sha256'])
    print(f'Prepared stock build inputs for {spec["release"]}', flush=True)


def prepare_desktop():
    spec = read_json(REPO / 'packaging/desktop/source.json')
    directory = WS / 'cache/ubuntu-desktop'
    iso = fetch(spec['iso']['url'], directory / 'ubuntu-desktop-arm64.iso',
                spec['iso']['sha256'])
    missing = [layer['path'] for layer in spec['layers']
               if not (directory / layer['path']).is_file()
               or sha256(directory / layer['path']) != layer['sha256']]
    if missing:
        subprocess.run(['7z', 'x', '-y', f'-o{directory}', str(iso), *missing], check=True)
    for layer in spec['layers']:
        verify(directory / layer['path'], layer['sha256'])
    print(f'Desktop layers: {directory / "casper"}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop', action='store_true',
                        help='Also download the large Ubuntu Desktop ISO and extract its layers')
    args = parser.parse_args()
    prepare_stock()
    prepare_tools()
    if args.desktop:
        prepare_desktop()
    print('Inputs ready. Device firmware is included in packaging/firmware/.')


if __name__ == '__main__':
    main()
