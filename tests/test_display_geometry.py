import unittest
from handset.screen import primary_display_size


class DisplayGeometryTests(unittest.TestCase):
    def test_integrated_display_wins_over_padded_wireless_display(self):
        info = {'displays': [
            {'primary': False, 'external': True, 'nativeSize': [1328.0, 2880.0]},
            {'primary': True, 'external': False, 'nativeSize': [1320.0, 2868.0]},
        ]}
        self.assertEqual(primary_display_size(info), {'width': 1320, 'height': 2868})

    def test_missing_or_invalid_metadata_does_not_invent_a_crop(self):
        for info in (None, {}, {'displays': None}, {'displays': [None]},
                     {'displays': [{'primary': True, 'external': True, 'nativeSize': [1328, 2880]}]}):
            self.assertIsNone(primary_display_size(info))
        for size in ([0, 0], [True, 2868], [1320.5, 2868], [1320, float('nan')], [1320, 20000], '1320x2868'):
            self.assertIsNone(primary_display_size({'displays': [
                {'primary': True, 'external': False, 'nativeSize': size}]}))
