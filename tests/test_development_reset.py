import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from handset import state


class DevelopmentResetTests(unittest.TestCase):
    def test_only_the_standard_development_profile_is_eligible(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, LOCALAPPDATA=folder):
            for development, name, allowed in [
                (True, 'Pane (Development)', True), (False, 'Pane (Development)', False),
                (True, 'Pane', False), (True, 'scratch', False),
            ]:
                with self.subTest(development=development, name=name), patch.object(
                    state, 'DEVELOPMENT', development
                ), patch.object(state, 'DATA_DIR', Path(folder) / name):
                    self.assertEqual(state.can_reset_development(), allowed)
