"""macOS native system operations (Spotlight, clipboard, notifications, defaults)."""

from capabilities.base import Capability, Operation, ExecutionResult
from macos.shell import run_shell_command
from macos.applescript import run_applescript
from security.risk import RiskLevel
import subprocess


class MacOSSystemCapability(Capability):
    name = "macos"
    description = (
        "Interact with native macOS system interfaces: clipboard (pbcopy/pbpaste), "
        "Spotlight search (mdfind), system notifications, and system settings (defaults)."
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
