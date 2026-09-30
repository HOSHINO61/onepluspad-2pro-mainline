#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Package a mainline first-boot candidate: kernel Image + erhai DTB + RAM initramfs.

The device boot contract is header v2 with the three components delivered by
ABL: kernel, ramdisk and --dtb. Output identity records the kernel commit,
config fragment, every input hash and the ABL overlay sink layout read back
from the DTB (tools/lib/abl_layout.py). A DTB with the legacy root-level sink
is only taken with --legacy-sink: that layout is for fallback and comparison.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from lib.abl_layout import LayoutError, add_arguments as add_layout_arguments, \
    check_choice, sink_layout
from lib.boot_profiles import CMDLINE, PROFILE_EXTRA

REPO = Path(__file__).resolve().parent.parent
# Workspace layout: when this repo is checked out at <workspace>/public/<name>,
# shared inputs and build outputs live in the workspace root; standalone
# checkouts keep everything inside the repo. ERHAI_WORKSPACE overrides both.
if (REPO.parent.parent / 'AGENTS.md').is_file() and (REPO.parent.parent / 'kernel/linux').is_dir():
    WS = Path(os.environ.get('ERHAI_WORKSPACE', REPO.parent.parent)).resolve()
else:
    WS = Path(os.environ.get('ERHAI_WORKSPACE', str(REPO))).resolve()
KERNEL_GIT = WS / 'kernel/linux'
DEFAULT_OUT = WS / 'out/kernel-firstboot'
# AOSP mkbootimg, vendored at cache/tools/mkbootimg.py (see README inputs).
MKBOOT = Path(os.environ.get('MKBOOTIMG', str(WS / 'cache/tools/mkbootimg.py')))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New output directory')
    parser.add_argument('--kernel-out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--initramfs', type=Path,
                        default=WS / 'out/initramfs-dev/initramfs-ncm.cpio.gz')
    parser.add_argument('--dtb', type=Path)
    parser.add_argument('--cmdline-extra', default='',
                        help='Appended to the standard cmdline (e.g. erhai.watchdog=1800 '
                             'to hold a demo session longer than 600s)')
    parser.add_argument('--profile', choices=tuple(PROFILE_EXTRA),
                        help='Append a cmdline policy: "desktop" runs a RAM desktop '
                             'session, "persistent" boots the installed UFS root')
    parser.add_argument('--rootfs', type=Path,
                        help='RAM desktop squashfs to hash; requires --profile desktop')
    parser.add_argument('--rootfs-url',
                        help='HTTP URL serving that squashfs to the tablet')
    add_layout_arguments(parser)
    args = parser.parse_args()
    rootfs = None
    if args.profile == 'desktop':
        if not args.rootfs or not args.rootfs_url:
            parser.error('--profile desktop requires --rootfs and --rootfs-url')
        if not args.rootfs_url.startswith(('http://', 'https://')) or any(
                c.isspace() or c in '\x00"' for c in args.rootfs_url):
            parser.error('--rootfs-url must be one HTTP(S) URL without whitespace or quotes')
        if not args.rootfs.is_file():
            parser.error(f'Missing input: {args.rootfs}')
        if any(token.startswith(('erhai.rootfs=', 'erhai.rootfs.sha256=', 'erhai.root='))
               for token in args.cmdline_extra.split()):
            parser.error('RAM desktop root inputs must use --rootfs and --rootfs-url')
        with args.rootfs.open('rb') as stream:
            rootfs = {'url': args.rootfs_url,
                      'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}
    elif args.rootfs or args.rootfs_url:
        parser.error('--rootfs and --rootfs-url require --profile desktop')
    cmdline = CMDLINE
    if args.profile:
        cmdline += ' ' + PROFILE_EXTRA[args.profile]
    if rootfs:
        cmdline += f' erhai.rootfs={rootfs["url"]} erhai.rootfs.sha256={rootfs["sha256"]}'
    if args.cmdline_extra.strip():
        cmdline += ' ' + args.cmdline_extra.strip()
    kout = args.kernel_out.resolve()
    image = kout / 'arch/arm64/boot/Image'
    dtb = args.dtb or kout / 'arch/arm64/boot/dts/qcom/sm8750-erhai.dtb'
    initramfs = args.initramfs.resolve()
    for path in (image, dtb, initramfs):
        if not path.is_file():
            parser.error(f'Missing input: {path}')
    try:
        layout = check_choice(sink_layout(dtb.read_bytes()), args.sink_layout,
                              allow_none=True)
    except LayoutError as error:
        parser.error(f'{dtb}: {error}')

    head = subprocess.run(['git', '-C', str(KERNEL_GIT), 'rev-parse', 'HEAD'],
                          capture_output=True, check=True, text=True).stdout.strip()
    dirty = subprocess.run(['git', '-C', str(KERNEL_GIT), 'status', '--porcelain'],
                           capture_output=True, check=True, text=True).stdout.strip()
    if dirty:
        parser.error(f'Kernel tree is dirty; commit first so the candidate identifies real code:\n{dirty}')

    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    inputs = {'Image': image, 'sm8750-erhai.dtb': dtb, 'initramfs.cpio.gz': initramfs}
    hashes = {name: sha(path) for name, path in inputs.items()}
    boot = out / 'boot-mainline.img'
    subprocess.run(['python3', str(MKBOOT), '--header_version', '2', '--pagesize', '4096',
                    '--base', '0', '--kernel_offset', '0x00008000',
                    '--ramdisk_offset', '0x01000000', '--tags_offset', '0x00000100',
                    '--dtb_offset', '0x01f00000',
                    '--kernel', str(image), '--ramdisk', str(initramfs),
                    '--dtb', str(dtb), '--os_version', '15.0.0',
                    '--os_patch_level', '2026-07', '--cmdline', cmdline,
                    '--output', str(boot)], check=True)
    assert boot.stat().st_size <= 100663296, 'exceeds boot partition capacity'
    manifest = {'status': 'OFFLINE_CANDIDATE_NOT_DEVICE_TESTED',
                'kernel_commit': head, 'kernel_out': str(kout),
                'cmdline': cmdline, 'inputs_sha256': hashes,
                'abl_sink_layout': layout,
                'boot_sha256': sha(boot), 'boot_size': boot.stat().st_size,
                'scope': 'fastboot boot only (header v2, ABL delivers kernel/ramdisk/dtb); '
                         'RAM userspace with NCM/HTTP evidence, telnet end, watchdog self-recovery.'}
    if rootfs:
        manifest['ram_rootfs'] = rootfs
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({k: manifest[k] for k in ['status', 'kernel_commit', 'abl_sink_layout',
                                                   'boot_sha256', 'boot_size']}, indent=2))


if __name__ == '__main__':
    main()
