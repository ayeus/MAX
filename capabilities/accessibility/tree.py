"""Accessibility tree extractor for macOS applications using System Events and Accessibility APIs."""

import json
import logging
from typing import Any, Optional
from macos.applescript import run_applescript, escape_applescript_string
from capabilities.accessibility.models import UIElement, ComputerState

logger = logging.getLogger(__name__)


class AccessibilityTreeExtractor:
    """Extracts structured, bounded semantic UI element trees from macOS applications."""

    def __init__(self, max_depth: int = 4, max_elements: int = 40):
        self.max_depth = max_depth
        self.max_elements = max_elements

    def get_computer_state(self, application_name: Optional[str] = None) -> ComputerState:
        """Extract structured ComputerState for the specified or frontmost application."""
        app_clause = ""
        if application_name and application_name.strip():
            clean_app = escape_applescript_string(application_name.strip())
            app_clause = f'set targetProc to first process whose name is "{clean_app}" or name contains "{clean_app}"'
        else:
            app_clause = 'set targetProc to first process whose frontmost is true'

        script = f"""
        tell application "System Events"
            try
                {app_clause}
                set procName to name of targetProc
                set winTitle to ""
                set winPos to {{0, 0}}
                set winSize to {{0, 0}}
                set allWins to {{}}

                try
                    set allWins to name of every window of targetProc
                end try

                set hasWin to false
                if (count of windows of targetProc) > 0 then
                    set targetWin to window 1 of targetProc
                    set hasWin to true
                    try
                        set winTitle to name of targetWin
                    end try
                    try
                        set winPos to position of targetWin
                        set winSize to size of targetWin
                    end try
                end if

                set elemList to {{}}
                if hasWin then
                    -- Extract direct controls and 1-level container children
                    set targetRoles to {{"AXButton", "AXTextField", "AXTextArea", "AXSearchField", "AXPopUpButton", "AXCheckBox", "AXRadioButton", "AXTabGroup", "AXStaticText", "AXLink"}}
                    
                    -- Query top-level elements
                    try
                        set topElems to every UI element of targetWin
                        repeat with el in topElems
                            try
                                set r to role of el
                                if r is in targetRoles then
                                    set n to ""
                                    set v to ""
                                    set d to ""
                                    set f to false
                                    try
                                        set n to name of el
                                    end try
                                    try
                                        set v to (value of el) as string
                                    end try
                                    try
                                        set d to description of el
                                    end try
                                    try
                                        set f to (focused of el)
                                    end try
                                    if (n is "missing value") then set n to ""
                                    if (v is "missing value") then set v to ""
                                    if (d is "missing value") then set d to ""
                                    if (n is not "") or (v is not "") or (d is not "") or (r is "AXTextField") or (r is "AXTextArea") then
                                        set end of elemList to (r & "|||" & n & "|||" & v & "|||" & d & "|||" & (f as string))
                                    end if
                                else if r is in {{"AXGroup", "AXScrollArea", "AXSplitGroup", "AXToolbar"}} then
                                    -- Check 1 level down
                                    try
                                        set subElems to every UI element of el
                                        repeat with subEl in subElems
                                            try
                                                set subR to role of subEl
                                                if subR is in targetRoles then
                                                    set subN to ""
                                                    set subV to ""
                                                    set subD to ""
                                                    set subF to false
                                                    try
                                                        set subN to name of subEl
                                                    end try
                                                    try
                                                        set subV to (value of subEl) as string
                                                    end try
                                                    try
                                                        set subD to description of subEl
                                                    end try
                                                    try
                                                        set subF to (focused of subEl)
                                                    end try
                                                    if (subN is "missing value") then set subN to ""
                                                    if (subV is "missing value") then set subV to ""
                                                    if (subD is "missing value") then set subD to ""
                                                    if (subN is not "") or (subV is not "") or (subD is not "") or (subR is "AXTextField") or (subR is "AXTextArea") then
                                                        set end of elemList to (subR & "|||" & subN & "|||" & subV & "|||" & subD & "|||" & (subF as string))
                                                    end if
                                                end if
                                                if (count of elemList) >= {self.max_elements} then exit repeat
                                            end try
                                        end repeat
                                    end try
                                end if
                                if (count of elemList) >= {self.max_elements} then exit repeat
                            end try
                        end repeat
                    end try
                end if

                set outStr to procName & "###" & winTitle & "###" & (winPos as string) & "###" & (winSize as string) & "###"
                repeat with itm in elemList
                    set outStr to outStr & itm & "%%%"
                end repeat
                return outStr
            on error errMsg
                return "ERROR###" & errMsg
            end try
        end tell
        """

        res = run_applescript(script, timeout=4)
        if not res.success or not res.stdout.strip() or res.stdout.strip().startswith("ERROR###"):
            # Fallback observation
            app_name = application_name or "Unknown"
            return ComputerState(
                active_application=app_name,
                active_window_title="",
                interactive_elements=[],
            )

        parts = res.stdout.strip().split("###")
        proc_name = parts[0].strip() if len(parts) > 0 else (application_name or "Unknown")
        win_title = parts[1].strip() if len(parts) > 1 else ""
        pos_raw = parts[2].strip() if len(parts) > 2 else ""
        size_raw = parts[3].strip() if len(parts) > 3 else ""
        elems_block = parts[4].strip() if len(parts) > 4 else ""

        bounds = None
        try:
            p_parts = [float(x.strip()) for x in pos_raw.split(",") if x.strip()]
            s_parts = [float(x.strip()) for x in size_raw.split(",") if x.strip()]
            if len(p_parts) >= 2 and len(s_parts) >= 2:
                bounds = {"x": p_parts[0], "y": p_parts[1], "width": s_parts[0], "height": s_parts[1]}
        except Exception:
            pass

        elements: list[UIElement] = []
        focused_el: Optional[UIElement] = None

        if elems_block:
            for item in elems_block.split("%%%"):
                if not item.strip():
                    continue
                fields = item.split("|||")
                if len(fields) >= 4:
                    role = fields[0].strip()
                    title = fields[1].strip()
                    value = fields[2].strip() if fields[2].strip() else None
                    desc = fields[3].strip() if fields[3].strip() else None
                    is_focused = (fields[4].strip().lower() == "true") if len(fields) >= 5 else False

                    el = UIElement(
                        role=role,
                        title=title,
                        value=value,
                        description=desc,
                        is_focused=is_focused,
                        actions=["AXPress"] if "Button" in role else ["AXConfirm"],
                    )
                    elements.append(el)
                    if is_focused and not focused_el:
                        focused_el = el

        return ComputerState(
            active_application=proc_name,
            active_window_title=win_title,
            active_window_bounds=bounds,
            focused_element=focused_el,
            interactive_elements=elements,
        )


tree_extractor = AccessibilityTreeExtractor()
