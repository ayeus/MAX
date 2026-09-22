"""macOS GUI and Accessibility automation capability for MAX."""

import logging
import time
from typing import Any, Optional

from capabilities.base import Capability, Operation, ExecutionResult
from macos.applescript import run_applescript, escape_applescript_string
from security.risk import RiskLevel
from security.audit import audit_log

from capabilities.accessibility.models import UIElement, ComputerState
from capabilities.accessibility.tree import tree_extractor
from capabilities.accessibility.grounding import (
    ui_grounder,
    TargetConstraints,
    GroundingConfidence,
)
from capabilities.accessibility.mouse import click_screen_coordinates, scroll_wheel, is_mouse_available

logger = logging.getLogger(__name__)


class AccessibilityCapability(Capability):
    name = "accessibility"
    description = (
        "Interact with macOS GUI elements via Accessibility and System Events: "
        "inspect computer state and active windows, locate buttons and text inputs semantically, "
        "click elements, type into text fields, send keystrokes/shortcuts (Cmd+S, Enter, Tab), "
        "and control application menus and windows."
    )

    def get_operations(self) -> list[Operation]:
        return [
            Operation(
                name="get_computer_state",
                description="Inspect the current active application GUI state, visible window title, and all interactive elements (buttons, inputs, text areas).",
                parameters={
                    "application_name": {"type": "string", "description": "Optional application name to inspect (defaults to frontmost)"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.get_computer_state,
            ),
            Operation(
                name="find_element",
                description="Search for a semantic UI element (button, text field, checkbox) in the active window by label, role, or description without acting.",
                parameters={
                    "label": {"type": "string", "description": "Label, title, placeholder, or accessible text of the target element"},
                    "role": {"type": "string", "description": "Optional element role (e.g. 'button', 'text_field', 'checkbox', 'popup_button')"},
                    "identifier": {"type": "string", "description": "Optional accessibility identifier"},
                    "application_name": {"type": "string", "description": "Optional application name (defaults to frontmost)"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.find_element,
            ),
            Operation(
                name="click_element",
                description="Semantically locate and click a button, link, tab, or interactive element in the active window.",
                parameters={
                    "label": {"type": "string", "description": "Label, title, or accessible description of the element to click (e.g. 'New Document', 'Save', 'Submit')"},
                    "role": {"type": "string", "description": "Optional role constraint (e.g. 'button', 'checkbox', 'tab')"},
                    "identifier": {"type": "string", "description": "Optional accessibility identifier"},
                    "application_name": {"type": "string", "description": "Optional application name (defaults to frontmost)"},
                },
                default_risk=RiskLevel.MEDIUM,
                handler=self.click_element,
            ),
            Operation(
                name="type_into_element",
                description="Focus an input field or text area and type text into it. Can optionally clear existing text first or press Return.",
                parameters={
                    "text": {"type": "string", "description": "The text content to type into the field"},
                    "target_label": {"type": "string", "description": "Optional label/placeholder of the target input field (e.g. 'Search', 'Message', 'Recipient')"},
                    "clear_first": {"type": "boolean", "description": "Whether to select all and delete existing text before typing (default: false)"},
                    "press_return": {"type": "boolean", "description": "Whether to press Return/Enter after typing (default: false)"},
                    "application_name": {"type": "string", "description": "Optional application name (defaults to frontmost)"},
                },
                default_risk=RiskLevel.MEDIUM,
                handler=self.type_into_element,
            ),
            Operation(
                name="focus_element",
                description="Move keyboard focus to a specific UI element in the active window.",
                parameters={
                    "label": {"type": "string", "description": "Label or description of the element to focus"},
                    "role": {"type": "string", "description": "Optional role constraint (e.g. 'text_field', 'search')"},
                    "application_name": {"type": "string", "description": "Optional application name (defaults to frontmost)"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.focus_element,
            ),
            Operation(
                name="send_key_chord",
                description="Send a keyboard shortcut combination (e.g. key 's' with modifiers 'command' to Save, or key 'return').",
                parameters={
                    "key": {"type": "string", "description": "Key character (e.g. 's', 'c', 'v') or special key ('return', 'tab', 'escape', 'space')"},
                    "modifiers": {"type": "string", "description": "Comma-separated modifiers: 'command', 'shift', 'option', 'control' (e.g. 'command,shift')"},
                },
                default_risk=RiskLevel.MEDIUM,
                handler=self.send_key_chord,
            ),
            Operation(
                name="scroll",
                description="Scroll the active window or view up or down.",
                parameters={
                    "direction": {"type": "string", "description": "Scroll direction: 'down' or 'up' (default: 'down')"},
                    "amount": {"type": "integer", "description": "Number of scroll lines/units (default: 5)"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.scroll,
            ),
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

    def get_computer_state(self, application_name: str = "") -> ExecutionResult:
        """Inspect the current GUI state of the active or target application."""
        try:
            state = tree_extractor.get_computer_state(application_name=application_name if application_name.strip() else None)
            summary = state.to_compact_prompt_summary()
            return ExecutionResult(
                success=True,
                capability=self.name,
                action="get_computer_state",
                data=summary,
                evidence={
                    "active_application": state.active_application,
                    "window_title": state.active_window_title,
                    "interactive_controls_count": len(state.interactive_elements),
                },
                verification={"inspected_state": True},
            )
        except Exception as e:
            logger.exception("Failed to get computer state")
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="get_computer_state",
                error=f"Error inspecting computer state: {e}",
            )

    def find_element(
        self,
        label: str = "",
        role: str = "",
        identifier: str = "",
        application_name: str = "",
    ) -> ExecutionResult:
        """Locate a semantic UI element in the computer state without performing an action."""
        state = tree_extractor.get_computer_state(application_name=application_name if application_name.strip() else None)
        constraints = TargetConstraints(
            label=label if label.strip() else None,
            role=role if role.strip() else None,
            identifier=identifier if identifier.strip() else None,
        )
        match = ui_grounder.ground(constraints, state)

        if not match.element:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="find_element",
                error=match.rationale,
                data={"confidence": match.confidence.value, "alternatives": match.alternative_labels},
                evidence={"grounding_failed": True, "candidates_count": match.candidates_count},
            )

        return ExecutionResult(
            success=True,
            capability=self.name,
            action="find_element",
            data={
                "element": match.element.to_summary_dict(),
                "confidence": match.confidence.value,
                "score": match.score,
                "rationale": match.rationale,
            },
            evidence={
                "matched_role": match.element.role,
                "matched_title": match.element.title,
                "confidence": match.confidence.value,
            },
            verification={"element_found": True},
        )

    def click_element(
        self,
        label: str = "",
        role: str = "",
        identifier: str = "",
        application_name: str = "",
    ) -> ExecutionResult:
        """Semantically locate and click an interactive UI element."""
        audit_log.log_event(
            event_type="tool_requested",
            tool=self.name,
            action="click_element",
            details={"label": label, "role": role, "application": application_name},
        )

        state = tree_extractor.get_computer_state(application_name=application_name if application_name.strip() else None)
        constraints = TargetConstraints(
            label=label if label.strip() else None,
            role=role if role.strip() else None,
            identifier=identifier if identifier.strip() else None,
        )
        match = ui_grounder.ground(constraints, state)

        if not match.is_reliable:
            audit_log.log_event(
                event_type="tool_failed",
                tool=self.name,
                action="click_element",
                details={"reason": match.rationale, "confidence": match.confidence.value},
                success=False,
            )
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="click_element",
                error=match.rationale or f"Could not reliably locate element '{label}' to click.",
                data={"confidence": match.confidence.value, "alternatives": match.alternative_labels},
                evidence={"grounding_reliable": False, "rationale": match.rationale},
            )

        target = match.element
        clean_target_text = escape_applescript_string(target.title or target.description or label)
        app_clause = f'process "{escape_applescript_string(state.active_application)}"'

        # Method 1: Semantic Accessibility click via System Events
        script = f"""
        tell application "System Events" to tell {app_clause}
            set targetWin to window 1
            try
                -- Attempt click by button title or name
                if (exists (first button of targetWin whose title is "{clean_target_text}" or name is "{clean_target_text}")) then
                    click (first button of targetWin whose title is "{clean_target_text}" or name is "{clean_target_text}")
                    return "clicked_button"
                end if
            end try
            try
                -- Attempt click by generic UI element title or name
                if (exists (first UI element of targetWin whose title is "{clean_target_text}" or name is "{clean_target_text}" or description is "{clean_target_text}")) then
                    click (first UI element of targetWin whose title is "{clean_target_text}" or name is "{clean_target_text}" or description is "{clean_target_text}")
                    return "clicked_element"
                end if
            end try
            try
                -- Search inside containers (scroll areas, groups, toolbars)
                repeat with container in {{scroll area 1 of targetWin, group 1 of targetWin, toolbar 1 of targetWin}}
                    try
                        if (exists (first button of container whose title is "{clean_target_text}" or name is "{clean_target_text}")) then
                            click (first button of container whose title is "{clean_target_text}" or name is "{clean_target_text}")
                            return "clicked_container_button"
                        end if
                    end try
                end repeat
            end try
            return "not_clicked"
        end tell
        """

        res = run_applescript(script, timeout=5)
        click_success = res.success and ("clicked_" in res.stdout)
        click_method = res.stdout.strip() if click_success else "failed_applescript"

        # Method 2: Coordinate click fallback if bounds are available
        if not click_success and target.bounds and is_mouse_available():
            b = target.bounds
            cx = b.get("x", 0) + b.get("width", 0) / 2
            cy = b.get("y", 0) + b.get("height", 0) / 2
            if cx > 0 and cy > 0:
                logger.info("Falling back to coordinate click at (%s, %s)", cx, cy)
                click_success = click_screen_coordinates(cx, cy)
                click_method = f"coordinate_click_({int(cx)},{int(cy)})"

        audit_log.log_event(
            event_type="tool_completed" if click_success else "tool_failed",
            tool=self.name,
            action="click_element",
            details={"success": click_success, "method": click_method, "target": target.to_summary_dict()},
            success=click_success,
        )

        return ExecutionResult(
            success=click_success,
            capability=self.name,
            action="click_element",
            data={
                "target": target.to_summary_dict(),
                "method": click_method,
                "confidence": match.confidence.value,
            },
            evidence={
                "grounded_role": target.role,
                "grounded_title": target.title or target.description,
                "method": click_method,
                "applescript_stdout": res.stdout,
            },
            verification={"element_clicked": click_success},
            error=None if click_success else f"Failed to click element '{label}'. Applescript output: {res.stdout.strip()} {res.stderr.strip()}",
        )

    def type_into_element(
        self,
        text: str,
        target_label: str = "",
        clear_first: bool = False,
        press_return: bool = False,
        application_name: str = "",
    ) -> ExecutionResult:
        """Focus an input field and type text into it."""
        audit_log.log_event(
            event_type="tool_requested",
            tool=self.name,
            action="type_into_element",
            details={"text_length": len(text), "target_label": target_label, "clear_first": clear_first},
        )

        # 1. If target label is specified, focus the input field first
        if target_label.strip():
            state = tree_extractor.get_computer_state(application_name=application_name if application_name.strip() else None)
            constraints = TargetConstraints(
                label=target_label.strip(),
                role="text_field",
            )
            match = ui_grounder.ground(constraints, state)
            if match.is_reliable and match.element:
                target = match.element
                clean_target = escape_applescript_string(target.title or target.description or target_label)
                app_clause = f'process "{escape_applescript_string(state.active_application)}"'
                focus_script = f"""
                tell application "System Events" to tell {app_clause}
                    set targetWin to window 1
                    try
                        set focused of (first text field of targetWin whose title is "{clean_target}" or description is "{clean_target}") to true
                        return "focused_text_field"
                    end try
                    try
                        set focused of (first text area of targetWin whose title is "{clean_target}" or description is "{clean_target}") to true
                        return "focused_text_area"
                    end try
                    try
                        repeat with container in {{scroll area 1 of targetWin, group 1 of targetWin}}
                            try
                                set focused of (first text area of container) to true
                                return "focused_container_text_area"
                            end try
                        end repeat
                    end try
                    return "focus_attempted"
                end tell
                """
                run_applescript(focus_script, timeout=3)
                time.sleep(0.1)

        # 2. Clear existing text if requested (Cmd+A, Delete)
        if clear_first:
            self.send_keystroke(text="a", modifiers="command")
            time.sleep(0.05)
            self.send_keystroke(text="delete")
            time.sleep(0.05)

        # 3. Type the text
        type_res = self.send_keystroke(text=text)
        if not type_res.success:
            return type_res

        # 4. Press return if requested
        if press_return:
            time.sleep(0.05)
            self.send_keystroke(text="return")

        audit_log.log_event(
            event_type="tool_completed",
            tool=self.name,
            action="type_into_element",
            details={"text_length": len(text), "target": target_label, "press_return": press_return},
            success=True,
        )

        return ExecutionResult(
            success=True,
            capability=self.name,
            action="type_into_element",
            data={
                "text_length": len(text),
                "target_label": target_label,
                "clear_first": clear_first,
                "press_return": press_return,
            },
            evidence={"keystrokes_dispatched": True, "chars_count": len(text)},
            verification={"typed_successfully": True},
        )

    def focus_element(
        self,
        label: str,
        role: str = "",
        application_name: str = "",
    ) -> ExecutionResult:
        """Focus a UI element in the active window."""
        state = tree_extractor.get_computer_state(application_name=application_name if application_name.strip() else None)
        constraints = TargetConstraints(label=label, role=role if role.strip() else None)
        match = ui_grounder.ground(constraints, state)

        if not match.is_reliable or not match.element:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="focus_element",
                error=match.rationale or f"Could not find element '{label}' to focus.",
            )

        target = match.element
        clean_target = escape_applescript_string(target.title or target.description or label)
        app_clause = f'process "{escape_applescript_string(state.active_application)}"'
        script = f"""
        tell application "System Events" to tell {app_clause}
            set targetWin to window 1
            try
                set focused of (first UI element of targetWin whose title is "{clean_target}" or description is "{clean_target}") to true
                return "focused"
            end try
            return "not_focused"
        end tell
        """
        res = run_applescript(script, timeout=4)
        focused = "focused" in res.stdout
        return ExecutionResult(
            success=focused,
            capability=self.name,
            action="focus_element",
            data={"target": target.to_summary_dict()},
            evidence={"focus_result": res.stdout.strip()},
            verification={"focused": focused},
            error=None if focused else f"Could not focus element '{label}'.",
        )

    def send_key_chord(self, key: str, modifiers: str = "") -> ExecutionResult:
        """Send a keyboard shortcut combination."""
        audit_log.log_event(
            event_type="tool_requested",
            tool=self.name,
            action="send_key_chord",
            details={"key": key, "modifiers": modifiers},
        )
        return self.send_keystroke(text=key, modifiers=modifiers)

    def scroll(self, direction: str = "down", amount: int = 5) -> ExecutionResult:
        """Scroll the active window up or down."""
        dir_clean = direction.strip().lower()
        multiplier = 1 if dir_clean == "up" else -1
        delta = multiplier * max(1, amount)

        if is_mouse_available():
            ok = scroll_wheel(delta)
            if ok:
                return ExecutionResult(
                    success=True,
                    capability=self.name,
                    action="scroll",
                    data={"direction": dir_clean, "amount": amount, "method": "CoreGraphics"},
                    evidence={"scroll_delta": delta},
                    verification={"scrolled": True},
                )

        # Fallback: send arrow keys
        key = "up" if dir_clean == "up" else "down"
        for _ in range(min(amount, 10)):
            self.send_keystroke(text=key)
            time.sleep(0.02)

        return ExecutionResult(
            success=True,
            capability=self.name,
            action="scroll",
            data={"direction": dir_clean, "amount": amount, "method": "keystrokes"},
            evidence={"keystroke": key, "count": amount},
            verification={"scrolled": True},
        )

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
