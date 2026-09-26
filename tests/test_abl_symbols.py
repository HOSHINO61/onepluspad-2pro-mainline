# SPDX-License-Identifier: GPL-2.0-only
"""Where build-erhai-abl-symbols.py puts the ABL overlay sink, and how the
boot image builders read the layout back.

Both layouts at the text level: the root-level legacy sink (the default, for
daily deliveries) and the contained sink of --contained-sink (sync_state
experiments only). tools/lib/abl_layout.py on synthetic device trees and
vendor_boot images, and the choice it enforces.
"""
import importlib.util
from pathlib import Path
import struct
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
from lib import abl_layout  # noqa: E402

TOOL = TOOLS / 'build-erhai-abl-symbols.py'
spec = importlib.util.spec_from_file_location('abl_symbols', TOOL)
abl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(abl)

MAINLINE = '''/dts-v1/;

/ {
\tmodel = "test";
\tsoc@0 {
\t\toverlay-sink {
\t\t\tstatus = "okay";
\t\t};
\t};
};
'''


class LayoutChoiceTest(unittest.TestCase):
    """The command line: legacy unless --contained-sink asks otherwise."""

    def parse(self, *argv):
        return abl.build_parser().parse_args(list(argv)).sink_layout

    def test_default_is_legacy(self):
        self.assertEqual(self.parse(), 'legacy')
        self.assertEqual(self.parse('--legacy-sink'), 'legacy')

    def test_contained_is_opt_in(self):
        self.assertEqual(self.parse('--contained-sink'), 'contained')

    def test_both_flags_are_refused(self):
        with self.assertRaises(SystemExit):
            self.parse('--contained-sink', '--legacy-sink')

    def test_every_layout_says_what_it_is_for(self):
        self.assertEqual(set(abl.LAYOUT_USE), {'legacy', 'contained', 'none'})
        self.assertIn('default', abl.LAYOUT_USE['legacy'])
        self.assertIn('not a daily delivery', abl.LAYOUT_USE['contained'])


class SinkPlacementTest(unittest.TestCase):
    """--contained-sink: the sink inside the disabled /erhai-abl container."""

    def setUp(self):
        self.text = abl.inject(MAINLINE, ['alpha', 'beta'],
                               {'qcom,msm-id': 'qcom,msm-id = <0x1 0x2>;'})

    def test_sink_is_inside_a_disabled_container(self):
        self.assertEqual(abl.SINK_PATH, '/erhai-abl/overlay-sink')
        container = abl.child_node_properties(self.text, abl.CONTAINER_NAME)
        self.assertEqual(container, {'status': '"disabled"'})
        sink = abl.child_node_properties(self.text, abl.SINK_PATH)
        self.assertEqual(sink, {'linux,phandle': f'<{abl.SINK_PHANDLE:#x}>'})

    def test_every_symbol_names_the_nested_sink(self):
        symbols = abl.child_node_properties(self.text, '__symbols__')
        self.assertEqual(symbols, {'alpha': '"/erhai-abl/overlay-sink"',
                                   'beta': '"/erhai-abl/overlay-sink"'})
        self.assertNotIn('"/erhai-abl"', symbols.values())

    def test_path_lookup_does_not_take_a_same_named_node_elsewhere(self):
        other = abl.child_node_properties(self.text, 'soc@0/overlay-sink')
        self.assertEqual(other, {'status': '"okay"'})

    def test_labels_on_the_sink_line_still_match(self):
        # dtc prints every symbol as a label on the node it names.
        labelled = self.text.replace('\t\toverlay-sink {', '\t\talpha: beta: overlay-sink {')
        sink = abl.child_node_properties(labelled, abl.SINK_PATH)
        self.assertIn('linux,phandle', sink)

    def test_identity_goes_first_and_the_container_closes_the_root(self):
        lines = self.text.splitlines()
        self.assertEqual(lines[lines.index('/ {') + 1], '\tqcom,msm-id = <0x1 0x2>;')
        self.assertLess(lines.index('\terhai-abl {'), lines.index('\t__symbols__ {'))

    def test_a_mainline_node_with_the_container_name_is_refused(self):
        clash = MAINLINE.replace('\tsoc@0 {', '\terhai-abl {')
        with self.assertRaises(SystemExit):
            abl.check_mainline(clash)

    def test_missing_path_is_reported(self):
        with self.assertRaises(SystemExit):
            abl.child_node_properties(self.text, 'erhai-abl/other')

    def test_layout_check_accepts_it_and_refuses_the_legacy_reading(self):
        self.assertIn('disabled', abl.check_layout(self.text))
        with self.assertRaises(SystemExit):
            abl.check_layout(self.text, legacy=True)

    def test_an_enabled_container_is_refused(self):
        enabled = self.text.replace('\t\tstatus = "disabled";', '\t\tstatus = "okay";')
        with self.assertRaises(SystemExit):
            abl.check_layout(enabled)


class LegacySinkPlacementTest(unittest.TestCase):
    """The default: the root-level sink the installed releases boot with."""

    def setUp(self):
        self.text = abl.inject(MAINLINE, ['alpha', 'beta'],
                               {'qcom,msm-id': 'qcom,msm-id = <0x1 0x2>;'}, legacy=True)

    def test_sink_is_a_root_child_without_container(self):
        self.assertEqual(abl.sink_path(True), '/erhai-abl-overlay-sink')
        sink = abl.child_node_properties(self.text, abl.LEGACY_SINK_NAME)
        self.assertEqual(sink, {'linux,phandle': f'<{abl.SINK_PHANDLE:#x}>'})
        lines = self.text.splitlines()
        self.assertIn('\terhai-abl-overlay-sink {', lines)
        self.assertNotIn('\terhai-abl {', lines)
        with self.assertRaises(SystemExit):
            abl.child_node_properties(self.text, abl.CONTAINER_NAME)

    def test_every_symbol_names_the_root_sink(self):
        symbols = abl.child_node_properties(self.text, '__symbols__')
        self.assertEqual(symbols, {'alpha': '"/erhai-abl-overlay-sink"',
                                   'beta': '"/erhai-abl-overlay-sink"'})

    def test_layout_check_accepts_it_and_refuses_the_contained_reading(self):
        self.assertIn('legacy', abl.check_layout(self.text, legacy=True))
        with self.assertRaises(SystemExit):
            abl.check_layout(self.text)

    def test_identity_goes_first_and_the_sink_closes_the_root(self):
        lines = self.text.splitlines()
        self.assertEqual(lines[lines.index('/ {') + 1], '\tqcom,msm-id = <0x1 0x2>;')
        self.assertLess(lines.index('\terhai-abl-overlay-sink {'), lines.index('\t__symbols__ {'))

    def test_a_mainline_node_with_the_sink_name_is_refused(self):
        clash = MAINLINE.replace('\tsoc@0 {', '\terhai-abl-overlay-sink {')
        with self.assertRaises(SystemExit):
            abl.check_mainline(clash, legacy=True)
        abl.check_mainline(MAINLINE, legacy=True)

    def test_same_symbols_and_identity_as_the_contained_layout(self):
        contained = abl.inject(MAINLINE, ['alpha', 'beta'],
                               {'qcom,msm-id': 'qcom,msm-id = <0x1 0x2>;'})
        self.assertEqual(abl.root_properties(self.text), abl.root_properties(contained))
        self.assertEqual(set(abl.child_node_properties(self.text, '__symbols__')),
                         set(abl.child_node_properties(contained, '__symbols__')))


def fdt(root_children):
    """A minimal flattened device tree: a root with a model and these children,
    each holding one property."""
    strings = b'model\0linux,phandle\0'

    def node(name, *props):
        data = struct.pack('>I', 1) + name.encode() + b'\0'
        data += b'\0' * (-len(data) % 4)
        for nameoff, value in props:
            data += struct.pack('>III', 3, len(value), nameoff) + value
            data += b'\0' * (-len(data) % 4)
        return data

    body = node('', (0, b'test\0'))
    for name in root_children:
        body += node(name, (6, struct.pack('>I', 0x40000000))) + struct.pack('>I', 2)
    body += struct.pack('>I', 2) + struct.pack('>I', 9)
    off_rsv = 40
    off_struct = off_rsv + 16
    off_strings = off_struct + len(body)
    total = off_strings + len(strings)
    header = struct.pack('>10I', 0xd00dfeed, total, off_struct, off_strings, off_rsv,
                         17, 16, 0, len(strings), len(body))
    return header + b'\0' * 16 + body + strings


def vendor_boot(dtb, page=4096, ramdisk=b'ramdisk'):
    """A header v4 vendor_boot: header page, vendor ramdisk, DTB, footer bytes."""
    header = bytearray(2128)
    header[:8] = b'VNDRBOOT'
    struct.pack_into('<II', header, 8, 4, page)
    struct.pack_into('<I', header, 24, len(ramdisk))
    struct.pack_into('<II', header, 2096, len(header), len(dtb))

    def padded(data):
        return bytes(data) + b'\0' * (-len(data) % page)

    return padded(header) + padded(ramdisk) + padded(dtb) + b'AVBf' * 16


class LayoutReadbackTest(unittest.TestCase):
    """tools/lib/abl_layout.py: the layout as the boot image builders see it."""

    def test_root_children_are_read_in_order(self):
        blob = fdt(['soc@0', 'erhai-abl-overlay-sink', '__symbols__'])
        self.assertEqual(abl_layout.root_children(blob),
                         ['soc@0', 'erhai-abl-overlay-sink', '__symbols__'])

    def test_each_layout_is_recognised(self):
        self.assertEqual(abl_layout.sink_layout(fdt(['soc@0', 'erhai-abl-overlay-sink'])),
                         'legacy')
        self.assertEqual(abl_layout.sink_layout(fdt(['soc@0', 'erhai-abl'])), 'contained')
        self.assertEqual(abl_layout.sink_layout(fdt(['soc@0'])), 'none')

    def test_both_layouts_at_once_are_refused(self):
        with self.assertRaises(abl_layout.LayoutError):
            abl_layout.sink_layout(fdt(['erhai-abl', 'erhai-abl-overlay-sink']))

    def test_not_a_device_tree_is_refused(self):
        with self.assertRaises(abl_layout.LayoutError):
            abl_layout.sink_layout(b'\0' * 64)

    def test_the_dtb_is_found_in_a_vendor_boot(self):
        dtb = fdt(['erhai-abl-overlay-sink'])
        image = vendor_boot(dtb, ramdisk=b'x' * 5000)
        self.assertEqual(abl_layout.vendor_boot_dtb(image), dtb)
        self.assertEqual(abl_layout.sink_layout(abl_layout.vendor_boot_dtb(image)), 'legacy')

    def test_a_boot_image_is_not_a_vendor_boot(self):
        with self.assertRaises(abl_layout.LayoutError):
            abl_layout.vendor_boot_dtb(b'ANDROID!' + b'\0' * 4096)

    def test_legacy_is_taken_without_a_flag(self):
        self.assertEqual(abl_layout.check_choice('legacy', False), 'legacy')

    def test_contained_needs_the_flag(self):
        with self.assertRaises(abl_layout.LayoutError):
            abl_layout.check_choice('contained', False)
        self.assertEqual(abl_layout.check_choice('contained', True), 'contained')

    def test_the_flag_needs_a_contained_dtb(self):
        for layout in ('legacy', 'none'):
            with self.assertRaises(abl_layout.LayoutError):
                abl_layout.check_choice(layout, True, allow_none=True)

    def test_no_sink_only_where_allowed(self):
        with self.assertRaises(abl_layout.LayoutError):
            abl_layout.check_choice('none', False)
        self.assertEqual(abl_layout.check_choice('none', False, allow_none=True), 'none')


if __name__ == '__main__':
    unittest.main()
