import os
import tempfile
import unittest

from settings import GuildSettings


class GuildSettingsTest(unittest.TestCase):
    def test_defaults_to_off(self):
        settings = GuildSettings(':memory:')
        self.assertFalse(settings.get_delete_original(1))

    def test_set_and_clear(self):
        settings = GuildSettings(':memory:')
        settings.set_delete_original(1, True)
        self.assertTrue(settings.get_delete_original(1))
        self.assertFalse(settings.get_delete_original(2))
        settings.set_delete_original(1, False)
        self.assertFalse(settings.get_delete_original(1))

    def test_persists_across_restarts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'settings.db')
            first = GuildSettings(path)
            first.set_delete_original(123456789012345678, True)
            first.close()
            second = GuildSettings(path)
            try:
                self.assertTrue(second.get_delete_original(123456789012345678))
            finally:
                second.close()


if __name__ == '__main__':
    unittest.main()
