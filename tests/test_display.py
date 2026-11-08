import ctypes
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from handset import display


class DisplayDensityTests(unittest.TestCase):
    def user_api(self, *, configured=False, success=True):
        return SimpleNamespace(GetThreadDpiAwarenessContext=Mock(return_value=123),
            AreDpiAwarenessContextsEqual=Mock(return_value=configured),
            SetProcessDpiAwarenessContext=Mock(return_value=success))

    def test_source_launch_sets_per_monitor_v2_before_ui_creation(self):
        api = self.user_api()
        with patch.object(display, 'os', SimpleNamespace(name='nt')), patch.object(
                ctypes, 'WinDLL', return_value=api, create=True):
            display.enable_per_monitor_dpi()
        api.SetProcessDpiAwarenessContext.assert_called_once_with(-4)

    def test_packaged_manifest_setting_is_not_overridden(self):
        api = self.user_api(configured=True)
        with patch.object(display, 'os', SimpleNamespace(name='nt')), patch.object(
                ctypes, 'WinDLL', return_value=api, create=True):
            display.enable_per_monitor_dpi()
        api.SetProcessDpiAwarenessContext.assert_not_called()

    def test_late_dpi_initialization_fails_instead_of_silently_blurring(self):
        api = self.user_api(success=False)
        with patch.object(display, 'os', SimpleNamespace(name='nt')), patch.object(
                ctypes, 'WinDLL', return_value=api, create=True), patch.object(
                ctypes, 'get_last_error', return_value=5, create=True):
            with self.assertRaises(OSError):
                display.enable_per_monitor_dpi()

    def test_non_windows_launch_does_not_load_windows_apis(self):
        with patch.object(display, 'os', SimpleNamespace(name='posix')), patch.object(
                ctypes, 'WinDLL', create=True) as load:
            display.enable_per_monitor_dpi()
        load.assert_not_called()

    def test_packaged_manifest_declares_density_without_elevation(self):
        root = Path(__file__).resolve().parents[1]
        document = ET.parse(root / 'packaging/pane.manifest')
        setting = document.find('.//{http://schemas.microsoft.com/SMI/2016/WindowsSettings}dpiAwareness')
        self.assertEqual(setting.text, 'PerMonitorV2')
        privilege = document.find('.//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel')
        self.assertEqual(privilege.attrib, {'level': 'asInvoker', 'uiAccess': 'false'})
        self.assertIn('manifest=str(ROOT / "packaging" / "pane.manifest")', (root / 'packaging/pane.spec').read_text())
