"""macOS native system operations (Spotlight, clipboard, notifications, defaults)."""

from capabilities.base import Capability, Operation, ExecutionResult
from macos.shell import run_shell_command
from macos.applescript import run_applescript
from macos.brightness import get_display_brightness, set_display_brightness, is_brightness_supported
from security.risk import RiskLevel
import subprocess


class MacOSSystemCapability(Capability):
    name = "macos"
    description = (
        "Interact with native macOS system interfaces: clipboard (pbcopy/pbpaste), "
        "Spotlight search (mdfind), system notifications, system settings (defaults), "
        "and display brightness."
    )

    def get_operations(self) -> list[Operation]:
        return [
            Operation(
                name="read_clipboard",
                description="Read the current text content from the macOS system clipboard.",
                parameters={},
                default_risk=RiskLevel.SAFE,
                handler=self.read_clipboard,
            ),
            Operation(
                name="write_clipboard",
                description="Copy text content to the macOS system clipboard.",
                parameters={
                    "text": {"type": "string", "description": "Text to place on the clipboard"},
                },
                default_risk=RiskLevel.LOW,
                handler=self.write_clipboard,
            ),
            Operation(
                name="show_notification",
                description="Display a native macOS desktop notification banner to the user.",
                parameters={
                    "message": {"type": "string", "description": "Notification body message"},
                    "title": {"type": "string", "description": "Notification title (defaults to 'MAX')"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.show_notification,
            ),
            Operation(
                name="spotlight_search",
                description="Fast filesystem search across macOS using Spotlight mdfind.",
                parameters={
                    "query": {"type": "string", "description": "Spotlight query string or name"},
                    "max_results": {"type": "integer", "description": "Maximum results to return (default 25)"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.spotlight_search,
            ),
            Operation(
                name="read_system_default",
                description="Read a macOS system or application setting via 'defaults read'.",
                parameters={
                    "domain": {"type": "string", "description": "Domain (e.g. 'com.apple.finder', 'NSGlobalDomain')"},
                    "key": {"type": "string", "description": "Optional specific key within the domain"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.read_system_default,
            ),
            Operation(
                name="get_brightness",
                description="Read current display brightness level (0.0 to 1.0) on macOS.",
                parameters={},
                default_risk=RiskLevel.SAFE,
                handler=self.get_brightness,
            ),
            Operation(
                name="set_brightness",
                description="Set display brightness level to an absolute value between 0.0 and 1.0.",
                parameters={
                    "level": {"type": "number", "description": "Target brightness level between 0.0 and 1.0"},
                },
                default_risk=RiskLevel.LOW,
                handler=self.set_brightness,
            ),
            Operation(
                name="increase_brightness",
                description="Increase display brightness level by a delta (default 0.1).",
                parameters={
                    "delta": {"type": "number", "description": "Amount to increase brightness by (default 0.1)"},
                },
                default_risk=RiskLevel.LOW,
                handler=self.increase_brightness,
            ),
            Operation(
                name="decrease_brightness",
                description="Decrease display brightness level by a delta (default 0.1).",
                parameters={
                    "delta": {"type": "number", "description": "Amount to decrease brightness by (default 0.1)"},
                },
                default_risk=RiskLevel.LOW,
                handler=self.decrease_brightness,
            ),
        ]


    def read_clipboard(self) -> ExecutionResult:
        res = run_shell_command("/usr/bin/pbpaste", timeout=3)
        return ExecutionResult(
            success=res.success,
            capability=self.name,
            action="read_clipboard",
            data={"content": res.stdout},
            evidence={"length": len(res.stdout)},
            verification={"pbpaste_executed": True},
        )

    def write_clipboard(self, text: str) -> ExecutionResult:
        try:
            proc = subprocess.run(
                ["/usr/bin/pbcopy"],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=3,
            )
            # Verify by reading back
            verify_res = run_shell_command("/usr/bin/pbpaste", timeout=3)
            matches = verify_res.stdout == text
            return ExecutionResult(
                success=proc.returncode == 0,
                capability=self.name,
                action="write_clipboard",
                data={"bytes_written": len(text.encode("utf-8"))},
                evidence={"matches_verified": matches},
                verification={"pbcopy_exit_zero": proc.returncode == 0, "clipboard_matches": matches},
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="write_clipboard",
                error=str(e),
            )

    def show_notification(self, message: str, title: str = "MAX") -> ExecutionResult:
        msg_clean = message.replace('"', '\\"')
        title_clean = title.replace('"', '\\"')
        script = f'display notification "{msg_clean}" with title "{title_clean}"'
        res = run_applescript(script)
        return ExecutionResult(
            success=res.success,
            capability=self.name,
            action="show_notification",
            data={"title": title, "message": message},
            evidence={"applescript_exit_code": res.exit_code},
            verification={"notification_posted": res.success},
        )

    def spotlight_search(self, query: str, max_results: int = 25) -> ExecutionResult:
        cmd = f"/usr/bin/mdfind '{query}'"
        res = run_shell_command(cmd, timeout=10)
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        results = lines[:max_results]
        return ExecutionResult(
            success=res.success,
            capability=self.name,
            action="spotlight_search",
            data={"query": query, "total_found": len(lines), "results": results},
            evidence={"count": len(results)},
            verification={"mdfind_executed": res.success},
        )

    def read_system_default(self, domain: str, key: str | None = None) -> ExecutionResult:
        key_arg = f" '{key}'" if key else ""
        cmd = f"/usr/bin/defaults read '{domain}'{key_arg}"
        res = run_shell_command(cmd, timeout=3)
        return ExecutionResult(
            success=res.success,
            capability=self.name,
            action="read_system_default",
            data={"domain": domain, "key": key, "value": res.stdout.strip()},
            evidence={"stdout": res.stdout.strip(), "stderr": res.stderr.strip()},
            verification={"defaults_queried": True},
            error=res.stderr if not res.success else None,
        )

    def get_brightness(self) -> ExecutionResult:
        ok, val, err = get_display_brightness()
        if not ok:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="get_brightness",
                error=err or "Brightness control is not supported on this display hardware.",
                data={"supported": False},
                evidence={"display_services_available": is_brightness_supported()},
            )
        return ExecutionResult(
            success=True,
            capability=self.name,
            action="get_brightness",
            data={"level": val, "supported": True},
            evidence={"level": val, "provider": "DisplayServices"},
            verification={"brightness_queried": True},
        )

    def set_brightness(self, level: float = 0.5) -> ExecutionResult:
        try:
            target_level = float(level)
        except (ValueError, TypeError):
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="set_brightness",
                error=f"Invalid brightness level: {level}",
            )

        ok_before, before_val, err_before = get_display_brightness()
        if not ok_before:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="set_brightness",
                error=err_before or "Brightness control is not supported on this display.",
            )

        ok_set, after_val, err_set = set_display_brightness(target_level)
        if not ok_set:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="set_brightness",
                error=err_set or "Failed to set display brightness.",
                evidence={"before": before_val},
            )

        matches_target = abs(after_val - target_level) < 0.05 or (target_level >= 1.0 and after_val >= 0.95) or (target_level <= 0.0 and after_val <= 0.05)
        return ExecutionResult(
            success=True,
            capability=self.name,
            action="set_brightness",
            data={"level": after_val, "previous_level": before_val},
            evidence={"before": before_val, "after": after_val, "target": target_level},
            verification={"brightness_set": matches_target},
        )

    def increase_brightness(self, delta: float = 0.1) -> ExecutionResult:
        try:
            step_delta = float(delta)
        except (ValueError, TypeError):
            step_delta = 0.1

        ok_before, before_val, err_before = get_display_brightness()
        if not ok_before:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="increase_brightness",
                error=err_before or "Brightness control is not supported on this display.",
            )

        target = min(1.0, before_val + step_delta)
        ok_set, after_val, err_set = set_display_brightness(target)
        if not ok_set:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="increase_brightness",
                error=err_set or "Failed to increase display brightness.",
                evidence={"before": before_val},
            )

        increased = (after_val > before_val) or (before_val >= 0.99 and after_val >= 0.99)
        return ExecutionResult(
            success=True,
            capability=self.name,
            action="increase_brightness",
            data={"level": after_val, "previous_level": before_val, "delta": step_delta},
            evidence={"before": before_val, "after": after_val, "delta_requested": step_delta, "delta_actual": after_val - before_val},
            verification={"brightness_increased": increased},
        )

    def decrease_brightness(self, delta: float = 0.1) -> ExecutionResult:
        try:
            step_delta = float(delta)
        except (ValueError, TypeError):
            step_delta = 0.1

        ok_before, before_val, err_before = get_display_brightness()
        if not ok_before:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="decrease_brightness",
                error=err_before or "Brightness control is not supported on this display.",
            )

        target = max(0.0, before_val - step_delta)
        ok_set, after_val, err_set = set_display_brightness(target)
        if not ok_set:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="decrease_brightness",
                error=err_set or "Failed to decrease display brightness.",
                evidence={"before": before_val},
            )

        decreased = (after_val < before_val) or (before_val <= 0.01 and after_val <= 0.01)
        return ExecutionResult(
            success=True,
            capability=self.name,
            action="decrease_brightness",
            data={"level": after_val, "previous_level": before_val, "delta": step_delta},
            evidence={"before": before_val, "after": after_val, "delta_requested": step_delta, "delta_actual": before_val - after_val},
            verification={"brightness_decreased": decreased},
        )

