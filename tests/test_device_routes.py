import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handset import device, mux, screen


class DeviceRouteTests(unittest.TestCase):
    def test_missing_developer_mode_key_is_unknown(self):
        from pymobiledevice3 import lockdown
        for raw in (None, False, True):
            with self.subTest(raw=raw):
                phone = SimpleNamespace(paired=True, get_value=AsyncMock(return_value=raw), close=AsyncMock())
                with patch.object(lockdown, "create_using_usbmux", new_callable=AsyncMock, return_value=phone):
                    self.assertIs(device.developer_mode_enabled("one"), raw)
                phone.close.assert_awaited_once()

    def test_only_usb_records_count_as_cable_routes(self):
        records = [
            {"udid": "one", "connection": "Network", "deviceId": 1},
            {"udid": "two", "connection": "USB", "deviceId": 2},
            {"udid": "two", "connection": "Network", "deviceId": 3},
            {"udid": "two", "connection": "USB", "deviceId": 4},
        ]
        self.assertEqual(mux.usb_devices(records), [records[1]])
        with patch.object(screen, "list_devices", return_value=records):
            self.assertEqual(screen._usb_udids(), ["two"])
        with patch.object(device, "driver_status"), patch.object(device, "list_devices", return_value=records), patch.object(device, "developer_mode_enabled") as mode:
            self.assertEqual(device.snapshot()["devices"], [records[1]])
            mode.assert_called_once_with("two")

    def test_public_values_are_insufficient_to_report_trust(self):
        from pymobiledevice3 import lockdown
        for paired in (False, True):
            with self.subTest(paired=paired):
                phone = SimpleNamespace(paired=paired, all_values={"DeviceClass": "iPhone", "Private": "test"}, close=AsyncMock())
                routes = [{"udid": "one", "connection": route, "deviceId": index} for index, route in enumerate(("Network", "USB"))]
                with patch.object(device, "list_devices", return_value=routes), patch.object(lockdown, "create_using_usbmux", new_callable=AsyncMock, return_value=phone) as connect:
                    result = device.read_handset("one")
                self.assertEqual(result["paired"], paired)
                self.assertEqual(result["info"], {"DeviceClass": "iPhone"} if paired else {})
                connect.assert_awaited_once_with(serial="one", connection_type="USB", autopair=False)
                phone.close.assert_awaited_once()
