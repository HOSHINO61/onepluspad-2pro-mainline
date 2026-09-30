#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build and package erhai-mesa on a host that is not ARM64, without root.

    tools/build-mesa-root.py --output <dir> [--work <dir>] [--jobs N] [--clean]

tools/build-mesa.py and tools/package-mesa.py need Ubuntu 26.04 arm64. Here
they run unchanged inside a disposable arm64 build root: the Ubuntu Base and
the archive snapshot pinned in packaging/mesa/build-root.json, entered through
an unprivileged user namespace and run by qemu-user binfmt, in the same way as
tools/build-sensors.py. The Mesa archive and patch stay pinned only in
packaging/mesa/source.json; the archive is downloaded into the cache once and
checked by SHA-256 on every use.

Each run builds from a fresh source tree and packages from that build; no
earlier build or package is read. The build root is kept in the work
directory for the next run of the same inputs; changed inputs need a new work
directory, and --clean removes it after a successful build. The output holds
the package, its manifest, the build identity and a record of the build root.
"""
import argparse
import fcntl
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

REPO = Path(__file__).resolve().parents[1]
INPUTS = REPO / 'packaging/mesa'
# The recipe copied into the build root: exactly what the native build uses.
RECIPE = ('tools/build-mesa.py', 'tools/package-mesa.py', 'packaging/mesa', 'packaging/erhai-mesa')
BINFMT = Path('/proc/sys/fs/binfmt_misc/qemu-aarch64')

# The unprivileged build-root helpers are shared with the sensors package.
_spec = importlib.util.spec_from_file_location('build_sensors', REPO / 'tools/build-sensors.py')
root_tools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(root_tools)
WS = root_tools.WS


def die(message):
    raise SystemExit(f'build-mesa-root: {message}')


def interpreter():
    """The qemu-user binary that runs the build root, for the build record."""
    fields = dict(line.replace(':', '').split(' ', 1) for line in BINFMT.read_text().splitlines()
                  if ' ' in line)
    path = Path(fields['interpreter'].strip()).resolve()
    version = subprocess.run([str(path), '--version'], capture_output=True, text=True).stdout
    return {'path': str(path), 'sha256': root_tools.sha256(path),
            'version': version.splitlines()[0] if version else '', 'flags': fields.get('flags', '').strip()}


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, required=True,
                        help='new directory for the package and its records')
    parser.add_argument('--work', type=Path, default=WS / 'out/mesa-root-build')
    parser.add_argument('--cache', type=Path, default=WS / 'cache/mesa')
    parser.add_argument('--jobs', type=int, default=6)
    parser.add_argument('--clean', action='store_true',
                        help='remove the work directory, build root included, after success')
    args = parser.parse_args()
    if not 1 <= args.jobs <= 8:
        parser.error('--jobs must be between 1 and 8, the limit of tools/build-mesa.py')
    if shutil.which('unshare') is None:
        die('unshare is required')
    if not BINFMT.is_file():
        die('arm64 binfmt (qemu-user-static) is required to run the build root')
    if not root_tools.HOST_CA.is_file():
        die(f'{root_tools.HOST_CA} is required for TLS to the snapshot service')

    source = json.loads((INPUTS / 'source.json').read_text())
    pins = json.loads((INPUTS / 'build-root.json').read_text())
    base = root_tools.fetch(pins['build_root']['url'], WS / 'cache' / pins['build_root']['archive'],
                            pins['build_root']['sha256'])
    archive = root_tools.fetch(source['source_url'], args.cache / source['archive'], source['sha256'])

    output = args.output.resolve()
    if output.exists():
        die(f'{output} exists; select a new --output')
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    with open(work / '.lock', 'w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        log = work / 'build.log'
        log.write_text('')
        root = root_tools.prepare_root(work, pins, base, log)
        build = root / 'build'
        if build.exists():
            shutil.rmtree(build)
        for name in RECIPE:
            path = REPO / name
            if path.is_dir():
                shutil.copytree(path, build / 'recipe' / name,
                                ignore=shutil.ignore_patterns('__pycache__'))
            else:
                (build / 'recipe' / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, build / 'recipe' / name)
        (build / 'inputs').mkdir()
        shutil.copyfile(archive, build / 'inputs' / source['archive'])
        print(f'  building Mesa {source["version"]} (desktop profile) and packaging it '
              f'under qemu-user; progress in {log}', flush=True)
        root_tools.chroot(root, (
            f'python3 -u /build/recipe/tools/build-mesa.py --profile desktop --jobs {args.jobs} '
            f'--source-archive /build/inputs/{source["archive"]} --output /build/out\n'
            'python3 -u /build/recipe/tools/package-mesa.py --build-output /build/out --output /build/debs\n'),
            log=log)

        installed = root_tools.capture(root, "dpkg-query -W -f='${Package} ${Version}\\n'").splitlines()
        output.mkdir(parents=True)
        manifest = json.loads((build / 'debs/manifest.json').read_text())
        package = build / 'debs' / manifest['package']['file']
        if root_tools.sha256(package) != manifest['package']['sha256']:
            die('the package does not match its manifest')
        for path in (package, build / 'debs/manifest.json', build / 'out/input.json',
                     build / 'out/build-result.json', build / 'out/build/meson-logs/meson-log.txt'):
            shutil.copy2(path, output / path.name)
        # One entry per recipe file, keyed by its repository path.
        recipe = {str(path.relative_to(REPO)): root_tools.sha256(path)
                  for name in RECIPE
                  for path in ([REPO / name] if (REPO / name).is_file()
                               else sorted((REPO / name).rglob('*')))
                  if path.is_file() and '__pycache__' not in path.parts}
        recipe['tools/build-mesa-root.py'] = root_tools.sha256(Path(__file__))
        record = {'build_root': pins['build_root'], 'apt_snapshot': pins['apt']['snapshot'],
                  'build_root_pins_sha256': root_tools.sha256(INPUTS / 'build-root.json'),
                  'recipe_sha256': recipe, 'interpreter': interpreter(),
                  'build_packages': installed, 'package': manifest['package']}
        (output / 'build-root.json').write_text(json.dumps(record, indent=2) + '\n')
        shutil.rmtree(build)
    if args.clean:
        shutil.rmtree(work)
    print(json.dumps(manifest['package']))


if __name__ == '__main__':
    main()
