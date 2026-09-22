"""macOS GUI and Accessibility automation capability for MAX."""

from typing import Any
from capabilities.base import Capability, Operation, ExecutionResult
from macos.applescript import run_applescript
from security.risk import RiskLevel
from security.audit import audit_log


class AccessibilityCapability(Capability):
    name = "accessibility"
    description = (
        "Interact with macOS GUI elements via Accessibility and System Events: "
        "inspect active windows, list and click application menu bar items, "
        "send keystrokes and keyboard shortcuts (Cmd+S, Enter, Tab), and control windows."
    )

    def get_operations(self) -> list[Operation]:
        return [
            Operation(
                name="get_active_window_info",
                description="Query the frontmost application name, window title, position (x, y), and size (width, height).",
                parameters={},
                default_risk=RiskLevel.SAFE,
                handler=self.get_active_window_info,
            ),
            Operation(
                name="list_menu_items",
                description="Inspect the menu bar hierarchy and items of a running application.",
                parameters={
                    "application_name": {"type": "string", "description": "Application name (e.g. 'Google Chrome', 'Finder', or empty for frontmost)"},
                    "menu_name": {"type": "string", "description": "Optional specific menu to inspect (e.g. 'File', 'Edit', 'View')"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.list_menu_items,
            ),
            Operation(
                name="click_menu_item",
                description="Click a menu item in a running application's menu bar (e.g. menu 'File', item 'Save').",
                parameters={
                    "application_name": {"type": "string", "description": "Application name (or empty for frontmost)"},
                    "menu_name": {"type": "string", "description": "Menu title (e.g. 'File', 'Edit', 'Window')"},
                    "item_name": {"type": "string", "description": "Menu item to click (e.g. 'New File', 'Save', 'Close Window')"},
                },
                default_risk=RiskLevel.MEDIUM,
                handler=self.click_menu_item,
            ),
            Operation(
                name="send_keystroke",
                description="Type text or send keystrokes with optional modifier keys (command, shift, option, control).",
                parameters={
                    "text": {"type": "string", "description": "Text to type or special key (e.g. 'return', 'tab', 'escape', 'space')"},
                    "modifiers": {"type": "string", "description": "Comma-separated modifiers: 'command', 'shift', 'option', 'control' (e.g. 'command,shift')"},
                },
                default_risk=RiskLevel.MEDIUM,
                handler=self.send_keystroke,
            ),
            Operation(
                name="close_frontmost_window",
                description="Close the frontmost window of the active application.",
                parameters={},
                default_risk=RiskLevel.LOW,
                handler=self.close_frontmost_window,
            ),
        ]

    def get_active_window_info(self) -> ExecutionResult:
        """Inspect the active process and its front window bounds."""
        script = """
        tell application "System Events"
            set frontProc to first process whose frontmost is true
            set procName to name of frontProc
            set winTitle to ""
            set winPos to {}
            set winSize to {}
            try
                set winTitle to title of window 1 of frontProc
                set winPos to position of window 1 of frontProc
                set winSize to size of window 1 of frontProc
            end try
            return procName & "|||" & winTitle & "|||" & (winPos as string) & "|||" & (winSize as string)
        end tell
        """
        res = run_applescript(script, timeout=4)
        if not res.success:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="get_active_window_info",
                error=res.stderr or "Failed to inspect active window.",
                evidence={"applescript_stderr": res.stderr},
            )

        parts = res.stdout.split("|||")
        proc_name = parts[0].strip() if len(parts) > 0 else "Unknown"
        win_title = parts[1].strip() if len(parts) > 1 else ""
        win_pos_raw = parts[2].strip() if len(parts) > 2 else ""
        win_size_raw = parts[3].strip() if len(parts) > 3 else ""

        return ExecutionResult(
            success=True,
            capability=self.name,
            action="get_active_window_info",
            data={
                "process_name": proc_name,
                "window_title": win_title,
                "position_raw": win_pos_raw,
                "size_raw": win_size_raw,
            },
            evidence={
                "process": proc_name,
                "title": win_title,
                "bounds": f"{win_pos_raw} / {win_size_raw}",
            },
            verification={"queried_system_events": True},
        )

    def list_menu_items(self, application_name: str = "", menu_name: str = "") -> ExecutionResult:
        """Inspect menu bar items or submenu items."""
        app_target = f'process "{application_name.strip()}"' if application_name.strip() else '(first process whose frontmost is true)'

        if menu_name.strip():
            menu_target = menu_name.strip()
            script = f"""
            tell application "System Events" to tell {app_target}
                set menuItems to name of every menu item of menu "{menu_target}" of menu bar item "{menu_target}" of menu bar 1
                return menuItems as string
            end tell
            """
        else:
            script = f"""
            tell application "System Events" to tell {app_target}
                set menuBarItems to name of every menu bar item of menu bar 1
                return menuBarItems as string
            end tell
            """

        res = run_applescript(script, timeout=5)
        if not res.success:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="list_menu_items",
                error=res.stderr or f"Could not list menus for {application_name or 'frontmost app'}.",
                evidence={"stderr": res.stderr},
            )

        items = [i.strip() for i in res.stdout.split(",") if i.strip() and i.strip() != "missing value"]
        return ExecutionResult(
            success=True,
            capability=self.name,
            action="list_menu_items",
            data={"application": application_name or "frontmost", "menu": menu_name or "menu_bar", "items": items},
            evidence={"count": len(items), "items": items},
            verification={"menu_queried": True},
        )

    def click_menu_item(self, menu_name: str, item_name: str, application_name: str = "") -> ExecutionResult:
        """Click a menu item in an application."""
        audit_log.log_event(
            event_type="tool_requested",
            tool=self.name,
            action="click_menu_item",
            details={"application": application_name, "menu": menu_name, "item": item_name},
        )

        app_target = f'process "{application_name.strip()}"' if application_name.strip() else '(first process whose frontmost is true)'
        menu_clean = menu_name.strip().replace('"', '\\"')
        item_clean = item_name.strip().replace('"', '\\"')

        script = f"""
        tell application "System Events" to tell {app_target}
            click menu item "{item_clean}" of menu "{menu_clean}" of menu bar item "{menu_clean}" of menu bar 1
        end tell
        """

        res = run_applescript(script, timeout=5)
        audit_log.log_event(
            event_type="tool_completed" if res.success else "tool_failed",
            tool=self.name,
            action="click_menu_item",
            details={"success": res.success, "stderr": res.stderr},
            success=res.success,
        )

        return ExecutionResult(
            success=res.success,
            capability=self.name,
            action="click_menu_item",
            data={"application": application_name or "frontmost", "menu": menu_name, "item": item_name},
            evidence={"exit_code": res.exit_code, "stdout": res.stdout, "stderr": res.stderr},
            verification={"menu_item_clicked": res.success},
            error=res.stderr if not res.success else None,
        )

    def send_keystroke(self, text: str, modifiers: str = "") -> ExecutionResult:
        """Simulate typing text or pressing key combinations."""
        mod_list = []
        if modifiers:
            for m in modifiers.split(","):
                m_clean = m.strip().lower()
                if m_clean in ("command", "cmd"):
                    mod_list.append("command down")
                elif m_clean == "shift":
                    mod_list.append("shift down")
                elif m_clean in ("option", "alt"):
                    mod_list.append("option down")
                elif m_clean in ("control", "ctrl"):
                    mod_list.append("control down")

        using_clause = f" using {{{', '.join(mod_list)}}}" if mod_list else ""

        # Check special keys
        special_keys = {
            "return": "key code 36",
            "enter": "key code 36",
            "tab": "key code 48",
            "space": "key code 49",
            "delete": "key code 51",
            "backspace": "key code 51",
            "escape": "key code 53",
            "esc": "key code 53",
            "down": "key code 125",
            "up": "key code 126",
            "left": "key code 123",
            "right": "key code 124",
        }

        key_lower = text.strip().lower()
        if key_lower in special_keys:
            action_snippet = f"{special_keys[key_lower]}{using_clause}"
        else:
            escaped_text = text.replace("\\", "\\\\").replace('"', '\\"')
            action_snippet = f'keystroke "{escaped_text}"{using_clause}'

        script = f"""
        tell application "System Events"
            {action_snippet}
        end tell
        """

        res = run_applescript(script, timeout=4)
        return ExecutionResult(
            success=res.success,
            capability=self.name,
            action="send_keystroke",
            data={"text": text, "modifiers": modifiers},
            evidence={"applescript_exit_code": res.exit_code},
            verification={"keystroke_sent": res.success},
            error=res.stderr if not res.success else None,
        )

    def close_frontmost_window(self) -> ExecutionResult:
        """Close the active window."""
        script = """
        tell application "System Events"
            set frontProc to first process whose frontmost is true
            tell frontProc to click (first button of window 1 whose subrole is "AXCloseButton")
        end tell
        """
        res = run_applescript(script, timeout=3)
        return ExecutionResult(
            success=res.success,
            capability=self.name,
            action="close_frontmost_window",
            evidence={"exit_code": res.exit_code},
            verification={"close_button_clicked": res.success},
            error=res.stderr if not res.success else None,
        )
