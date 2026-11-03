import unittest
from unittest.mock import patch
from handset import updater


class UpdatePolicyTests(unittest.TestCase):
    def test_development_fork_does_not_query_upstream_updates(self):
        with patch.object(updater, 'AUTO_UPDATE_ENABLED', False), \
             patch.object(updater.urllib.request, 'urlopen') as request:
            updater.check()
        request.assert_not_called()
        self.assertEqual(updater.status()['phase'], 'disabled')
