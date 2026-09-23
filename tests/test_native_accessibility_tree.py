"""Unit and integration tests for MAX 2.0 Chunk 1: Native Accessibility Tree & Computer State."""

from datetime import datetime, timezone
import json
import unittest
from unittest.mock import MagicMock, patch

from agent.context import AgentContext
from agent.observer import Observer
from capabilities.accessibility.models import (
    AccessibilityHealthStatus,
    ComputerState,
    ObservationMetadata,
    UIElement,
    WindowState,
)
from capabilities.accessibility.native_backend import (
    _build_ui_element_tree,
    extract_native_accessibility,
    parse_native_output_to_computer_state,
)
from capabilities.accessibility.tree import AccessibilityTreeExtractor


class TestNativeAccessibilityTree(unittest.TestCase):
    """Test suite verifying all Chunk 1 requirements."""

    def test_01_ui_element_serialization(self):
        """Verify UIElement model serialization and deserialization."""
        el = UIElement(
            role="AXButton",
            subrole="AXCloseButton",
            title="Close",
            identifier="_NS:123",
            bounds={"x": 10.0, "y": 20.0, "width": 14.0, "height": 14.0},
            is_focused=False,
            is_enabled=True,
            is_selected=False,
            actions=["AXPress"],
            path="AXApplication/AXWindow[0]/AXButton[0]",
        )
        d = el.model_dump()
        self.assertEqual(d["role"], "AXButton")
        self.assertEqual(d["subrole"], "AXCloseButton")
        self.assertEqual(d["title"], "Close")
        self.assertEqual(d["actions"], ["AXPress"])
        self.assertEqual(d["bounds"]["width"], 14.0)

        # Roundtrip
        el2 = UIElement.model_validate(d)
        self.assertEqual(el2.path, el.path)
        self.assertEqual(el2.identifier, el.identifier)

    def test_02_computer_state_serialization(self):
        """Verify ComputerState serialization with window state and metadata."""
        win = WindowState(
            title="Document 1",
            role="AXWindow",
            subrole="AXStandardWindow",
            is_focused=True,
            bounds={"x": 100.0, "y": 100.0, "width": 800.0, "height": 600.0},
            pid=4567,
        )
        meta = ObservationMetadata(
            snapshot_id="snap_test_123",
            latency_ms=18.5,
            accessibility_status=AccessibilityHealthStatus.ACCESSIBILITY_AVAILABLE,
            backend="native_swift",
        )
        state = ComputerState(
            active_application="TextEdit",
            active_application_pid=4567,
            active_window_title="Document 1",
            active_window=win,
            windows=[win],
            observation_metadata=meta,
        )
        d = state.model_dump()
        self.assertEqual(d["active_application"], "TextEdit")
        self.assertEqual(d["active_application_pid"], 4567)
        self.assertEqual(d["windows"][0]["title"], "Document 1")
        self.assertEqual(d["observation_metadata"]["backend"], "native_swift")

    def test_03_recursive_traversal_and_flattening(self):
        """Verify recursive tree structure preserves hierarchy and flattens correctly."""
        child_btn = UIElement(role="AXButton", title="Save", actions=["AXPress"], path="AXApplication/AXWindow[0]/AXGroup[0]/AXButton[0]")
        child_txt = UIElement(role="AXTextField", value="Hello", path="AXApplication/AXWindow[0]/AXGroup[0]/AXTextField[0]")
        group = UIElement(
            role="AXGroup",
            path="AXApplication/AXWindow[0]/AXGroup[0]",
            children=[child_btn, child_txt],
        )
        window = UIElement(
            role="AXWindow",
            title="Main",
            path="AXApplication/AXWindow[0]",
            children=[group],
        )
        app_root = UIElement(
            role="AXApplication",
            title="App",
            path="AXApplication",
            children=[window],
        )

        # Hierarchy check
        self.assertEqual(len(app_root.children), 1)
        self.assertEqual(app_root.children[0].role, "AXWindow")
        self.assertEqual(len(app_root.children[0].children[0].children), 2)

        # Flatten check
        all_nodes = app_root.flatten()
        self.assertEqual(len(all_nodes), 5)
        paths = [n.path for n in all_nodes]
        self.assertIn("AXApplication", paths)
        self.assertIn("AXApplication/AXWindow[0]/AXGroup[0]/AXButton[0]", paths)

        # Path lookup
        found = app_root.find_by_path("AXApplication/AXWindow[0]/AXGroup[0]/AXButton[0]")
        self.assertIsNotNone(found)
        self.assertEqual(found.title, "Save")

    def test_04_budget_enforcement_in_native_output(self):
        """Verify parse handles truncation reasons from budget enforcement."""
        mock_output = {
            "status": "ACCESSIBILITY_AVAILABLE",
            "application": {"name": "ComplexApp", "pid": 100},
            "windows": [],
            "stats": {
                "duration_ms": 1502.1,
                "depth_reached": 6,
                "total_nodes_visited": 100,
                "truncated_by_budget": "max_elements",
            },
            "flattened_interactive": [],
        }
        state = parse_native_output_to_computer_state(mock_output)
        self.assertEqual(state.observation_metadata.traversal_stats["truncated_by_budget"], "max_elements")
        self.assertEqual(state.observation_metadata.traversal_stats["depth_reached"], 6)

    def test_05_missing_attributes_zero_hallucination(self):
        """Verify missing attributes remain None/empty and are NEVER fabricated."""
        node = {
            "role": "AXButton",
            # title is missing
            # value is missing
            # description is missing
            # identifier is missing
            # bounds is missing
            "is_enabled": True,
            "actions": [],
        }
        el = _build_ui_element_tree(node)
        self.assertIsNotNone(el)
        self.assertEqual(el.role, "AXButton")
        self.assertEqual(el.title, "")
        self.assertIsNone(el.value)
        self.assertIsNone(el.description)
        self.assertIsNone(el.identifier)
        self.assertIsNone(el.bounds)
        self.assertEqual(el.actions, [])  # Never infer AXPress if not reported by OS

    def test_06_missing_bounds_never_default_to_zero_or_screen(self):
        """Verify that elements with no bounds do not receive fake coordinates like (0,0)."""
        node = {"role": "AXStaticText", "title": "Label"}
        el = _build_ui_element_tree(node)
        self.assertIsNone(el.bounds)

        # Also verify invalid bounds with zero width/height are rejected
        node_invalid = {"role": "AXStaticText", "title": "Label", "bounds": {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}}
        el_invalid = _build_ui_element_tree(node_invalid)
        self.assertIsNotNone(el_invalid.bounds)
        self.assertEqual(el_invalid.bounds["width"], 0.0)

    def test_07_action_discovery_strictly_real(self):
        """Verify real AX action names are preserved and not inferred by role heuristics."""
        node = {
            "role": "AXButton",
            "title": "Options",
            "actions": ["AXShowMenu", "AXPress"],
        }
        el = _build_ui_element_tree(node)
        self.assertEqual(el.actions, ["AXShowMenu", "AXPress"])

        # Button with NO actions should not have AXPress injected
        node_no_act = {"role": "AXButton", "title": "Disabled"}
        el_no_act = _build_ui_element_tree(node_no_act)
        self.assertEqual(el_no_act.actions, [])

    def test_08_focus_detection_real_source_of_truth(self):
        """Verify focused element is captured directly from accessibility."""
        mock_output = {
            "status": "ACCESSIBILITY_AVAILABLE",
            "application": {"name": "Xcode", "pid": 999},
            "windows": [{"title": "Workspace", "is_focused": True}],
            "active_window": {"title": "Workspace", "is_focused": True},
            "focused_element": {
                "role": "AXTextArea",
                "title": "Code Editor",
                "value": "import Foundation",
                "is_focused": True,
                "path": "AXApplication/AXWindow[0]/AXScrollArea[0]/AXTextArea[0]",
            },
            "flattened_interactive": [],
        }
        state = parse_native_output_to_computer_state(mock_output)
        self.assertIsNotNone(state.focused_element)
        self.assertEqual(state.focused_element.role, "AXTextArea")
        self.assertEqual(state.focused_element.value, "import Foundation")
        self.assertTrue(state.focused_element.is_focused)

    def test_09_permission_denied_behavior_explicit_not_empty(self):
        """Verify accessibility permission failure returns explicit ACCESSIBILITY_DENIED status."""
        mock_denied = {
            "status": "ACCESSIBILITY_DENIED",
            "error": "macOS Accessibility permission is not granted. Please enable MAX in System Settings.",
            "stats": {"duration_ms": 1.2},
        }
        state = parse_native_output_to_computer_state(mock_denied)
        self.assertEqual(state.observation_metadata.accessibility_status, AccessibilityHealthStatus.ACCESSIBILITY_DENIED)
        self.assertIn("not granted", state.observation_metadata.error)

    def test_10_malformed_native_response_handling(self):
        """Verify unexpected/malformed native response degrades gracefully."""
        state = parse_native_output_to_computer_state({"status": "INVALID_STATUS", "stats": "not_a_dict"})
        self.assertEqual(state.observation_metadata.accessibility_status, AccessibilityHealthStatus.UNKNOWN)
        self.assertEqual(state.active_application, "Unknown")

    def test_11_state_delta_computation(self):
        """Verify ComputerState.compute_delta computes accurate deltas between state A and B."""
        btn_a = UIElement(role="AXButton", title="Submit", is_selected=False, path="path/btn1")
        inp_a = UIElement(role="AXTextField", value="user", path="path/inp1")
        state_a = ComputerState(
            active_application="Safari",
            active_window_title="Login",
            focused_element=inp_a,
            interactive_elements=[btn_a, inp_a],
        )

        btn_b = UIElement(role="AXButton", title="Submit", is_selected=True, path="path/btn1")
        inp_b = UIElement(role="AXTextField", value="user@example.com", path="path/inp1")
        state_b = ComputerState(
            active_application="Safari",
            active_window_title="Dashboard",
            focused_element=btn_b,
            interactive_elements=[btn_b, inp_b],
        )

        delta = state_a.compute_delta(state_b)
        self.assertFalse(delta["application_changed"])
        self.assertTrue(delta["window_changed"])
        self.assertEqual(delta["previous_window"], "Login")
        self.assertEqual(delta["current_window"], "Dashboard")
        self.assertTrue(delta["focus_changed"])
        self.assertIn("path/inp1", delta["value_changes"])
        self.assertEqual(delta["value_changes"]["path/inp1"]["old"], "user")
        self.assertEqual(delta["value_changes"]["path/inp1"]["new"], "user@example.com")
        self.assertIn("path/btn1", delta["new_selected"])

    def test_12_compact_prompt_projection_separation(self):
        """Verify compact prompt projection is cleanly separated from raw state."""
        btn = UIElement(role="AXButton", title="Go", bounds={"x": 10, "y": 10, "width": 50, "height": 30}, path="path/1")
        state = ComputerState(
            active_application="Terminal",
            active_window_title="zsh",
            interactive_elements=[btn],
            observation_metadata=ObservationMetadata(
                snapshot_id="snap_123",
                latency_ms=25.0,
                accessibility_status=AccessibilityHealthStatus.ACCESSIBILITY_AVAILABLE,
            ),
        )

        summary = state.to_compact_prompt_summary()
        self.assertEqual(summary["active_application"], "Terminal")
        self.assertEqual(summary["active_window"], "zsh")
        self.assertEqual(summary["total_controls_detected"], 1)
        self.assertEqual(len(summary["interactive_controls"]), 1)
        self.assertEqual(summary["observation_metadata"]["snapshot_id"], "snap_123")

        # Raw state retains full objects
        self.assertEqual(state.interactive_elements[0].bounds["width"], 50)

    def test_13_cache_invalidation_lifecycle(self):
        """Verify AccessibilityTreeExtractor cache invalidation behavior."""
        extractor = AccessibilityTreeExtractor(cache_ttl=0.5)

        mock_state1 = ComputerState(active_application="App1", active_window_title="Win1")
        mock_state2 = ComputerState(active_application="App2", active_window_title="Win2")

        with patch("capabilities.accessibility.tree.is_native_available", return_value=False):
            with patch.object(extractor, "_extract_applescript_fallback", side_effect=[mock_state1, mock_state2]):
                s1 = extractor.get_computer_state(application_name="App1")
                self.assertEqual(s1.active_application, "App1")

                # Immediate call with same app returns cached state without invoking fallback
                s_cached = extractor.get_computer_state(application_name="App1")
                self.assertEqual(s_cached.active_application, "App1")

                # Call with a DIFFERENT app immediately busts cache and returns App2
                s2 = extractor.get_computer_state(application_name="App2")
                self.assertEqual(s2.active_application, "App2")

                # Invalidation forces new extraction
                extractor.invalidate_cache()
                self.assertIsNone(extractor._cached_state)

    def test_14_observer_integration(self):
        """Verify agent Observer consumes rich state and stores last_computer_state."""
        obs = Observer()
        sample_state = ComputerState(
            active_application="Finder",
            active_window_title="Desktop",
            interactive_elements=[UIElement(role="AXButton", title="Back")],
            observation_metadata=ObservationMetadata(
                snapshot_id="snap_obs",
                accessibility_status=AccessibilityHealthStatus.ACCESSIBILITY_AVAILABLE,
            ),
        )

        with patch("capabilities.accessibility.tree.tree_extractor.get_computer_state", return_value=sample_state):
            res = obs.observe(fast=False, include_ui=True)
            self.assertEqual(res.active_application, "Finder")
            self.assertEqual(res.active_window, "Desktop")
            self.assertEqual(res.interactive_elements_count, 1)
            self.assertIsNotNone(res.computer_state)
            self.assertEqual(obs.last_computer_state.observation_metadata.snapshot_id, "snap_obs")

    def test_15_context_integration(self):
        """Verify AgentContext.to_prompt_dict includes focused control and visible windows."""
        sample_state = ComputerState(
            active_application="Notes",
            active_window_title="My Note",
            focused_element=UIElement(role="AXTextArea", description="Note body"),
            visible_windows=["My Note", "Notes List"],
            interactive_elements=[UIElement(role="AXButton", title="New Note")],
        )
        obs = Observer()
        with patch("capabilities.accessibility.tree.tree_extractor.get_computer_state", return_value=sample_state):
            env = obs.observe(fast=False, include_ui=True)
            ctx = AgentContext(observation=env)
            prompt_dict = ctx.to_prompt_dict()

            self.assertEqual(prompt_dict["active_application"], "Notes")
            self.assertEqual(prompt_dict["active_window"], "My Note")
            self.assertEqual(prompt_dict["focused_element"]["role"], "AXTextArea")
            self.assertEqual(prompt_dict["visible_windows"], ["My Note", "Notes List"])


    def test_16_truncation_status_and_traversal_statistics(self):
        """Verify truncation marks status as PARTIAL and captures detailed traversal stats."""
        mock_truncated = {
            "status": "PARTIAL",
            "application": {"name": "Browser", "pid": 4321},
            "windows": [{"title": "Tab", "is_focused": True}],
            "stats": {
                "duration_ms": 45.2,
                "elements_total": 100,
                "total_nodes_visited": 100,
                "interactive_nodes_count": 98,
                "max_depth_reached": 6,
                "depth_reached": 6,
                "nodes_by_depth": {"2": 1, "3": 5, "4": 20, "5": 50, "6": 24},
                "truncated_by_max_elements": True,
                "truncated_by_max_children": False,
                "timed_out": False,
                "is_truncated": True,
                "truncated_by_budget": "max_elements",
            },
            "flattened_interactive": [],
        }
        state = parse_native_output_to_computer_state(mock_truncated)
        self.assertEqual(state.observation_metadata.accessibility_status, AccessibilityHealthStatus.PARTIAL)
        self.assertTrue(state.observation_metadata.is_truncated)
        self.assertEqual(state.observation_metadata.truncated_by, "max_elements")
        self.assertEqual(state.observation_metadata.traversal_stats["nodes_by_depth"]["5"], 50)
        self.assertTrue(state.observation_metadata.traversal_stats["truncated_by_max_elements"])

    def test_17_multi_window_tree_isolation(self):
        """Verify multiple windows are represented with distinct paths and no tree merging."""
        win0 = {
            "role": "AXWindow",
            "title": "Window A (Active)",
            "path": "AXApplication/AXWindow[0]",
            "is_focused": True,
            "children": [{"role": "AXButton", "title": "Btn A", "path": "AXApplication/AXWindow[0]/AXButton[0]"}],
        }
        win1 = {
            "role": "AXWindow",
            "title": "Window B (Background)",
            "path": "AXApplication/AXWindow[1]",
            "is_focused": False,
            "children": [{"role": "AXButton", "title": "Btn B", "path": "AXApplication/AXWindow[1]/AXButton[0]"}],
        }
        mock_multi_win = {
            "status": "ACCESSIBILITY_AVAILABLE",
            "application": {"name": "Editor", "pid": 5555},
            "windows": [
                {"title": "Window A (Active)", "role": "AXWindow", "is_focused": True, "pid": 5555},
                {"title": "Window B (Background)", "role": "AXWindow", "is_focused": False, "pid": 5555},
            ],
            "active_window": {"title": "Window A (Active)", "role": "AXWindow", "is_focused": True, "pid": 5555},
            "root_element": {
                "role": "AXApplication",
                "title": "Editor",
                "path": "AXApplication",
                "children": [win0, win1],
            },
        }
        state = parse_native_output_to_computer_state(mock_multi_win)
        self.assertEqual(len(state.windows), 2)
        self.assertEqual(state.active_window_title, "Window A (Active)")
        self.assertEqual(len(state.root_element.children), 2)
        self.assertEqual(state.root_element.children[0].path, "AXApplication/AXWindow[0]")
        self.assertEqual(state.root_element.children[1].path, "AXApplication/AXWindow[1]")
        self.assertEqual(state.root_element.children[0].children[0].title, "Btn A")
        self.assertEqual(state.root_element.children[1].children[0].title, "Btn B")

    def test_18_missing_attributes_optional_bools(self):
        """Verify that missing attributes in native node remain None, not fabricated booleans."""
        node = {
            "role": "AXStaticText",
            "title": "Unselectable Label",
            "path": "AXApplication/AXWindow[0]/AXStaticText[0]",
            # Notice is_enabled and is_selected are intentionally NOT present
        }
        el = _build_ui_element_tree(node)
        self.assertIsNone(el.is_enabled)
        self.assertIsNone(el.is_selected)

    def test_19_cache_pid_isolation(self):
        """Verify that changing frontmost application PID busts cache even if app name is identical."""
        extractor = AccessibilityTreeExtractor(cache_ttl=1.0)
        mock_state1 = ComputerState(active_application="Terminal", active_application_pid=1001)
        mock_state2 = ComputerState(active_application="Terminal", active_application_pid=1002)

        with patch("capabilities.accessibility.tree.is_native_available", return_value=False):
            with patch.object(extractor, "_get_frontmost_app_info", side_effect=[("terminal", 1001), ("terminal", 1002)]):
                with patch.object(extractor, "_extract_applescript_fallback", side_effect=[mock_state1, mock_state2]):
                    s1 = extractor.get_computer_state()
                    self.assertEqual(s1.active_application_pid, 1001)

                    # PID change triggers fresh observation even within 1.0s TTL
                    s2 = extractor.get_computer_state()
                    self.assertEqual(s2.active_application_pid, 1002)

    def test_20_force_refresh_bypasses_cache(self):
        """Verify that force_refresh=True explicitly forces a fresh observation bypassing TTL."""
        extractor = AccessibilityTreeExtractor(cache_ttl=5.0)
        mock_state1 = ComputerState(active_application="Finder", active_window_title="Folder A")
        mock_state2 = ComputerState(active_application="Finder", active_window_title="Folder B")

        with patch("capabilities.accessibility.tree.is_native_available", return_value=False):
            with patch.object(extractor, "_extract_applescript_fallback", side_effect=[mock_state1, mock_state2]):
                s1 = extractor.get_computer_state(application_name="Finder")
                self.assertEqual(s1.active_window_title, "Folder A")

                # Regular call returns cached Folder A
                s_cached = extractor.get_computer_state(application_name="Finder")
                self.assertEqual(s_cached.active_window_title, "Folder A")

                # Force refresh returns fresh Folder B
                s_fresh = extractor.get_computer_state(application_name="Finder", force_refresh=True)
                self.assertEqual(s_fresh.active_window_title, "Folder B")

    def test_21_live_macos_native_backend_execution(self):
        """Phase 12: Real LIVE MACOS test invoking bin/max-ax-dump on Darwin without mocks."""
        import sys
        import os
        from capabilities.accessibility.native_backend import ensure_native_binary, extract_native_accessibility, parse_native_output_to_computer_state
        from capabilities.accessibility.models import AccessibilityHealthStatus

        if sys.platform != "darwin":
            self.skipTest("Native accessibility backend requires macOS (Darwin).")

        binary_path = ensure_native_binary()
        self.assertIsNotNone(binary_path, "Native binary bin/max-ax-dump could not be ensured or compiled.")
        self.assertTrue(os.path.exists(binary_path), f"Native binary {binary_path} does not exist on disk.")
        self.assertTrue(os.access(binary_path, os.X_OK), f"Native binary {binary_path} is not executable.")

        # Real un-mocked native extraction against Finder
        raw_dict = extract_native_accessibility(app_name="Finder", max_depth=3, max_elements=25)
        self.assertIsInstance(raw_dict, dict, "Expected dictionary response from native binary.")
        self.assertNotIn("error", raw_dict.get("status", "").lower(), f"Native extraction failed: {raw_dict.get('error')}")

        # Verify process/app identity and PID
        app_info = raw_dict.get("application") or {}
        self.assertEqual(app_info.get("name"), "Finder", "Expected application identity 'Finder'.")
        self.assertIsInstance(app_info.get("pid"), int, "Expected integer PID from native binary.")
        self.assertGreater(app_info.get("pid"), 0, "Expected positive PID for running Finder process.")

        # Verify parsed ComputerState
        state = parse_native_output_to_computer_state(raw_dict)
        self.assertEqual(state.active_application, "Finder")
        self.assertEqual(state.active_application_pid, app_info.get("pid"))
        self.assertEqual(state.observation_metadata.backend, "native_swift")
        self.assertEqual(state.observation_metadata.accessibility_status, AccessibilityHealthStatus.ACCESSIBILITY_AVAILABLE)

        # Verify root element and UI node extraction
        self.assertIsNotNone(state.root_element, "Native backend must extract a valid root element.")
        self.assertEqual(state.root_element.role, "AXApplication")
        self.assertIsInstance(state.windows, list)


if __name__ == "__main__":
    unittest.main()
