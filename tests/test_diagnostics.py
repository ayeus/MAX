"""Unit tests for system diagnostics and hardware detection."""

import unittest
from app.diagnostics import run_system_diagnostics
from security.permissions import check_macos_permissions, PermissionStatus


class TestDiagnostics(unittest.TestCase):

    def test_system_diagnostics_query(self):
        diag = run_system_diagnostics()
        self.assertIn(diag.architecture, ("arm64", "x86_64"))
        self.assertGreater(diag.ram_bytes, 0)
        self.assertGreater(diag.ram_gb, 0.0)
        self.assertTrue(diag.macos_version)
        self.assertTrue(diag.current_user)
        self.assertTrue(diag.cwd)
        # Verify tools dictionary populated with real installed tools
        self.assertIn("python3", diag.tools)
        self.assertTrue(diag.tools["python3"].installed)
        self.assertIn("git", diag.tools)
        self.assertTrue(diag.tools["git"].installed)

    def test_macos_permissions_check(self):
        perms = check_macos_permissions()
        self.assertGreaterEqual(len(perms), 2)
        perm_names = [p.permission_name for p in perms]
        self.assertIn("Accessibility", perm_names)
        self.assertIn("Screen Recording", perm_names)
        for p in perms:
            self.assertIn(p.status, (PermissionStatus.GRANTED, PermissionStatus.DENIED_OR_MISSING, PermissionStatus.UNKNOWN))
            self.assertTrue(p.system_settings_path)


if __name__ == "__main__":
    unittest.main()
