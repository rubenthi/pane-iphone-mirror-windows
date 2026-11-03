import math
import unittest
from handset.window import dimensions, DRAWER, TAB, DEFAULT_ASPECT


class WindowLayoutTests(unittest.TestCase):
    def test_sidebar_expands_horizontally_without_resizing_phone(self):
        compact = dimensions()
        expanded = dimensions(expanded=True)
        self.assertEqual(compact['phone_width'], expanded['phone_width'])
        self.assertEqual(compact['height'], expanded['height'])
        self.assertEqual(expanded['width'] - compact['width'], DRAWER - TAB)

    def test_display_aspect_and_landscape_fit_work_area(self):
        for aspect in (390/844, 430/932, 844/390, 2.5):
            for expanded in (False, True):
                layout = dimensions(aspect, expanded, 1280, 720)
                self.assertLessEqual(layout['width'], 1280)
                self.assertLessEqual(layout['height'], 720)
                self.assertAlmostEqual((layout['phone_width']-16)/(layout['height']-16), aspect, delta=.01)

    def test_bad_dimensions_do_not_reach_native_api(self):
        for aspect in (None, True, [], float('nan'), float('inf'), -.1, 99):
            with self.subTest(aspect=aspect), self.assertRaises(ValueError):
                dimensions(aspect)
        with self.assertRaises(ValueError):
            dimensions(DEFAULT_ASPECT, 'yes')
