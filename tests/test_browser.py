"""Unit tests for Browser capability."""

import unittest
from capabilities.browser import BrowserCapability


class TestBrowser(unittest.TestCase):

    def setUp(self):
        self.browser = BrowserCapability()

    def test_search_web_url_generation(self):
        res = self.browser.search_web(query="Python unit test", engine="duckduckgo")
        self.assertTrue(res.success)
        self.assertEqual(res.data["search_url"], "https://duckduckgo.com/?q=Python+unit+test")

    def test_search_web_google_encoding(self):
        res = self.browser.search_web(query="macOS M4 chip", engine="google")
        self.assertTrue(res.success)
        self.assertEqual(res.data["search_url"], "https://www.google.com/search?q=macOS+M4+chip")

    def test_handle_action_search(self):
        res = self.browser.handle_action("search", {"query": "pytest"})
        self.assertTrue(res.success)
        self.assertIn("pytest", res.data["search_url"])


if __name__ == "__main__":
    unittest.main()
