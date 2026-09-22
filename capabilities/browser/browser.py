"""General browser automation capability for macOS (Safari and Google Chrome)."""

from typing import Any
import urllib.parse
from capabilities.base import Capability, Operation, ExecutionResult
from macos.applescript import run_applescript
from macos.shell import run_shell_command
from security.risk import RiskLevel
from security.audit import audit_log


class BrowserCapability(Capability):
    name = "browser"
    description = (
        "Control web browsers on macOS (Safari, Google Chrome, default browser): "
        "open URLs, perform web searches, inspect active tab title and URL, "
        "and read page contents or execute JavaScript."
    )

    def get_operations(self) -> list[Operation]:
        return [
            Operation(
                name="open_url",
                description="Open a web URL in the browser.",
                parameters={
                    "url": {"type": "string", "description": "The full HTTP/HTTPS URL to open"},
                    "browser": {"type": "string", "description": "Optional browser name: 'Safari', 'Google Chrome', or empty for default"},
                },
                default_risk=RiskLevel.LOW,
                handler=self.open_url,
            ),
            Operation(
                name="search_web",
                description="Perform a web search in the browser.",
                parameters={
                    "query": {"type": "string", "description": "Search query keywords or phrase"},
                    "engine": {"type": "string", "description": "Search engine: 'google', 'duckduckgo', 'bing' (default google)"},
                    "browser": {"type": "string", "description": "Optional browser: 'Safari' or 'Google Chrome'"},
                },
                default_risk=RiskLevel.LOW,
                handler=self.search_web,
            ),
            Operation(
                name="get_active_tab_info",
                description="Retrieve the title and URL of the currently active browser tab.",
                parameters={
                    "browser": {"type": "string", "description": "Browser name: 'Safari' or 'Google Chrome' (default Safari)"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.get_active_tab_info,
            ),
            Operation(
                name="read_page_text",
                description="Extract the visible body text of the current active webpage.",
                parameters={
                    "browser": {"type": "string", "description": "Browser name: 'Safari' or 'Google Chrome'"},
                    "max_chars": {"type": "integer", "description": "Maximum characters to return (default 2000)"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.read_page_text,
            ),
        ]

    def handle_action(self, action: str, args: dict[str, Any]) -> ExecutionResult:
        """Handle intuitive action names like search, open, navigate, launch."""
        act_lower = action.lower()
        if "search" in act_lower:
            query = args.get("query") or args.get("text") or " ".join(str(v) for v in args.values())
            return self.search_web(query=query, browser=args.get("browser", ""))
        elif "url" in act_lower or "open" in act_lower or "navigate" in act_lower:
            url = args.get("url") or args.get("link") or "https://www.google.com"
            return self.open_url(url=url, browser=args.get("browser", ""))
        elif "launch" in act_lower or "app" in act_lower:
            browser_name = args.get("application_name") or args.get("browser") or "Safari"
            return self.open_url(url="https://www.google.com", browser=browser_name)
        raise NotImplementedError(f"Action '{action}' is not supported in '{self.name}'.")

    def open_url(self, url: str, browser: str = "") -> ExecutionResult:
        url_clean = url.strip()
        if not url_clean.startswith(("http://", "https://")):
            url_clean = "https://" + url_clean

        audit_log.log_event(
            event_type="tool_requested",
            tool=self.name,
            action="open_url",
            details={"url": url_clean, "browser": browser},
        )

        b_lower = browser.lower().strip()
        if "safari" in b_lower:
            script = f'tell application "Safari" to open location "{url_clean}"'
            res = run_applescript(script, timeout=6)
        elif "chrome" in b_lower or "google" in b_lower:
            script = f'tell application "Google Chrome" to open location "{url_clean}"'
            res = run_applescript(script, timeout=6)
        else:
            # Open via macOS default handler
            cmd = f"/usr/bin/open '{url_clean}'"
            sh_res = run_shell_command(cmd, timeout=6)
            return ExecutionResult(
                success=sh_res.success,
                capability=self.name,
                action="open_url",
                data={"url": url_clean, "browser": "default"},
                evidence={"open_exit_code": sh_res.exit_code},
                verification={"browser_opened": sh_res.success},
                error=sh_res.stderr if not sh_res.success else None,
            )

        return ExecutionResult(
            success=res.success,
            capability=self.name,
            action="open_url",
            data={"url": url_clean, "browser": browser or "Safari"},
            evidence={"applescript_exit_code": res.exit_code},
            verification={"url_opened": res.success},
            error=res.stderr if not res.success else None,
        )

    def search_web(self, query: str, engine: str = "google", browser: str = "") -> ExecutionResult:
        encoded = urllib.parse.quote_plus(query.strip())
        engine_lower = engine.lower().strip()

        if "duck" in engine_lower:
            url = f"https://duckduckgo.com/?q={encoded}"
        elif "bing" in engine_lower:
            url = f"https://www.bing.com/search?q={encoded}"
        else:
            url = f"https://www.google.com/search?q={encoded}"

        res = self.open_url(url=url, browser=browser)
        return ExecutionResult(
            success=res.success,
            capability=self.name,
            action="search_web",
            data={"query": query, "engine": engine, "search_url": url},
            evidence=res.evidence,
            verification={"search_dispatched": res.success},
            error=res.error,
        )

    def get_active_tab_info(self, browser: str = "Safari") -> ExecutionResult:
        b_lower = browser.lower().strip()

        if "chrome" in b_lower:
            script = """
            tell application "Google Chrome"
                if not (exists window 1) then return "NO_WINDOW"
                set activeTab to active tab of window 1
                return (title of activeTab) & "|||" & (URL of activeTab)
            end tell
            """
        else:
            script = """
            tell application "Safari"
                if not (exists document 1) then return "NO_WINDOW"
                return (name of current tab of window 1) & "|||" & (URL of current tab of window 1)
            end tell
            """

        res = run_applescript(script, timeout=4)
        if not res.success or "NO_WINDOW" in res.stdout:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="get_active_tab_info",
                error=f"{browser} has no open windows or tabs, or is not running.",
            )

        parts = res.stdout.split("|||")
        title = parts[0].strip() if len(parts) > 0 else ""
        url = parts[1].strip() if len(parts) > 1 else ""

        return ExecutionResult(
            success=True,
            capability=self.name,
            action="get_active_tab_info",
            data={"browser": browser, "title": title, "url": url},
            evidence={"title": title, "url": url},
            verification={"tab_queried": True},
        )

    def read_page_text(self, browser: str = "Safari", max_chars: int = 2000) -> ExecutionResult:
        b_lower = browser.lower().strip()

        if "chrome" in b_lower:
            script = """
            tell application "Google Chrome"
                if not (exists window 1) then return "NO_WINDOW"
                return execute active tab of window 1 javascript "document.body.innerText"
            end tell
            """
        else:
            script = """
            tell application "Safari"
                if not (exists document 1) then return "NO_WINDOW"
                return do JavaScript "document.body.innerText" in current tab of window 1
            end tell
            """

        res = run_applescript(script, timeout=6)
        if not res.success or "NO_WINDOW" in res.stdout:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="read_page_text",
                error=res.stderr or f"Cannot extract text from {browser}. Ensure the browser has a page open.",
            )

        text = res.stdout.strip()
        truncated = text[:max_chars]
        return ExecutionResult(
            success=True,
            capability=self.name,
            action="read_page_text",
            data={"browser": browser, "char_count": len(text), "text": truncated},
            evidence={"chars_extracted": len(text)},
            verification={"page_text_extracted": True},
        )
