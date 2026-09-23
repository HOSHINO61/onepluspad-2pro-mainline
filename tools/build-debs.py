#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build the erhai device .deb set from pinned inputs, without root.

The delivered root filesystem is Canonical's Ubuntu, unpacked as it ships and
free to follow upstream through apt. Everything this tablet needs on top of it
is a package, and each package owns exactly what it installs:

    erhai-device-support  the dual-boot switcher, its store and log rotation,
                          the desktop entry and polkit action for the Android
                          direction, and the power settings this port needs
                          until suspend/resume works
    erhai-kernel          the signed boot/init_boot/vendor_boot triplet; its
                          postinst hands the set to the switcher's installer,
                          so a kernel update is an apt upgrade
    erhai-firmware        the firmware closure the mainline drivers ask for
    erhai-device          a metapackage depending on the three

Inputs are pinned, never inherited: the kernel comes from a clean checkout at a
named commit and the firmware from packaging/firmware/, every file of which is
checked against the sha256 and size recorded in packaging/firmware-manifest.json
before it is packed. Nothing here reads a previous build's output, and building
erhai-firmware needs neither the ROM cache nor the network.

    tools/build-debs.py --avb-key <key>.pem --avbtool <avbtool.py>

    --debug              build the triplet with the debug channel enabled and
                         mark the version ~dbg. Off by default: the persistent
                         install ships without an unauthenticated root telnet.
    --triplet-signed D   use an already-signed triplet instead of building one
                         (no kernel build, no AVB key needed)
    --refresh-from-rom   re-extract every firmware file from the pinned stock
                         ROM images and upstream archives and diff the result
                         against packaging/firmware/; nothing is packed. With
                         --refresh-apply the new bytes and their hashes are
                         taken into the tree -- this is how a later ROM version
                         gets in.

Versions
--------

    <release>[~dbg]+g<kernel commit>.b<build id>
    0.1.4+g1e4124bb816d.bf2655cee       0.1.4~dbg+g1e4124bb816d.b9a8a5a08

<release> comes from packaging/VERSION and is bumped by hand for each release
meant to install over the last one. It is the only part dpkg's ordering ever
reaches, because every build of one release carries the same one: the earlier
scheme put a payload digest where the counter belongs, so half of all new
builds sorted *below* the installed package and apt called them downgrades.

The rest names the build rather than ordering it. <kernel commit> is the
kernel the triplet was built from, so `dpkg -l` says which kernel is installed
without opening a package; it is left out when the triplet came in already
signed and its commit is therefore unknown. <build id> is a digest of
everything the four packages contain -- each staged payload *and* each
package's DEBIAN templates as they read before @VERSION@ is filled in, so a
changed description or maintainer script produces a new id where before only
payload bytes did. The version cannot be part of its own seed, which is why it
is the templates and not the finished control files that go in.

~dbg sorts below the plain release, so at one release counter the product
build installs over the debug build and not the other way round: a debug build
carries an unauthenticated root telnet, and leaving it in place should take a
deliberate bump rather than happen by ordering accident.

Two builds from the same inputs still produce the same four files byte for
byte; nothing in the version is drawn from the clock or the build host.

The AVB signing key and avbtool stay on the build host. They are inputs to the
build, never contents of a package.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# Workspace layout: when this repo is checked out at <workspace>/public/<name>,
# shared inputs and build outputs live in the workspace root; standalone
# checkouts keep everything inside the repo. ERHAI_WORKSPACE overrides both.
if (REPO.parent.parent / 'AGENTS.md').is_file() and (REPO.parent.parent / 'kernel/linux').is_dir():
    WS = Path(os.environ.get('ERHAI_WORKSPACE', REPO.parent.parent)).resolve()
else:
    WS = Path(os.environ.get('ERHAI_WORKSPACE', str(REPO))).resolve()

PACKAGING = REPO / 'packaging'
FIRMWARE = PACKAGING / 'firmware'
MANIFEST = PACKAGING / 'firmware-manifest.json'
VERSION_FILE = PACKAGING / 'VERSION'
MAINTAINER = 'Erwin <yzddmr7@gmail.com>'
DEBIAN_SCRIPTS = ('preinst', 'postinst', 'prerm', 'postrm')
PACKAGES = ('erhai-display-power', 'erhai-device-support', 'erhai-firmware', 'erhai-kernel', 'erhai-device')
PARTS = ('boot', 'init_boot', 'vendor_boot')
SWITCHER_PROGRAMS = ('erhai-switch', 'erhai-switch-install-ubuntu-images')


def die(message):
    raise SystemExit(f'build-debs: {message}')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        die(f'{command[0]} failed: {" ".join(str(c) for c in command)}\n'
            f'{result.stderr or result.stdout}')
    return result.stdout


# --------------------------------------------------------------------------
# Firmware
#
# The binaries live in packaging/firmware/, laid out exactly as they install
# under /usr/lib/firmware, and packaging/firmware-manifest.json is the per-file
# record of where each one came from and what it must hash and weigh. A build
# copies from the tree and verifies against the manifest; it never reaches for
# the ROM cache or the network.
#
# --refresh-from-rom is the other direction, for a later ROM version: extract
# the closure again from the pinned inputs and diff it against the tree. Four
# kinds of input, none of them a previous build's output:
#   archive  an upstream tarball, by member path
#   fat      a stock ROM partition image (FAT), read with mtools, no mount and
#            so no privileges
#   dtb      an Android dtbo image; the touch firmware is a property inside one
#            of its overlays, which is where the vendor keeps it
#   url      a single upstream file, cached under cache/ by its pinned hash


FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9
FDT_MAGIC = 0xd00dfeed
DT_TABLE_MAGIC = 0xd7b7ab1e


def fdt_find_property(fdt, node_name, prop_name):
    """Value of <prop_name> on the first node called <node_name>, or None."""
    magic, _total, off_struct, off_strings = struct.unpack('>4I', fdt[:16])
    if magic != FDT_MAGIC:
        return None
    size_struct = struct.unpack('>I', fdt[36:40])[0]
    offset, end, path = off_struct, off_struct + size_struct, []
    while offset < end:
        token, = struct.unpack('>I', fdt[offset:offset + 4])
        offset += 4
        if token == FDT_BEGIN_NODE:
            stop = fdt.index(b'\0', offset)
            path.append(fdt[offset:stop].decode())
            offset = (stop + 1 + 3) & ~3
        elif token == FDT_END_NODE:
            if path:
                path.pop()
        elif token == FDT_PROP:
            length, name_off = struct.unpack('>II', fdt[offset:offset + 8])
            offset += 8
            start = off_strings + name_off
            name = fdt[start:fdt.index(b'\0', start)].decode()
            value = fdt[offset:offset + length]
            offset = (offset + length + 3) & ~3
            if name == prop_name and path and path[-1] == node_name:
                return value
        elif token == FDT_END:
            break
    return None


def dtbo_entries(image):
    magic, _total, _hdr, entry_size, entry_count, entries_offset = \
        struct.unpack('>6I', image[:24])
    if magic != DT_TABLE_MAGIC:
        die('dtbo image does not start with a dt_table_header')
    for index in range(entry_count):
        base = entries_offset + index * entry_size
        size, offset = struct.unpack('>II', image[base:base + 8])
        yield index, image[offset:offset + size]


def extract_from_dtb(source_path, spec, target):
    image = source_path.read_bytes()
    for _index, fdt in dtbo_entries(image):
        value = fdt_find_property(fdt, spec['node'], spec['property'])
        if value is not None:
            target.write_bytes(value)
            return
    die(f'no {spec["node"]}/{spec["property"]} in any overlay of {source_path.name}')


def extract_from_fat(source_path, spec, target):
    if shutil.which('mcopy') is None:
        die('mtools (mcopy) is required to read the stock FAT partition images')
    environment = dict(os.environ, MTOOLS_SKIP_CHECK='1')
    run(['mcopy', '-i', str(source_path), '-n', '-o', spec['member'], str(target)],
        env=environment)


def extract_from_archive(source_path, spec, target):
    import tarfile
    with tarfile.open(source_path) as archive:
        try:
            member = archive.extractfile(spec['member'])
        except KeyError:
            member = None
        if member is None:
            die(f'{source_path.name} has no member {spec["member"]}')
        with open(target, 'wb') as handle:
            shutil.copyfileobj(member, handle)


def fetch_url(url, target, expected):
    """Download once into the pinned cache; a cached file must still hash right."""
    if target.is_file() and (expected is None or sha256_file(target) == expected):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f'  fetching {url}')
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    target.write_bytes(data)


def firmware_sources(manifest, adopt):
    """Resolve and hash-check every pinned input the manifest names.

    Only --refresh-from-rom needs these. An ordinary build reads the tree.
    """
    resolved = {}
    for name, entry in manifest['inputs'].items():
        if entry['kind'] == 'url-base':
            resolved[name] = entry
            continue
        path = WS / entry['path']
        if not path.is_file():
            die(f'pinned firmware input is missing: {entry["path"]} '
                f'({entry.get("origin", "see packaging/firmware-manifest.json")})')
        digest = sha256_file(path)
        if adopt:
            entry['sha256'] = digest
        elif digest != entry['sha256']:
            die(f'{entry["path"]} is {digest}, the manifest pins {entry["sha256"]}')
        resolved[name] = dict(entry, resolved_path=path)
    return resolved


def extract_firmware(manifest, sources, base, adopt):
    """Extract the closure from the pinned inputs into <base>."""
    for spec in manifest['files']:
        source = sources[spec['from']]
        target = base / spec['install']
        target.parent.mkdir(parents=True, exist_ok=True)
        if source['kind'] == 'archive':
            extract_from_archive(source['resolved_path'], spec, target)
        elif source['kind'] == 'fat':
            extract_from_fat(source['resolved_path'], spec, target)
        elif source['kind'] == 'dtb':
            extract_from_dtb(source['resolved_path'], spec, target)
        elif source['kind'] == 'url-base':
            cached = WS / source['cache'] / spec['member']
            fetch_url(source['base_url'] + spec['member'], cached,
                      None if adopt else spec.get('sha256'))
            shutil.copyfile(cached, target)
        else:
            die(f'unknown firmware input kind: {source["kind"]}')
        target.chmod(0o644)


def tracked_firmware():
    """Every firmware file in the tree, by install path; README.md is prose."""
    if not FIRMWARE.is_dir():
        return set()
    return {path.relative_to(FIRMWARE).as_posix()
            for path in FIRMWARE.rglob('*')
            if path.is_file() and path.name != 'README.md'}


def refresh_from_rom(manifest, adopt):
    """Extract the closure again from the pinned inputs and diff it against the tree.

    This is the door a later ROM version comes through: extract, read what
    moved, and with --refresh-apply take the new bytes and their hashes in.
    Nothing is packed here, and no ordinary build runs it.
    """
    sources = firmware_sources(manifest, adopt)
    work = Path(tempfile.mkdtemp(prefix='erhai-firmware.'))
    try:
        extract_firmware(manifest, sources, work, adopt)
        unchanged, changed, added = [], [], []
        for spec in manifest['files']:
            extracted = work / spec['install']
            digest, size = sha256_file(extracted), extracted.stat().st_size
            repo = FIRMWARE / spec['install']
            if not repo.is_file():
                added.append(spec['install'])
            elif sha256_file(repo) == digest:
                unchanged.append(spec['install'])
                if spec.get('sha256') != digest or spec.get('size') != size:
                    changed.append(spec['install'])
                continue
            else:
                changed.append(spec['install'])
            if adopt:
                repo.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(extracted, repo)
                repo.chmod(0o644)
        if adopt:
            for spec in manifest['files']:
                extracted = work / spec['install']
                spec['sha256'] = sha256_file(extracted)
                spec['size'] = extracted.stat().st_size
    finally:
        shutil.rmtree(work, ignore_errors=True)

    stale = sorted(tracked_firmware() - {s['install'] for s in manifest['files']})
    for install in sorted(changed):
        print(f'  changed: {install}')
    for install in sorted(added):
        print(f'  new:     {install}')
    for install in stale:
        print(f'  stale:   {install} (in the tree, not in the manifest)')
    print(f'refresh-from-rom: {len(unchanged)} unchanged, {len(changed)} changed, '
          f'{len(added)} new, {len(stale)} stale')
    if adopt:
        MANIFEST.write_text(json.dumps(manifest, indent=2) + '\n')
        print(f'wrote {len(changed) + len(added)} files under '
              f'{FIRMWARE.relative_to(REPO)} and refreshed '
              f'{MANIFEST.relative_to(REPO)}')
        if stale:
            die('remove the stale files by hand; this tool does not delete')
    elif changed or added or stale:
        die('packaging/firmware does not match the pinned inputs; '
            '--refresh-apply takes the difference in')


# --------------------------------------------------------------------------
# Package staging


def install_file(source, target, mode):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(mode)


def copy_tree(source, root):
    """Pack a packaging tree as it is checked out, executable bits and all.

    Git records the executable bit, so a program that lives in the tree -- a
    unit's ExecStart, say -- arrives installable without the build script
    having to carry a list of which files are programs.
    """
    for entry in sorted(source.rglob('*')):
        if entry.is_dir():
            continue
        if entry.is_symlink():
            die(f'packaging tree carries a symlink, which is not packed: {entry}')
        # Bytecode caches are not part of the package. Running one of the
        # tree's own programs from the checkout leaves a __pycache__ beside
        # it, and it would otherwise be packed into /usr/sbin.
        if '__pycache__' in entry.parts or entry.suffix == '.pyc':
            continue
        mode = 0o755 if entry.stat().st_mode & 0o100 else 0o644
        install_file(entry, root / entry.relative_to(source), mode)


def stage_device_support(root):
    copy_tree(PACKAGING / 'erhai-device-support/tree', root)
    for program in SWITCHER_PROGRAMS:
        install_file(REPO / 'switch' / program, root / 'usr/sbin' / program, 0o755)
    # The store itself: the package owns the directory, never its contents.
    # What lives inside is state -- the triplets, the log, state.json -- and
    # belongs to the switcher and to erhai-kernel's postinst.
    (root / 'var/lib/erhai/switch').mkdir(parents=True, exist_ok=True)


def stage_display_power(root):
    copy_tree(PACKAGING / 'erhai-display-power/tree', root)
    target = root / 'usr/lib/aarch64-linux-gnu/erhai/gsd-backlight-compat.so'
    target.parent.mkdir(parents=True, exist_ok=True)
    run(['aarch64-linux-gnu-gcc', '-std=c11', '-D_GNU_SOURCE', '-O2', '-Wall',
         '-Wextra', '-Werror', '-shared', '-fPIC', '-Wl,-z,relro,-z,now',
         '-Wl,-z,defs', '-o', str(target),
         str(PACKAGING / 'erhai-display-power/gsd-backlight-compat.c')])


def stage_firmware(root, manifest):
    """Copy the closure out of the tree, verifying every file on the way in."""
    base = root / 'usr/lib/firmware'
    for spec in manifest['files']:
        source = FIRMWARE / spec['install']
        if not source.is_file():
            die(f'firmware {spec["install"]} is not in '
                f'{FIRMWARE.relative_to(REPO)}; --refresh-from-rom '
                f'--refresh-apply puts it there')
        size = source.stat().st_size
        if size != spec['size']:
            die(f'firmware {spec["install"]} is {size} bytes, '
                f'the manifest pins {spec["size"]}')
        digest = sha256_file(source)
        if digest != spec['sha256']:
            die(f'firmware {spec["install"]} is {digest}, '
                f'the manifest pins {spec["sha256"]}')
        target = base / spec['install']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o644)
    # The manifest is the whole record, in both directions: a binary the tree
    # carries and it does not list has no recorded origin, so it is not packed.
    stale = sorted(tracked_firmware() - {s['install'] for s in manifest['files']})
    if stale:
        die(f'{FIRMWARE.relative_to(REPO)} holds files the manifest does not '
            f'list: {", ".join(stale)}')
    print(f'  firmware: {len(manifest["files"])} files from '
          f'{FIRMWARE.relative_to(REPO)}')


def build_triplet(args, work):
    """Kernel Image + ABL device tree + initramfs -> a signed boot triplet."""
    if args.triplet_signed:
        signed = args.triplet_signed.resolve()
        for name in PARTS:
            if not (signed / f'{name}.img').is_file():
                die(f'{signed} has no {name}.img')
        if not (signed / 'SHA256SUMS').is_file():
            die(f'{signed} has no SHA256SUMS')
        return signed, None

    if not args.avb_key or not args.avb_key.is_file():
        die('--avb-key is required to sign a freshly built triplet')
    unsigned = work / 'triplet'
    command = [sys.executable, str(REPO / 'tools/build-mainline-gki.py'),
               '--output', str(unsigned), '--profile', 'persistent',
               '--kernel-out', str(args.kernel_out), '--dtb', str(args.dtb),
               '--initramfs', str(args.initramfs)]
    if args.debug:
        command += ['--cmdline-extra', 'erhai.debug=1']
    print('  packaging the GKI triplet')
    run(command)

    signed = work / 'triplet-avb'
    signer = [sys.executable, str(REPO / 'tools/sign-boot-triplet.py'),
              '--triplet', str(unsigned), '--stock', str(args.stock),
              '--key', str(args.avb_key), '--output', str(signed)]
    if args.avbtool:
        signer += ['--avbtool', str(args.avbtool)]
    print('  adding the AVB hash footers')
    run(signer)
    return signed, json.loads((unsigned / 'manifest.json').read_text())


def stage_kernel(root, args, work, release):
    signed, unsigned_manifest = build_triplet(args, work)
    signed_manifest = json.loads((signed / 'manifest.json').read_text())
    images = root / 'usr/lib/erhai/boot' / release
    images.mkdir(parents=True, exist_ok=True)
    for name in PARTS:
        install_file(signed / f'{name}.img', images / f'{name}.img', 0o644)
    install_file(signed / 'SHA256SUMS', images / 'SHA256SUMS', 0o644)

    # A module tree only if the kernel actually builds modules. This
    # configuration builds none -- every driver this tablet needs is built in,
    # because the initramfs has no module loader -- and shipping an empty
    # /lib/modules/<release> would only invite depmod to disagree.
    modules = sorted(Path(args.kernel_out).rglob('*.ko'))
    if modules:
        die(f'the kernel built {len(modules)} modules; erhai-kernel does not '
            f'package a module tree yet')

    cmdline = (unsigned_manifest or {}).get('cmdline')
    meta = {
        'package': 'erhai-kernel',
        'kernel_release': release,
        'kernel_commit': (unsigned_manifest or {}).get('kernel_commit'),
        'cmdline': cmdline,
        'debug_channel': bool(cmdline and 'erhai.debug=1' in cmdline),
        'kernel_modules': 'none; every driver this tablet needs is built in',
        'inputs_sha256': (unsigned_manifest or {}).get('inputs_sha256'),
        'avb': {
            'algorithm': signed_manifest.get('algorithm'),
            'key_sha256': signed_manifest.get('key_sha256'),
            'partitions': {
                name: {
                    'partition_size': entry['footer']['partition_size'],
                    'rollback_index': entry['footer']['rollback_index'],
                    'stock_reference_sha256': entry['stock_reference']['sha256'],
                }
                for name, entry in signed_manifest['partitions'].items()
            },
        },
        'images_sha256': {name: signed_manifest['partitions'][name]['output_sha256']
                          for name in PARTS},
    }
    (images / 'meta.json').write_text(json.dumps(meta, indent=2) + '\n')
    (images / 'meta.json').chmod(0o644)
    return meta


# --------------------------------------------------------------------------
# Packing


def tree_digest(root):
    """A canonical digest of a staged payload: path, mode and content."""
    digest = hashlib.sha256()
    for entry in sorted(root.rglob('*')):
        relative = entry.relative_to(root).as_posix()
        if entry.is_dir():
            digest.update(f'd {relative} {entry.stat().st_mode & 0o7777:o}\n'.encode())
        else:
            digest.update(f'f {relative} {entry.stat().st_mode & 0o7777:o} '
                          f'{sha256_file(entry)}\n'.encode())
    return digest.hexdigest()


def metadata_digest(package, substitutions):
    """A canonical digest of what a package says about itself.

    The build id has to cover the DEBIAN side too -- a reworded description or
    an edited maintainer script is a different package -- but the finished
    control file holds the version, and a version cannot be part of its own
    seed. So the templates go in, as they read before @VERSION@ is filled in,
    together with every substitution that is not the version itself.
    """
    digest = hashlib.sha256()
    for name in ('control', *DEBIAN_SCRIPTS):
        source = PACKAGING / package / name
        if source.is_file():
            digest.update(f'{name} {sha256_file(source)}\n'.encode())
    for key in sorted(substitutions):
        digest.update(f'{key} {substitutions[key]}\n'.encode())
    return digest.hexdigest()


def read_release():
    """The release counter from packaging/VERSION: the orderable part of the version."""
    if not VERSION_FILE.is_file():
        die(f'{VERSION_FILE.relative_to(REPO)} is missing; it holds the release counter')
    lines = [line.strip() for line in VERSION_FILE.read_text().splitlines()]
    values = [line for line in lines if line and not line.startswith('#')]
    if len(values) != 1:
        die(f'{VERSION_FILE.relative_to(REPO)} must hold exactly one version line')
    release = values[0]
    # Debian upstream versions start with a digit; ~ and + are reserved here
    # for the debug marker and the build id this script appends.
    if not re.fullmatch(r'[0-9][0-9A-Za-z.]*', release):
        die(f'{VERSION_FILE.relative_to(REPO)} holds {release!r}, which is not a '
            f'release counter of the form 0.1.2')
    return release


def installed_size_kib(root):
    """What the payload costs on disk, in KiB; DEBIAN/ is not installed."""
    total = 0
    for entry in root.rglob('*'):
        if entry.is_relative_to(root / 'DEBIAN'):
            continue
        total += 4 if entry.is_dir() else (entry.stat().st_size + 1023) // 1024
    return total


def write_control(root, package, version, substitutions):
    debian = root / 'DEBIAN'
    debian.mkdir(parents=True, exist_ok=True)
    text = (PACKAGING / package / 'control').read_text()
    values = {'@VERSION@': version,
              '@INSTALLED_SIZE@': str(installed_size_kib(root)), **substitutions}
    for key, value in values.items():
        text = text.replace(key, value)
    leftover = re.findall(r'@[A-Z_]+@', text)
    if leftover:
        die(f'{package}/control still holds {leftover}')
    (debian / 'control').write_text(text)
    (debian / 'control').chmod(0o644)

    for script in DEBIAN_SCRIPTS:
        source = PACKAGING / package / script
        if not source.is_file():
            continue
        text = source.read_text()
        for key, value in values.items():
            text = text.replace(key, value)
        (debian / script).write_text(text)
        (debian / script).chmod(0o755)

    # Files under /etc are configuration: dpkg must keep local edits instead of
    # replacing them on upgrade.
    conffiles = sorted(f'/{p.relative_to(root).as_posix()}'
                       for p in (root / 'etc').rglob('*') if p.is_file()) \
        if (root / 'etc').is_dir() else []
    if conffiles:
        (debian / 'conffiles').write_text('\n'.join(conffiles) + '\n')
        (debian / 'conffiles').chmod(0o644)

    lines = []
    for entry in sorted(root.rglob('*')):
        if entry.is_dir() or entry.is_relative_to(debian):
            continue
        checksum = hashlib.md5(entry.read_bytes()).hexdigest()
        lines.append(f'{checksum}  {entry.relative_to(root).as_posix()}')
    if lines:
        (debian / 'md5sums').write_text('\n'.join(lines) + '\n')
        (debian / 'md5sums').chmod(0o644)


def source_date_epoch(kernel_out):
    """A fixed timestamp for the archive members, so two builds match byte for byte.

    dpkg-deb clamps every mtime newer than SOURCE_DATE_EPOCH to it, and the
    staged files are all newer, so the whole archive lands on one timestamp.
    The kernel commit is the natural choice: it is the newest real input.
    """
    if 'SOURCE_DATE_EPOCH' in os.environ:
        return os.environ['SOURCE_DATE_EPOCH']
    source = Path(kernel_out) / 'source'
    git = WS / 'kernel/linux'
    if git.is_dir() or source.is_dir():
        result = subprocess.run(['git', '-C', str(git), 'show', '-s', '--format=%ct', 'HEAD'],
                                capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip().isdigit():
            return result.stdout.strip()
    return '1'


def pack(root, package, version, architecture, out_dir, epoch):
    target = out_dir / f'{package}_{version}_{architecture}.deb'
    run(['dpkg-deb', '--root-owner-group', '--build', str(root), str(target)],
        env=dict(os.environ, SOURCE_DATE_EPOCH=epoch))
    return target


# --------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, default=WS / 'out/erhai-debs')
    parser.add_argument('--kernel-out', type=Path, default=WS / 'out/kernel-firstboot')
    parser.add_argument('--dtb', type=Path, default=WS / 'out/abl-dtb/erhai-abl.dtb',
                        help='ABL-compatible device tree (tools/build-erhai-abl-symbols.py)')
    parser.add_argument('--initramfs', type=Path,
                        default=WS / 'out/initramfs-dev/initramfs-ncm.cpio.gz')
    parser.add_argument('--stock', type=Path, default=WS / 'cache/stock-c34/images',
                        help='Stock images of the running firmware, for the AVB footers')
    parser.add_argument('--avb-key', type=Path,
                        help='RSA-4096 PEM signing key; a build-host input, never packaged')
    parser.add_argument('--avbtool', type=Path)
    parser.add_argument('--triplet-signed', type=Path,
                        help='Use this already-signed triplet instead of building one')
    parser.add_argument('--debug', action='store_true',
                        help='Enable the debug channel in the packaged kernel command '
                             'line and mark the version ~dbg')
    parser.add_argument('--refresh-from-rom', action='store_true',
                        help='Re-extract the firmware closure from the pinned ROM and '
                             'upstream inputs and diff it against packaging/firmware')
    parser.add_argument('--refresh-apply', action='store_true',
                        help='With --refresh-from-rom, take the difference into '
                             'packaging/firmware and the manifest')
    parser.add_argument('--only', choices=PACKAGES, action='append',
                        help='Build just these packages (repeatable)')
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text())
    if args.refresh_from_rom:
        refresh_from_rom(manifest, args.refresh_apply)
        return
    if args.refresh_apply:
        die('--refresh-apply only means something with --refresh-from-rom')

    if shutil.which('dpkg-deb') is None:
        die('dpkg-deb is required')
    wanted = tuple(args.only) if args.only else PACKAGES

    release_file = Path(args.kernel_out) / 'include/config/kernel.release'
    release = release_file.read_text().strip() if release_file.is_file() else None
    if 'erhai-kernel' in wanted:
        if not release:
            die(f'no kernel release at {release_file}; build the kernel first')
        if re.search(r'[^A-Za-z0-9._+-]', release):
            die(f'unsafe kernel release string: {release}')

    out_dir = args.output.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='erhai-debs.'))
    try:
        roots, kernel_meta = {}, None
        for package in wanted:
            print(f'staging {package}')
            root = work / package / 'root'
            root.mkdir(parents=True)
            if package == 'erhai-device-support':
                stage_device_support(root)
            elif package == 'erhai-display-power':
                stage_display_power(root)
            elif package == 'erhai-firmware':
                stage_firmware(root, manifest)
            elif package == 'erhai-kernel':
                kernel_meta = stage_kernel(root, args, work, release)
            roots[package] = root

        substitutions = {'@KERNEL_RELEASE@': release or '',
                         '@MAINTAINER@': MAINTAINER}

        # One build id for the set, derived from everything the set contains:
        # the staged payloads and the DEBIAN templates behind them. Two builds
        # from the same inputs get the same id, and a changed byte anywhere --
        # a firmware file, a unit, a description -- produces a new one. It
        # identifies the build; packaging/VERSION is what orders it.
        payloads = {package: tree_digest(root) for package, root in roots.items()}
        metadata = {package: metadata_digest(package, substitutions) for package in roots}
        seed = ''.join(f'{package} payload {payloads[package]} '
                       f'metadata {metadata[package]}\n' for package in sorted(roots))
        build_id = hashlib.sha256(seed.encode()).hexdigest()[:8]
        commit = (kernel_meta or {}).get('kernel_commit')
        stamp = f'+g{commit[:12]}.b{build_id}' if commit else f'+b{build_id}'
        # ~ sorts below everything, so the product build of a release installs
        # over its debug build and never the reverse.
        release_counter = read_release()
        version = release_counter + ('~dbg' if args.debug else '') + stamp

        epoch = source_date_epoch(args.kernel_out)
        built = []
        for package in wanted:
            architecture = 'arm64' if package in ('erhai-kernel', 'erhai-device', 'erhai-display-power') else 'all'
            write_control(roots[package], package, version, substitutions)
            built.append(pack(roots[package], package, version, architecture, out_dir, epoch))

        summary = {
            'version': version,
            'release': release_counter,
            'build_id': build_id,
            'source_date_epoch': epoch,
            'built': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'debug_channel': bool(args.debug),
            'kernel': kernel_meta,
            'firmware_files': len(manifest['files']),
            'packages': {path.name: {'sha256': sha256_file(path),
                                     'bytes': path.stat().st_size,
                                     'payload_sha256': payloads[path.name.split('_')[0]],
                                     'metadata_sha256': metadata[path.name.split('_')[0]]}
                         for path in built},
        }
        (out_dir / 'build-manifest.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(summary, indent=2))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
