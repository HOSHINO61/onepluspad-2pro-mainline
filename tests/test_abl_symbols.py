# SPDX-License-Identifier: GPL-2.0-only
"""Where build-erhai-abl-symbols.py puts the ABL overlay sink, text level.

Both layouts: the contained sink of the package sets from 0.1.50 on, and the
root-level sink of --legacy-sink (the layout up to 0.1.49, comparison images).
"""
import importlib.util
from pathlib import Path
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'tools/build-erhai-abl-symbols.py'
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


class SinkPlacementTest(unittest.TestCase):
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
    """--legacy-sink: the root-level sink of the package sets up to 0.1.49."""

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


if __name__ == '__main__':
    unittest.main()
