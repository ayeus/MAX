"""General application management and control capability for macOS."""

from pathlib import Path
from typing import Any
import os
import plistlib
import subprocess
import time
from capabilities.base import Capability, Operation, ExecutionResult
from macos.applescript import run_applescript
from macos.shell import run_shell_command
from security.risk import RiskLevel
from security.confirmation import request_user_confirmation
from security.audit import audit_log


class ApplicationsCapability(Capability):
    name = "applications"
    description = (
        "Discover, launch, activate, inspect, and quit arbitrary installed macOS applications. "
        "Discovers applications dynamically from the filesystem; not limited to any fixed app list."
    )

    def get_operations(self) -> list[Operation]:
        return [
            Operation(
                name="list_installed_applications",
                description="Discover all installed applications across system and user application directories.",
                parameters={
                    "filter_text": {"type": "string", "description": "Optional substring to filter application names"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.list_installed_applications,
            ),
            Operation(
                name="launch_application",
                description="Launch or open an installed application by name and verify it is running.",
                parameters={
                    "application_name": {"type": "string", "description": "Name of the application (e.g. 'Google Chrome', 'Visual Studio Code', 'Docker')"},
                    "wait_seconds": {"type": "integer", "description": "Seconds to wait before verifying application launch (default 2)"},
                },
                default_risk=RiskLevel.LOW,
                handler=self.launch_application,
            ),
            Operation(
                name="activate_application",
                description="Bring an already running application to the foreground.",
                parameters={
                    "application_name": {"type": "string", "description": "Name of the application"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.activate_application,
            ),
            Operation(
                name="is_application_running",
                description="Check if an application is currently running on macOS.",
                parameters={
                    "application_name": {"type": "string", "description": "Name of the application to check"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.is_application_running,
            ),
            Operation(
                name="quit_application",
                description="Gracefully request a running application to quit.",
                parameters={
                    "application_name": {"type": "string", "description": "Name of the application to quit"},
                },
                default_risk=RiskLevel.MEDIUM,
                handler=self.quit_application,
            ),
        ]

    def _discover_apps(self) -> dict[str, Path]:
        """Scan standard macOS application directories for .app bundles."""
        app_dirs = [
            Path("/Applications"),
            Path("/System/Applications"),
            Path("/System/Applications/Utilities"),
            Path.home() / "Applications",
        ]
        discovered: dict[str, Path] = {}
        for base in app_dirs:
            if not base.exists():
                continue
            for item in base.iterdir():
                if item.suffix == ".app":
                    name = item.stem
                    discovered[name.lower()] = item
                    # Also try reading Info.plist CFBundleDisplayName if available
                    plist_path = item / "Contents/Info.plist"
                    if plist_path.exists():
                        try:
                            with open(plist_path, "rb") as f:
                                pl = plistlib.load(f)
                                display_name = pl.get("CFBundleDisplayName") or pl.get("CFBundleName")
                                if display_name:
                                    discovered[str(display_name).lower()] = item
                        except Exception:
                            pass
        return discovered

    def _get_running_process_names(self) -> list[str]:
        """Query real list of running process names from macOS."""
        res = run_applescript('tell application "System Events" to get name of every process')
        if res.success and res.stdout:
            return [p.strip() for p in res.stdout.split(",") if p.strip()]

        # Fallback to ps if System Events encounters an issue
        ps_res = run_shell_command("/bin/ps -A -o comm=", timeout=3)
        if ps_res.success:
            return [os.path.basename(line.strip()) for line in ps_res.stdout.splitlines() if line.strip()]
        return []

    def list_installed_applications(self, filter_text: str | None = None) -> ExecutionResult:
        apps_dict = self._discover_apps()
        results = []
        filter_lower = filter_text.lower().strip() if filter_text else None

        for name, path in apps_dict.items():
            if filter_lower and filter_lower not in name:
                continue
            results.append({"name": path.stem, "path": str(path)})

        # Deduplicate by path
        seen_paths = set()
        unique_results = []
        for r in results:
            if r["path"] not in seen_paths:
                seen_paths.add(r["path"])
                unique_results.append(r)

        unique_results.sort(key=lambda x: x["name"].lower())
        return ExecutionResult(
            success=True,
            capability=self.name,
            action="list_installed_applications",
            data={"count": len(unique_results), "applications": unique_results},
            evidence={"count": len(unique_results), "sample": unique_results[:20]},
            verification={"queried_filesystem": True},
        )

    def launch_application(self, application_name: str, wait_seconds: int = 2) -> ExecutionResult:
        audit_log.log_event(
            event_type="tool_requested",
            tool=self.name,
            action="launch_application",
            details={"application": application_name},
        )

        app_clean = application_name.strip()
        # Find closest match if full path isn't provided
        app_path_to_open: str = app_clean
        apps = self._discover_apps()
        clean_lower = app_clean.lower()
        if clean_lower in apps:
            app_path_to_open = str(apps[clean_lower])
        else:
            # Check prefix / substring match
            for k, p in apps.items():
                if clean_lower in k or k in clean_lower:
                    app_path_to_open = str(p)
                    break

        # Execute real launch via /usr/bin/open
        cmd = f"/usr/bin/open -a '{app_path_to_open}'"
        res = run_shell_command(cmd, timeout=10)

        # Wait briefly for OS process table to reflect launch
        if wait_seconds > 0:
            time.sleep(wait_seconds)

        # Verify whether application is now running
        running_names = self._get_running_process_names()
        is_running = any(
            app_clean.lower() in p.lower() or Path(app_path_to_open).stem.lower() in p.lower()
            for p in running_names
        )

        audit_log.log_event(
            event_type="verification_passed" if is_running else "verification_failed",
            tool=self.name,
            action="launch_application",
            details={"application": app_clean, "verified_running": is_running},
            success=is_running,
        )

        return ExecutionResult(
            success=is_running or res.success,
            capability=self.name,
            action="launch_application",
            data={
                "application": app_clean,
                "target_opened": app_path_to_open,
                "open_exit_code": res.exit_code,
                "verified_running": is_running,
            },
            evidence={
                "launch_command": cmd,
                "open_stdout": res.stdout,
                "open_stderr": res.stderr,
                "verified_running": is_running,
            },
            verification={
                "process_present_in_process_list": is_running,
                "open_command_exit_zero": res.exit_code == 0,
            },
            error=res.stderr if res.exit_code != 0 and not is_running else None,
        )

    def activate_application(self, application_name: str) -> ExecutionResult:
        app_clean = application_name.strip()
        script = f'tell application "{app_clean}" to activate'
        res = run_applescript(script)
        return ExecutionResult(
            success=res.success,
            capability=self.name,
            action="activate_application",
            data={"application": app_clean, "activated": res.success},
            evidence={"applescript_exit_code": res.exit_code},
            verification={"activation_called": True},
            error=res.stderr if not res.success else None,
        )

    def is_application_running(self, application_name: str) -> ExecutionResult:
        app_clean = application_name.strip().lower()
        running_names = self._get_running_process_names()
        matches = [p for p in running_names if app_clean in p.lower()]
        is_running = len(matches) > 0

        return ExecutionResult(
            success=True,
            capability=self.name,
            action="is_application_running",
            data={"application": application_name, "is_running": is_running, "matched_processes": matches},
            evidence={"running": is_running, "matching_processes": matches},
            verification={"queried_system_processes": True},
        )

    def quit_application(self, application_name: str) -> ExecutionResult:
        app_clean = application_name.strip()
        script = f'tell application "{app_clean}" to quit'
        res = run_applescript(script)
        time.sleep(1)

        running_names = self._get_running_process_names()
        still_running = any(app_clean.lower() in p.lower() for p in running_names)

        return ExecutionResult(
            success=not still_running,
            capability=self.name,
            action="quit_application",
            data={"application": app_clean, "quit_success": not still_running},
            evidence={"process_terminated": not still_running},
            verification={"verified_not_running": not still_running},
            error=res.stderr if still_running else None,
        )
