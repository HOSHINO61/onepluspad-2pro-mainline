# SPDX-License-Identifier: GPL-2.0-only
"""Which ABL overlay sink layout a packaging DTB carries, read from the DTB.

tools/build-erhai-abl-symbols.py places the inert overlay sink in one of two
layouts:

* legacy (the default): the root child /erhai-abl-overlay-sink.  This is the
  layout the installed releases boot with.  Its known cost is that the merged
  sink becomes a platform device and holds back sync_state() of several
  power and interconnect providers.
* contained (--contained-sink): /erhai-abl/overlay-sink inside a disabled
  container.  It lets those providers reach sync_state(), but the first
  unblank after the display subsystem powered down loses the device; it is
  for sync_state experiments only and is not a daily delivery.

The boot image builders take a finished DTB, so they read the layout back
from the DTB itself rather than trusting a flag: a contained DTB is refused
unless --contained-sink says it is meant, and --contained-sink is refused
on anything else.  The layout goes into their manifests.
"""
import struct

LEGACY = 'legacy'
CONTAINED = 'contained'
NONE = 'none'  # no sink at all: a plain mainline DTB
LAYOUTS = (LEGACY, CONTAINED)
ROOT_NODES = {'erhai-abl-overlay-sink': LEGACY, 'erhai-abl': CONTAINED}
USE = {
    LEGACY: 'default: the root-level sink of the installed releases',
    CONTAINED: 'opt-in (--contained-sink): sync_state experiments only, not a daily delivery',
    NONE: 'no ABL overlay sink (plain mainline DTB)',
}

FDT_MAGIC = 0xd00dfeed
FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9


class LayoutError(ValueError):
    pass


def _align4(value):
    return (value + 3) & ~3


def root_children(blob):
    """Names of the root node's direct children in a flattened device tree."""
    if len(blob) < 40 or struct.unpack('>I', blob[:4])[0] != FDT_MAGIC:
        raise LayoutError('not a flattened device tree')
    total, off_struct = struct.unpack('>II', blob[4:12])
    size_struct = struct.unpack('>I', blob[36:40])[0]
    if total > len(blob) or off_struct + size_struct > total:
        raise LayoutError('device tree header points past the blob')
    pos, end = off_struct, off_struct + size_struct
    depth, names = 0, []
    while pos + 4 <= end:
        token = struct.unpack('>I', blob[pos:pos + 4])[0]
        pos += 4
        if token == FDT_BEGIN_NODE:
            stop = blob.index(b'\0', pos, end)
            depth += 1
            if depth == 2:
                names.append(blob[pos:stop].decode('ascii', 'replace'))
            pos = _align4(stop + 1)
        elif token == FDT_END_NODE:
            depth -= 1
            if depth < 0:
                raise LayoutError('unbalanced device tree structure')
        elif token == FDT_PROP:
            length = struct.unpack('>I', blob[pos:pos + 4])[0]
            pos = _align4(pos + 8 + length)
        elif token == FDT_NOP:
            continue
        elif token == FDT_END:
            return names
        else:
            raise LayoutError(f'unknown device tree token {token:#x}')
    raise LayoutError('device tree structure has no end token')


def sink_layout(blob):
    """'legacy', 'contained' or 'none' for a DTB blob; both at once is refused."""
    found = {ROOT_NODES[name] for name in root_children(blob) if name in ROOT_NODES}
    if len(found) > 1:
        raise LayoutError('the DTB carries both sink layouts')
    return found.pop() if found else NONE


def vendor_boot_dtb(image):
    """The DTB section of an Android vendor_boot image (header v3/v4)."""
    if image[:8] != b'VNDRBOOT':
        raise LayoutError('not a vendor_boot image')
    version, page = struct.unpack('<II', image[8:16])
    if version not in (3, 4) or page == 0:
        raise LayoutError(f'unsupported vendor_boot header v{version}, page size {page}')
    ramdisk_size = struct.unpack('<I', image[24:28])[0]
    header_size, dtb_size = struct.unpack('<II', image[2096:2104])

    def pages(size):
        return (size + page - 1) // page * page

    start = pages(header_size) + pages(ramdisk_size)
    if dtb_size == 0 or start + dtb_size > len(image):
        raise LayoutError('vendor_boot has no complete DTB section')
    return image[start:start + dtb_size]


def check_choice(layout, contained_sink, allow_none=False):
    """Refuse a layout the caller did not ask for; returns the layout."""
    if contained_sink and layout != CONTAINED:
        raise LayoutError(f'--contained-sink given, but the DTB carries the {layout} layout')
    if layout == CONTAINED and not contained_sink:
        raise LayoutError('the DTB carries the contained sink, which is for sync_state '
                          'experiments only and not a daily delivery; pass '
                          '--contained-sink to build with it on purpose')
    if layout == NONE and not allow_none:
        raise LayoutError('the DTB has no ABL overlay sink; ABL will not boot it next to '
                          'the stock dtbo (build it with tools/build-erhai-abl-symbols.py)')
    return layout
