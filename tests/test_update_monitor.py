import unittest
from unittest.mock import Mock, patch
from handset import updater

class MonitorTests(unittest.TestCase):
    def test_offline_launch_retries_then_checks_periodically_until_staged(self):
        stop=Mock(); stop.is_set.return_value=False; stop.wait.return_value=False
        with patch.object(updater,'check') as check, patch.object(updater,'status',side_effect=[{'phase':'error'},{'phase':'current'},{'phase':'ready'}]):
            updater.monitor(stop)
        self.assertEqual(check.call_count,3)
        self.assertEqual([c.args[0] for c in stop.wait.call_args_list],[900,21600])
    def test_shutdown_interrupts_wait(self):
        stop=Mock(); stop.is_set.return_value=False; stop.wait.return_value=True
        with patch.object(updater,'check') as check, patch.object(updater,'status',return_value={'phase':'current'}): updater.monitor(stop)
        check.assert_called_once()
