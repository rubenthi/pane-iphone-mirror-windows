import math
import unittest
from handset.window import dimensions, DRAWER, TAB, DEFAULT_ASPECT, FloatingWindow, SCREEN_CHROME


class WindowLayoutTests(unittest.TestCase):
    def test_anchored_resize_uses_space_to_edge_without_a_second_gutter(self):
        before = dimensions(preferred_height=563)
        # The high-density monitor fixture starts 48 physical / 24 CSS px
        # from the top/left. Growing 20 CSS px must use that available space.
        grown = dimensions(work_width=before['width']+24, work_height=before['height']+24,
                           preferred_height=583, work_margin=0)
        self.assertEqual(grown['height'], 583)
        self.assertLessEqual(grown['width'], before['width']+24)
        limited = dimensions(work_width=before['width'], work_height=before['height'],
                             preferred_height=583, work_margin=0)
        # Reversing an integer-rounded width can lose at most one logical px.
        self.assertAlmostEqual(limited['height'], before['height'], delta=1)

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
                self.assertAlmostEqual((layout['phone_width']-SCREEN_CHROME)/(layout['height']-SCREEN_CHROME), aspect, delta=.01)

    def test_bad_dimensions_do_not_reach_native_api(self):
        for aspect in (None, True, [], float('nan'), float('inf'), -.1, 99):
            with self.subTest(aspect=aspect), self.assertRaises(ValueError):
                dimensions(aspect)
        with self.assertRaises(ValueError):
            dimensions(DEFAULT_ASPECT, 'yes')

    def test_open_panel_has_usable_minimum_but_still_fits_small_displays(self):
        self.assertEqual(dimensions(expanded=True, preferred_height=360)['height'], 540)
        self.assertEqual(dimensions(expanded=False, preferred_height=360)['height'], 360)
        self.assertLessEqual(dimensions(expanded=True, preferred_height=360, work_height=480)['height'], 480)
        shell = FloatingWindow()
        shell.layout(True, DEFAULT_ASPECT)
        shell.command({'action': 'resize', 'height': 400})
        self.assertEqual(shell.layout(False, DEFAULT_ASPECT)['height'], 540)

    def test_resize_and_maximize_preserve_aspect(self):
        shell=FloatingWindow()
        small=shell.command({'action':'resize','height':500})
        self.assertEqual(small['height'],500)
        self.assertAlmostEqual((small['phone_width']-SCREEN_CHROME)/(small['height']-SCREEN_CHROME),DEFAULT_ASPECT,delta=.002)
        self.assertTrue(shell.command({'action':'maximize'})['maximized'])
        self.assertFalse(shell.command({'action':'maximize'})['maximized'])
        for height in (None,True,float('nan'),-1,10001):
            with self.assertRaises(ValueError):shell.command({'action':'resize','height':height})
