"""Unit tests for MAX capabilities."""

import unittest
from pathlib import Path
import tempfile
from capabilities.terminal import TerminalCapability
from capabilities.filesystem import FilesystemCapability
from capabilities.applications import ApplicationsCapability
from capabilities.macos import MacOSSystemCapability
from capabilities.developer import DeveloperCapability


class TestCapabilities(unittest.TestCase):

    def setUp(self):
        self.terminal = TerminalCapability()
        self.filesystem = FilesystemCapability()
        self.applications = ApplicationsCapability()
        self.macos = MacOSSystemCapability()
        self.developer = DeveloperCapability()

    def test_terminal_execute_echo(self):
        res = self.terminal.execute_command("echo 'MAX_TEST_PING'")
        self.assertTrue(res.success)
        self.assertEqual(res.data["stdout"].strip(), "MAX_TEST_PING")
        self.assertEqual(res.data["exit_code"], 0)

    def test_terminal_check_tool_installed(self):
        res = self.terminal.check_tool_installed("git")
        self.assertTrue(res.success)
        self.assertTrue(res.data["installed"])

    def test_filesystem_write_read_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            # Write
            res_write = self.filesystem.write_file(str(test_file), "Hello MAX agent!")
            self.assertTrue(res_write.success)
            self.assertTrue(test_file.exists())

            # Read
            res_read = self.filesystem.read_file(str(test_file))
            self.assertTrue(res_read.success)
            self.assertEqual(res_read.data["content"], "Hello MAX agent!")

            # Metadata
            res_meta = self.filesystem.get_metadata(str(test_file))
            self.assertTrue(res_meta.success)
            self.assertEqual(res_meta.data["size_bytes"], len(b"Hello MAX agent!"))

    def test_filesystem_find_files(self):
        res = self.filesystem.find_files(".", pattern="pyproject.toml")
        self.assertTrue(res.success)
        self.assertGreaterEqual(res.data["matches_count"], 1)

    def test_applications_discovery(self):
        res = self.applications.list_installed_applications()
        self.assertTrue(res.success)
        self.assertGreater(res.data["count"], 0)

    def test_macos_clipboard_roundtrip(self):
        test_string = "MAX_CLIPBOARD_TEST_42"
        res_write = self.macos.write_clipboard(test_string)
        self.assertTrue(res_write.success)

        res_read = self.macos.read_clipboard()
        self.assertTrue(res_read.success)
        self.assertEqual(res_read.data["content"].strip(), test_string)

    def test_developer_inspect_project(self):
        res = self.developer.inspect_project_environment(".")
        self.assertTrue(res.success)
        self.assertIn("python", res.data["detected_stacks"])
        self.assertIn("pyproject.toml", res.data["config_files_found"])


if __name__ == "__main__":
    unittest.main()
