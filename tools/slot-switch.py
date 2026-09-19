#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""A/B slot switcher for the OnePlus Pad 2 Pro (SM8750) dual-boot.

Qualcomm keeps the A/B boot slot in the GPT partition-entry attribute bits of
the boot partitions, laid out as AOSP's gpt-utils does (verified on this device
against `fastboot getvar slot-*`):

    bits 48-49 : priority (0-3, higher wins)
    bit  50    : active
    bits 51-53 : tries remaining (0-7)
    bit  54    : successful (this slot booted all the way at least once)
    bit  55    : unbootable

The ABL boots the boot partition that is active, highest priority and not
unbootable, decrementing tries until `successful` is set. Switching OS =
rewriting these bits on boot_a / boot_b and rebooting, which is what
`fastboot --set-active` does from the bootloader; this tool does it from a
running Linux so the tablet can switch back to Android on its own.

Three things this has to get right on real hardware:

  * the UFS on this device is 4Kn, so every LBA is scaled by the disk's own
    logical_block_size, never a hardcoded 512;
  * the boot partitions do not live on the data LUN -- the tool finds the LUN
    that actually carries boot_a/boot_b instead of assuming one;
  * both GPT copies are updated. Leaving the backup stale invites the
    bootloader (or any GPT repair) to undo the switch at the worst moment.

Usage:
    ./slot-switch.py --show                      # decode both copies, no writes
    ./slot-switch.py --disk /dev/sde --to a      # boot Android
    ./slot-switch.py --disk /dev/sde --to b      # boot the mainline slot
    ./slot-switch.py --disk dump.bin --show      # offline, against a GPT dump

Writing needs root. Only the two boot_* entries are ever modified.
"""
import argparse
import glob
import os
from pathlib import Path
import struct
import sys
import zlib

ATTR_PRIORITY_SHIFT = 48
ATTR_PRIORITY_MASK = 0x3
ATTR_ACTIVE_BIT = 50
ATTR_TRIES_SHIFT = 51
ATTR_TRIES_MASK = 0x7
ATTR_SUCCESSFUL_BIT = 54
ATTR_UNBOOTABLE_BIT = 55

MAX_PRIORITY = 3
MAX_TRIES = 7

GPT_SIGNATURE = b'EFI PART'
HEADER_BYTES = 512  # the on-disk header is always <= 512 bytes, LBA size aside


class GptError(Exception):
    pass


def sector_size_of(path):
    """Logical block size: from sysfs for a block device, probed for a file."""
    try:
        st = os.stat(path)
        if os.path.stat.S_ISBLK(st.st_mode):
            name = os.path.basename(os.path.realpath(path))
            sysfs = Path(f'/sys/class/block/{name}/queue/logical_block_size')
            if sysfs.is_file():
                return int(sysfs.read_text().strip())
    except OSError:
        pass
    with open(path, 'rb') as f:
        for size in (4096, 512):
            f.seek(size)
            if f.read(len(GPT_SIGNATURE)) == GPT_SIGNATURE:
                return size
    raise GptError(f'{path}: no GPT header at LBA 1 for a 512 or 4096 byte sector')


def find_boot_disk(boot_name='boot'):
    """The LUN whose GPT carries boot_a/boot_b, from the partition uevents."""
    found = {}
    for uevent in glob.glob('/sys/class/block/*/uevent'):
        try:
            text = Path(uevent).read_text()
        except OSError:
            continue
        for line in text.splitlines():
            if line.startswith('PARTNAME='):
                part = line.split('=', 1)[1]
                if part in (f'{boot_name}_a', f'{boot_name}_b'):
                    disk = os.path.basename(
                        os.path.dirname(os.path.realpath(os.path.dirname(uevent))))
                    found.setdefault(part, disk)
    if len(found) != 2:
        return None
    disks = set(found.values())
    if len(disks) != 1:
        raise GptError(f'{boot_name}_a and {boot_name}_b are on different LUNs: {found}')
    return '/dev/' + disks.pop()


class Gpt:
    """One GPT copy: its header plus the partition entry array."""

    def __init__(self, f, lba, sector):
        self.f = f
        self.lba = lba
        self.sector = sector
        f.seek(lba * sector)
        self.header = bytearray(f.read(HEADER_BYTES))
        if self.header[:8] != GPT_SIGNATURE:
            raise GptError(f'no GPT header at LBA {lba}')
        self.header_size = struct.unpack('<I', self.header[12:16])[0]
        self.my_lba, self.alternate_lba = struct.unpack('<QQ', self.header[24:40])
        self.entry_lba = struct.unpack('<Q', self.header[72:80])[0]
        self.count, self.entry_size = struct.unpack('<II', self.header[80:88])
        f.seek(self.entry_lba * sector)
        self.entries = bytearray(f.read(self.count * self.entry_size))
        if len(self.entries) < self.count * self.entry_size:
            raise GptError(f'entry array at LBA {self.entry_lba} is truncated '
                           f'({len(self.entries)} of {self.count * self.entry_size} bytes)')

    def find(self, name):
        for i in range(self.count):
            off = i * self.entry_size
            raw = self.entries[off:off + self.entry_size]
            if raw[:16] == b'\x00' * 16:
                continue
            label = raw[56:128].decode('utf-16-le', errors='ignore').rstrip('\x00')
            if label == name:
                return i
        return None

    def attrs(self, index):
        off = index * self.entry_size + 48
        return struct.unpack('<Q', self.entries[off:off + 8])[0]

    def set_attrs(self, index, value):
        off = index * self.entry_size + 48
        self.entries[off:off + 8] = struct.pack('<Q', value)

    def flush(self):
        """Rewrite the entry array and the header with both CRCs refreshed."""
        self.header[88:92] = struct.pack(
            '<I', zlib.crc32(bytes(self.entries)) & 0xffffffff)
        self.header[16:20] = b'\x00\x00\x00\x00'
        crc = zlib.crc32(bytes(self.header[:self.header_size])) & 0xffffffff
        self.header[16:20] = struct.pack('<I', crc)
        self.f.seek(self.entry_lba * self.sector)
        self.f.write(bytes(self.entries))
        self.f.seek(self.lba * self.sector)
        self.f.write(bytes(self.header))
        self.f.flush()
        os.fsync(self.f.fileno())


def decode(attrs):
    return {
        'priority': (attrs >> ATTR_PRIORITY_SHIFT) & ATTR_PRIORITY_MASK,
        'active': (attrs >> ATTR_ACTIVE_BIT) & 1,
        'tries': (attrs >> ATTR_TRIES_SHIFT) & ATTR_TRIES_MASK,
        'successful': (attrs >> ATTR_SUCCESSFUL_BIT) & 1,
        'unbootable': (attrs >> ATTR_UNBOOTABLE_BIT) & 1,
    }


def describe(name, attrs):
    d = decode(attrs)
    return (f"{name}: attrs=0x{attrs:016x} priority={d['priority']} "
            f"active={d['active']} tries={d['tries']} "
            f"successful={d['successful']} unbootable={d['unbootable']}")


def activate(attrs):
    """Full expected state for the slot being switched to."""
    attrs &= ~(ATTR_PRIORITY_MASK << ATTR_PRIORITY_SHIFT)
    attrs |= MAX_PRIORITY << ATTR_PRIORITY_SHIFT
    attrs |= 1 << ATTR_ACTIVE_BIT
    attrs &= ~(ATTR_TRIES_MASK << ATTR_TRIES_SHIFT)
    attrs |= MAX_TRIES << ATTR_TRIES_SHIFT
    attrs &= ~(1 << ATTR_SUCCESSFUL_BIT)
    attrs &= ~(1 << ATTR_UNBOOTABLE_BIT)
    return attrs


def demote(attrs):
    """Leave the other slot bootable but not chosen, as set-active does."""
    attrs &= ~(ATTR_PRIORITY_MASK << ATTR_PRIORITY_SHIFT)
    attrs |= 1 << ATTR_PRIORITY_SHIFT
    attrs &= ~(1 << ATTR_ACTIVE_BIT)
    return attrs


def open_copies(f, sector, allow_primary_only):
    primary = Gpt(f, 1, sector)
    try:
        backup = Gpt(f, primary.alternate_lba, sector)
    except (GptError, OSError) as exc:
        if not allow_primary_only:
            raise GptError(
                f'backup GPT at LBA {primary.alternate_lba} unreadable ({exc}); '
                f'refusing to write only one copy') from None
        print(f'note: backup GPT unreadable ({exc}); primary only', file=sys.stderr)
        backup = None
    return primary, backup


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--disk', help='LUN holding boot_a/boot_b, or a GPT dump file; '
                                   'discovered automatically on the device')
    ap.add_argument('--to', choices=['a', 'b'], help='slot to activate')
    ap.add_argument('--show', action='store_true', help='decode both copies, write nothing')
    ap.add_argument('--boot-name', default='boot', help='boot partition base name')
    args = ap.parse_args()
    if not args.show and not args.to:
        ap.error('give --show or --to')

    discovered = None
    try:
        discovered = find_boot_disk(args.boot_name)
    except GptError as exc:
        ap.error(str(exc))
    disk = args.disk or discovered
    if not disk:
        ap.error(f'no LUN carries {args.boot_name}_a/{args.boot_name}_b; pass --disk')
    # A --disk that is not where the boot partitions actually are is how the
    # wrong GPT gets rewritten; only let it through for offline dump files.
    if discovered and args.disk and os.path.realpath(args.disk) != os.path.realpath(discovered):
        if Path(args.disk).is_block_device():
            ap.error(f'--disk {args.disk} does not carry {args.boot_name}_a/'
                     f'{args.boot_name}_b; this device has them on {discovered}')

    sector = sector_size_of(disk)
    mode = 'rb' if args.show else 'r+b'
    with open(disk, mode) as f:
        primary, backup = open_copies(f, sector, allow_primary_only=args.show)
        names = [f'{args.boot_name}_a', f'{args.boot_name}_b']
        index = {}
        for name in names:
            i = primary.find(name)
            if i is None:
                raise SystemExit(f'{name} not found in the GPT on {disk}')
            index[name] = i

        print(f'disk {disk} (logical block {sector}), primary LBA {primary.lba}, '
              f'backup LBA {primary.alternate_lba}')
        for name in names:
            print('  primary', describe(name, primary.attrs(index[name])))
            if backup:
                print('  backup ', describe(name, backup.attrs(index[name])))
        if backup:
            agree = all(primary.attrs(index[n]) == backup.attrs(index[n]) for n in names)
            print(f'  copies agree: {"yes" if agree else "NO"}')

        if args.show:
            return 0

        target = f'{args.boot_name}_{args.to}'
        for copy in (primary, backup):
            if copy is None:
                continue
            for name in names:
                current = copy.attrs(index[name])
                copy.set_attrs(index[name],
                               activate(current) if name == target else demote(current))
            copy.flush()
        print(f'slot set to {args.to}; both GPT copies rewritten.')
        for name in names:
            print('  primary', describe(name, primary.attrs(index[name])))
            if backup:
                print('  backup ', describe(name, backup.attrs(index[name])))
        print('Reboot to take effect.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
