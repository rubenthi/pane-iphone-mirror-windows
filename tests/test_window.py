import math
import unittest
from handset.window import dimensions, DRAWER, TAB, DEFAULT_ASPECT, FloatingWindow


class WindowLayoutTests(unittest.TestCase):
    def test_panel_overlays_without_changing_native_dimensions(self):
        compact = dimensions()
        expanded = dimensions(expanded=True)
        self.assertEqual(compact['phone_width'], expanded['phone_width'])
        self.assertEqual(compact['height'], expanded['height'])
        self.assertEqual(expanded['width'], compact['width'])

    def test_display_aspect_and_landscape_fit_work_area(self):
        for aspect in (390/844, 430/932, 844/390, 2.5):
            for expanded in (False, True):
                layout = dimensions(aspect, expanded, 1280, 720)
                self.assertLessEqual(layout['width'], 1280)
                self.assertLessEqual(layout['height'], 720)
                self.assertAlmostEqual((layout['phone_width']-14)/(layout['height']-14), aspect, delta=.01)

    def test_bad_dimensions_do_not_reach_native_api(self):
        for aspect in (None, True, [], float('nan'), float('inf'), -.1, 99):
            with self.subTest(aspect=aspect), self.assertRaises(ValueError):
                dimensions(aspect)
        with self.assertRaises(ValueError):
            dimensions(DEFAULT_ASPECT, 'yes')

    def test_resize_and_maximize_preserve_aspect(self):
        shell=FloatingWindow()
        small=shell.command({'action':'resize','height':500})
        self.assertEqual(small['height'],500)
        self.assertAlmostEqual((small['phone_width']-14)/(small['height']-14),DEFAULT_ASPECT,delta=.002)
        self.assertTrue(shell.command({'action':'maximize'})['maximized'])
        self.assertFalse(shell.command({'action':'maximize'})['maximized'])
        for height in (None,True,float('nan'),-1,10001):
            with self.assertRaises(ValueError):shell.command({'action':'resize','height':height})
