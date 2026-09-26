# SPDX-License-Identifier: GPL-2.0-only
"""Where build-erhai-abl-symbols.py puts the ABL overlay sink, text level."""
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


if __name__ == '__main__':
    unittest.main()
