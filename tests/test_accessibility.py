"""Unit tests for Accessibility and GUI automation capability."""

import unittest
from capabilities.accessibility import AccessibilityCapability


class TestAccessibility(unittest.TestCase):

    def setUp(self):
        self.acc = AccessibilityCapability()

    def test_get_active_window_info(self):
        res = self.acc.get_active_window_info()
        self.assertTrue(res.success)
        self.assertIn("process_name", res.data)
        self.assertIn("window_title", res.data)

    def test_list_menu_items_frontmost(self):
        res = self.acc.list_menu_items()
        self.assertTrue(res.success)
        self.assertIn("items", res.data)
        self.assertGreater(len(res.data["items"]), 0)

    def test_send_keystroke_escape(self):
        # Sending safe Escape key
        res = self.acc.send_keystroke(text="escape")
        self.assertTrue(res.success)
        self.assertTrue(res.verification["keystroke_sent"])


if __name__ == "__main__":
    unittest.main()
