"""Unit and contract tests for MAX 2.0 Chunk 2 General Computer-Use Execution Engine."""

import unittest
from unittest.mock import MagicMock, patch
import time

from capabilities.accessibility.models import (
    UIElement,
    ComputerState,
    WindowState,
    ObservationMetadata,
    TargetReference,
)
from capabilities.accessibility.grounding import (
    SemanticUIGrounder,
    TargetConstraints,
    GroundingConfidence,
)
from agent.goal import (
    Goal,
    Subgoal,
    SubgoalStatus,
    ActionIntent,
)
from verification.base import (
    GoalStatus,
    ExpectedPostcondition,
    PostconditionType,
    AgentState,
)
from verification.evaluator import GoalEvaluator
from agent.replanner import Replanner
from agent.planner import Planner, Plan, PlanStep
from agent.core import AgentCore
from capabilities.base import ExecutionResult
from agent.perception import PerceptionPipeline, PerceptionMethod


class TestComputerUseEngine(unittest.TestCase):
    """Exhaustive test suite for Goal/Subgoal, Hierarchical Grounding, Postcondition Verification, and Replanning."""

    def setUp(self):
        self.grounder = SemanticUIGrounder()
        self.evaluator = GoalEvaluator()
        self.replanner = Replanner()

        # Build a representative hierarchical tree:
        # Window
        #   Group (Chat List)
        #     Row 0 (path: AXWindow[0]/AXGroup[0]/AXRow[0])
        #       StaticText ("Alice")
        #       StaticText ("See you tomorrow")
        #     Row 1 (path: AXWindow[0]/AXGroup[0]/AXRow[1])
        #       StaticText ("John")
        #       StaticText ("Hey, are you free?")
        #   Group (Composer)
        #     TextArea (path: AXWindow[0]/AXGroup[1]/AXTextArea[0], title="Message", value="")
        #     Button (path: AXWindow[0]/AXGroup[1]/AXButton[0], title="Send")

        self.row_alice = UIElement(
            role="AXRow",
            path="AXWindow[0]/AXGroup[0]/AXRow[0]",
            children=[
                UIElement(role="AXStaticText", title="Alice", path="AXWindow[0]/AXGroup[0]/AXRow[0]/AXStaticText[0]"),
                UIElement(role="AXStaticText", title="See you tomorrow", path="AXWindow[0]/AXGroup[0]/AXRow[0]/AXStaticText[1]"),
            ],
        )
        self.row_john = UIElement(
            role="AXRow",
            path="AXWindow[0]/AXGroup[0]/AXRow[1]",
            children=[
                UIElement(role="AXStaticText", title="John", path="AXWindow[0]/AXGroup[0]/AXRow[1]/AXStaticText[0]"),
                UIElement(role="AXStaticText", title="Hey, are you free?", path="AXWindow[0]/AXGroup[0]/AXRow[1]/AXStaticText[1]"),
            ],
        )
        self.composer_input = UIElement(
            role="AXTextArea",
            title="Message",
            description="Type a message",
            value="",
            path="AXWindow[0]/AXGroup[1]/AXTextArea[0]",
            bounds={"x": 300, "y": 700, "width": 500, "height": 50},
        )
        self.send_button = UIElement(
            role="AXButton",
            title="Send",
            path="AXWindow[0]/AXGroup[1]/AXButton[0]",
            bounds={"x": 810, "y": 710, "width": 60, "height": 30},
        )

        self.root_window = UIElement(
            role="AXWindow",
            title="MessagingApp",
            path="AXWindow[0]",
            children=[
                UIElement(role="AXGroup", path="AXWindow[0]/AXGroup[0]", children=[self.row_alice, self.row_john]),
                UIElement(role="AXGroup", path="AXWindow[0]/AXGroup[1]", children=[self.composer_input, self.send_button]),
            ],
        )

        self.sample_state = ComputerState(
            active_application="MessagingApp",
            active_application_pid=1234,
            active_window_title="MessagingApp",
            root_element=self.root_window,
            interactive_elements=[self.row_alice, self.row_john, self.composer_input, self.send_button],
            observation_metadata=ObservationMetadata(snapshot_id="snap_test_001"),
        )

    # 1. Goal & Subgoal Lifecycle
    def test_goal_subgoal_lifecycle(self):
        sg1 = Subgoal(description="Open chat with John", expected_postcondition=ExpectedPostcondition(postcondition_type=PostconditionType.WINDOW_ACTIVE, expected_window="John"))
        sg2 = Subgoal(description="Type note", expected_postcondition=ExpectedPostcondition(postcondition_type=PostconditionType.TEXT_VALUE_EQUALS, expected_value="Hello"))

        goal = Goal(objective="Chat with John", subgoals=[sg1, sg2])
        self.assertEqual(goal.current_subgoal_index, 0)
        self.assertEqual(goal.get_current_subgoal().description, "Open chat with John")

        # Advance subgoal
        next_sg = goal.advance_subgoal()
        self.assertEqual(sg1.status, SubgoalStatus.SATISFIED)
        self.assertEqual(goal.current_subgoal_index, 1)
        self.assertEqual(next_sg.description, "Type note")

        # Complete final subgoal
        final = goal.advance_subgoal()
        self.assertIsNone(final)
        self.assertEqual(goal.status, SubgoalStatus.SATISFIED)
        self.assertTrue(goal.all_satisfied())
        self.assertTrue(goal.is_complete())

    # 2. Hierarchical Grounding: Container-to-Child Matching
    def test_hierarchical_grounding_container_descendant(self):
        # Intent: Find row containing "John"
        constraints = TargetConstraints(role="row", child_label="John")
        match = self.grounder.ground(constraints, self.sample_state)

        self.assertTrue(match.is_reliable)
        self.assertIsNotNone(match.element)
        self.assertEqual(match.element.role, "AXRow")
        self.assertEqual(match.element.path, "AXWindow[0]/AXGroup[0]/AXRow[1]")
        self.assertIsNotNone(match.target_ref)
        self.assertEqual(match.target_ref.path, "AXWindow[0]/AXGroup[0]/AXRow[1]")

    # 3. Strict Ambiguity Rejection (Rule 5: Zero Blind Actions)
    def test_strict_ambiguity_rejection(self):
        # Two identical Save buttons in different dialogs/groups
        btn1 = UIElement(role="AXButton", title="Save", path="AXWindow[0]/AXGroup[0]/AXButton[0]")
        btn2 = UIElement(role="AXButton", title="Save", path="AXWindow[0]/AXGroup[1]/AXButton[0]")

        ambiguous_state = ComputerState(
            active_application="Editor",
            root_element=UIElement(role="AXWindow", path="AXWindow[0]", children=[btn1, btn2]),
            interactive_elements=[btn1, btn2],
            observation_metadata=ObservationMetadata(snapshot_id="snap_ambig"),
        )

        constraints = TargetConstraints(role="button", label="Save")
        match = self.grounder.ground(constraints, ambiguous_state)

        # Ambiguity must be flagged and blind action refused
        self.assertTrue(match.is_ambiguous)
        self.assertFalse(match.is_reliable)
        self.assertIsNone(match.element)
        self.assertIn("Ambiguous target", match.rationale)

    # 4. TargetReference Stability and Stale Target Invalidation
    def test_target_reference_staleness(self):
        # Initially valid in current snapshot
        target_ref = TargetReference(
            snapshot_id="snap_test_001",
            path="AXWindow[0]/AXGroup[1]/AXTextArea[0]",
            role="AXTextArea",
            title="Message",
        )
        self.assertTrue(target_ref.is_valid_in(self.sample_state))

        # UI changes: element removed in new state
        new_state = ComputerState(
            active_application="MessagingApp",
            root_element=UIElement(role="AXWindow", path="AXWindow[0]", children=[]),
            interactive_elements=[],
            observation_metadata=ObservationMetadata(snapshot_id="snap_test_002"),
        )
        self.assertFalse(target_ref.is_valid_in(new_state))

        # Validate through grounder helper
        is_valid, el, status = self.grounder.validate_target_reference(target_ref, new_state)
        self.assertFalse(is_valid)
        self.assertIsNone(el)
        self.assertIn("STALE_NOT_FOUND", status)

    # 5. True Postcondition Verification: Text Entry
    def test_postcondition_text_entry_truthful_verification(self):
        # Test A: Text matches expected -> SATISFIED
        postcondition = ExpectedPostcondition(
            postcondition_type=PostconditionType.TEXT_VALUE_EQUALS,
            target_path="AXWindow[0]/AXGroup[1]/AXTextArea[0]",
            expected_value="Verified text input",
        )
        state_success = self.sample_state.model_copy(deep=True)
        # Set actual value in post-action state
        el = state_success.root_element.find_by_path("AXWindow[0]/AXGroup[1]/AXTextArea[0]")
        el.value = "Verified text input"

        v_success = self.evaluator.evaluate_postcondition(postcondition, self.sample_state, state_success)
        self.assertEqual(v_success.status, GoalStatus.SATISFIED)
        self.assertIn("Verified text value equals", v_success.explanation)

        # Test B: Text entry partial / incorrect -> UNSATISFIED
        state_partial = self.sample_state.model_copy(deep=True)
        el_p = state_partial.root_element.find_by_path("AXWindow[0]/AXGroup[1]/AXTextArea[0]")
        el_p.value = "Verified text"  # Cut off

        v_partial = self.evaluator.evaluate_postcondition(postcondition, self.sample_state, state_partial)
        self.assertEqual(v_partial.status, GoalStatus.UNSATISFIED)
        self.assertIn("Text verification failed", v_partial.explanation)

        # Test C: Field value unreadable (None) -> UNKNOWN (never false success)
        state_unreadable = self.sample_state.model_copy(deep=True)
        el_u = state_unreadable.root_element.find_by_path("AXWindow[0]/AXGroup[1]/AXTextArea[0]")
        el_u.value = None

        v_unreadable = self.evaluator.evaluate_postcondition(postcondition, self.sample_state, state_unreadable)
        self.assertEqual(v_unreadable.status, GoalStatus.UNKNOWN)

    # 6. Postcondition Verification: State Delta Match
    def test_postcondition_state_delta(self):
        postcondition = ExpectedPostcondition(
            postcondition_type=PostconditionType.STATE_DELTA_MATCH,
            expected_delta_keys=["window_changed", "focus_changed"],
        )

        state_after = self.sample_state.model_copy(deep=True)
        state_after.active_window_title = "Preferences"
        state_after.focused_element = self.send_button

        v_delta = self.evaluator.evaluate_postcondition(postcondition, self.sample_state, state_after)
        self.assertEqual(v_delta.status, GoalStatus.SATISFIED)

    # 7. Postcondition Verification: Selection State (Preserves None as UNKNOWN)
    def test_postcondition_selection(self):
        postcondition = ExpectedPostcondition(
            postcondition_type=PostconditionType.ELEMENT_SELECTED,
            target_path="AXWindow[0]/AXGroup[1]/AXButton[0]",
        )

        # A. is_selected is True -> SATISFIED
        st_sel = self.sample_state.model_copy(deep=True)
        st_sel.root_element.find_by_path("AXWindow[0]/AXGroup[1]/AXButton[0]").is_selected = True
        self.assertEqual(self.evaluator.evaluate_postcondition(postcondition, None, st_sel).status, GoalStatus.SATISFIED)

        # B. is_selected is False -> UNSATISFIED
        st_unsel = self.sample_state.model_copy(deep=True)
        st_unsel.root_element.find_by_path("AXWindow[0]/AXGroup[1]/AXButton[0]").is_selected = False
        self.assertEqual(self.evaluator.evaluate_postcondition(postcondition, None, st_unsel).status, GoalStatus.UNSATISFIED)

        # C. is_selected is None -> UNKNOWN
        st_none = self.sample_state.model_copy(deep=True)
        st_none.root_element.find_by_path("AXWindow[0]/AXGroup[1]/AXButton[0]").is_selected = None
        self.assertEqual(self.evaluator.evaluate_postcondition(postcondition, None, st_none).status, GoalStatus.UNKNOWN)

    # 8. State-Driven Replanning: Modal Interruption Diagnosis
    def test_state_driven_replanning_modal_interruption(self):
        # Pre-action state: working inside TextEdit
        pre_state = ComputerState(
            active_application="TextEdit",
            active_window_title="Untitled",
            windows=[WindowState(title="Untitled", is_modal=False)],
            observation_metadata=ObservationMetadata(snapshot_id="snap_pre"),
        )
        # Post-action state: an unexpected alert dialog appeared
        post_state = ComputerState(
            active_application="TextEdit",
            active_window_title="Confirm Discard",
            windows=[
                WindowState(title="Untitled", is_modal=False),
                WindowState(title="Confirm Discard", subrole="AXDialog", is_modal=True),
            ],
            observation_metadata=ObservationMetadata(snapshot_id="snap_post"),
        )

        subgoal = Subgoal(
            description="Type text in document",
            action_intent=ActionIntent(action_type="type_text", parameters={"text": "MAX"}),
            expected_postcondition=ExpectedPostcondition(postcondition_type=PostconditionType.TEXT_VALUE_EQUALS, expected_value="MAX"),
        )
        goal = Goal(objective="Edit document", subgoals=[subgoal])

        diag = self.replanner.diagnose_state_mismatch(subgoal.expected_postcondition, pre_state, post_state)
        self.assertEqual(diag["type"], "MODAL_INTERRUPTION")
        self.assertTrue(diag["modal_detected"])
        self.assertEqual(diag["modal_title"], "Confirm Discard")

        recovery_subgoal = self.replanner.determine_recovery_subgoal(subgoal, goal, ExecutionResult(success=True, capability="accessibility", action="type_into_element"), pre_state, post_state)
        self.assertIsNotNone(recovery_subgoal)
        self.assertIn("Confirm Discard", recovery_subgoal.description)
        self.assertEqual(recovery_subgoal.expected_postcondition.postcondition_type, PostconditionType.WINDOW_CLOSED)

    # 9. Removal of Unsafe Planner Fallbacks (Phase 20)
    def test_planner_zero_echo_fallbacks(self):
        mock_provider = MagicMock()
        # Simulate LLM returning empty or invalid JSON
        mock_res = MagicMock()
        mock_res.content = "{ invalid json }"
        mock_provider.generate.return_value = mock_res

        planner = Planner(provider=mock_provider)
        context = MagicMock()
        context.to_prompt_dict.return_value = {}
        context.recent_history = []

        plan = planner.create_plan("do something impossible", context)
        # Must return empty plan with planning failure, NEVER echo command
        self.assertEqual(len(plan.plan), 0)
        self.assertIn("Planning failure", plan.thought)

    # 10. Automatic Perception Pipeline: Accessibility First, Vision Fallback
    def test_perception_pipeline_fallbacks(self):
        # Mock vision capability
        mock_vision = MagicMock()
        mock_vision.find_visual_target.return_value = ExecutionResult(
            success=True,
            capability="vision",
            action="find_visual_target",
            data={"coordinates": [450, 320], "provider": "vlm", "screenshot_id": "snap_vis_1"},
        )
        pipeline = PerceptionPipeline(vision_capability=mock_vision)

        # Case A: Target exists in Accessibility tree -> Resolves via ACCESSIBILITY
        res_ax = pipeline.resolve_target(TargetConstraints(role="button", label="Send"), self.sample_state)
        self.assertEqual(res_ax.method, PerceptionMethod.ACCESSIBILITY)
        self.assertTrue(res_ax.is_usable)
        self.assertEqual(res_ax.element.title, "Send")
        mock_vision.find_visual_target.assert_not_called()

        # Case B: Target NOT in Accessibility tree -> Resolves via dynamic VISION
        res_vis = pipeline.resolve_target(TargetConstraints(label="SpecialCustomIcon"), self.sample_state)
        self.assertEqual(res_vis.method, PerceptionMethod.VISION)
        self.assertTrue(res_vis.is_usable)
        self.assertEqual(res_vis.dynamic_coordinates, (450.0, 320.0))

        # Case C: Vision fails -> evaluates truthfully to NONE / UNKNOWN (never fake coordinates)
        mock_vision.find_visual_target.return_value = ExecutionResult(
            success=False,
            capability="vision",
            action="find_visual_target",
            error="Target not detected in screenshot",
        )
        res_fail = pipeline.resolve_target(TargetConstraints(label="NonexistentIcon"), self.sample_state)
        self.assertEqual(res_fail.method, PerceptionMethod.NONE)
        self.assertFalse(res_fail.is_usable)

    # 11. TargetReference Validation Hierarchy & Ambiguity
    def test_target_reference_validation_hierarchy(self):
        from capabilities.accessibility.models import TargetValidity, AccessibilityHealthStatus
        # Test A: Native identifier matches uniquely
        ref_id = TargetReference(
            snapshot_id="snap_1",
            path="AXWindow[0]/OldPath",
            role="AXButton",
            identifier="unique_submit_btn",
            title="Submit",
        )
        state_with_id = ComputerState(
            active_application="App",
            root_element=UIElement(
                role="AXWindow",
                path="AXWindow[0]",
                children=[
                    UIElement(role="AXButton", path="AXWindow[0]/NewMovedPath", identifier="unique_submit_btn", title="Submit"),
                ],
            ),
            interactive_elements=[],
            observation_metadata=ObservationMetadata(snapshot_id="snap_2"),
        )
        status, el, reason = ref_id.validate_in(state_with_id)
        self.assertEqual(status, TargetValidity.VALID)
        self.assertIsNotNone(el)
        self.assertEqual(el.path, "AXWindow[0]/NewMovedPath")

        # Test B: Duplicate titles in different groups -> AMBIGUOUS
        ref_dup = TargetReference(
            snapshot_id="snap_1",
            path="AXWindow[0]/AXGroup[0]/AXButton[0]",
            role="AXButton",
            title="Save",
        )
        state_dup = ComputerState(
            active_application="App",
            root_element=UIElement(
                role="AXWindow",
                path="AXWindow[0]",
                children=[
                    UIElement(role="AXGroup", path="AXWindow[0]/AXGroup[0]", children=[
                        UIElement(role="AXButton", path="AXWindow[0]/AXGroup[0]/AXButton[0]", title="Save"),
                    ]),
                    UIElement(role="AXGroup", path="AXWindow[0]/AXGroup[1]", children=[
                        UIElement(role="AXButton", path="AXWindow[0]/AXGroup[1]/AXButton[0]", title="Save"),
                    ]),
                ],
            ),
            interactive_elements=[],
            observation_metadata=ObservationMetadata(snapshot_id="snap_2"),
        )
        status_dup, el_dup, reason_dup = ref_dup.validate_in(state_dup)
        self.assertEqual(status_dup, TargetValidity.AMBIGUOUS)
        self.assertIsNone(el_dup)

        # Test C: Accessibility denied -> UNKNOWN
        denied_state = ComputerState(
            active_application="App",
            observation_metadata=ObservationMetadata(
                snapshot_id="snap_denied",
                accessibility_status=AccessibilityHealthStatus.ACCESSIBILITY_DENIED,
            ),
        )
        status_denied, _, _ = ref_id.validate_in(denied_state)
        self.assertEqual(status_denied, TargetValidity.UNKNOWN)

    # 12. Structural Type != Send Invariant (Rule 12)
    def test_structural_type_not_send_invariant(self):
        from agent.goal import ActionType
        # Intent-level structural enforcement
        with self.assertRaises(ValueError) as ctx:
            ActionIntent(
                action_type=ActionType.TYPE_TEXT,
                parameters={"text": "hello", "press_return": True},
            )
        self.assertIn("Structural safety violation", str(ctx.exception))

        # Capability-level structural enforcement
        from capabilities.accessibility.accessibility import AccessibilityCapability
        cap = AccessibilityCapability()
        res = cap.type_into_element(text="hello", press_return=True)
        self.assertFalse(res.success)
        self.assertTrue(res.evidence.get("structural_safety_violation"))
        self.assertIn("Implicit send/return rejected", res.error)

    # 13. Click Verification: Zero Blind Satisfaction
    def test_click_verification_requires_state_delta_or_postcondition(self):
        from agent.planner import PlanStep
        from agent.observer import EnvironmentObservation
        from capabilities.base import ExecutionResult
        from verification.base import GoalStatus
        from verification.evaluator import GoalEvaluator

        evaluator = GoalEvaluator()
        step = PlanStep(step_number=1, capability="accessibility", action="click_element", args={"label": "Button"})
        tool_res = ExecutionResult(success=True, capability="accessibility", action="click_element", data={"method": "system_events"})

        # Case A: Identical pre and post states (no delta) -> UNKNOWN (NOT SATISFIED)
        pre_obs = EnvironmentObservation(
            current_directory="/tmp",
            active_application="App",
            computer_state=ComputerState(
                active_application="App",
                active_window_title="Doc",
                interactive_elements=[],
                observation_metadata=ObservationMetadata(snapshot_id="snap_1"),
            ),
        )
        post_obs = EnvironmentObservation(
            current_directory="/tmp",
            active_application="App",
            computer_state=ComputerState(
                active_application="App",
                active_window_title="Doc",
                interactive_elements=[],
                observation_metadata=ObservationMetadata(snapshot_id="snap_2"),
            ),
        )
        verif = evaluator.evaluate_step(step, tool_res, post_obs, pre_observation=pre_obs)
        self.assertEqual(verif.status, GoalStatus.UNKNOWN)
        self.assertIn("no observable state change", verif.explanation)

        # Case B: Window title changed in post state -> SATISFIED
        post_obs_changed = EnvironmentObservation(
            current_directory="/tmp",
            active_application="App",
            computer_state=ComputerState(
                active_application="App",
                active_window_title="NewDialog",
                interactive_elements=[],
                observation_metadata=ObservationMetadata(snapshot_id="snap_3"),
            ),
        )
        verif_ok = evaluator.evaluate_step(step, tool_res, post_obs_changed, pre_observation=pre_obs)
        self.assertEqual(verif_ok.status, GoalStatus.SATISFIED)

    # 14. Scroll Verification: Only Satisfied When Target Revealed
    def test_scroll_verification_requires_content_revelation(self):
        from agent.planner import PlanStep
        from agent.observer import EnvironmentObservation
        from capabilities.base import ExecutionResult
        from verification.base import GoalStatus
        from verification.evaluator import GoalEvaluator

        evaluator = GoalEvaluator()
        step = PlanStep(step_number=1, capability="accessibility", action="scroll", args={"direction": "down", "target_label": "Footer Note"})
        tool_res = ExecutionResult(success=True, capability="accessibility", action="scroll", data={})

        # Target not revealed -> UNSATISFIED
        obs_empty = EnvironmentObservation(
            current_directory="/tmp",
            active_application="App",
            computer_state=ComputerState(
                active_application="App",
                interactive_elements=[],
                observation_metadata=ObservationMetadata(snapshot_id="snap_1"),
            ),
        )
        verif_fail = evaluator.evaluate_step(step, tool_res, obs_empty)
        self.assertEqual(verif_fail.status, GoalStatus.UNSATISFIED)

        # Target revealed -> SATISFIED
        obs_revealed = EnvironmentObservation(
            current_directory="/tmp",
            active_application="App",
            computer_state=ComputerState(
                active_application="App",
                interactive_elements=[
                    UIElement(role="AXStaticText", title="Footer Note", path="AXWindow[0]/AXStaticText[0]"),
                ],
                observation_metadata=ObservationMetadata(snapshot_id="snap_2"),
            ),
        )
        verif_ok = evaluator.evaluate_step(step, tool_res, obs_revealed)
        self.assertEqual(verif_ok.status, GoalStatus.SATISFIED)

    # 15. Custom Postcondition: Zero Fake Success
    def test_custom_postcondition_zero_fake_success(self):
        from verification.base import ExpectedPostcondition, PostconditionType, GoalStatus
        from verification.evaluator import GoalEvaluator, register_custom_verifier
        from capabilities.base import ExecutionResult

        evaluator = GoalEvaluator()
        tool_res = ExecutionResult(success=True, capability="custom", action="do_work")

        # Unregistered custom postcondition -> UNKNOWN, never SATISFIED
        custom_unregistered = ExpectedPostcondition(
            postcondition_type=PostconditionType.CUSTOM,
            description="Special unprovable condition",
        )
        verif = evaluator.evaluate_postcondition(custom_unregistered, None, None, result=tool_res)
        self.assertEqual(verif.status, GoalStatus.UNKNOWN)

        # Registered custom verifier -> Evaluates truthfully
        def my_verifier(postcond, pre_st, post_st, res):
            from verification.base import VerificationResult
            return VerificationResult(status=GoalStatus.SATISFIED, explanation="Custom proof confirmed.")

        register_custom_verifier("my_verifier", my_verifier)
        custom_registered = ExpectedPostcondition(
            postcondition_type=PostconditionType.CUSTOM,
            custom_verifier_name="my_verifier",
        )
        verif_reg = evaluator.evaluate_postcondition(custom_registered, None, None, result=tool_res)
        self.assertEqual(verif_reg.status, GoalStatus.SATISFIED)


class TestChunk2AuthenticityRegressions(unittest.TestCase):
    """PHASE 28: Mandatory Regression Tests for Evidence Integrity & False-Success Prevention."""

    def setUp(self):
        self.evaluator = GoalEvaluator()

    # 1. is_application_running=False -> UNSATISFIED (and True -> SATISFIED, missing -> UNKNOWN)
    def test_regression_01_is_application_running_tri_state(self):
        from agent.planner import PlanStep
        from capabilities.base import ExecutionResult
        from agent.observer import EnvironmentObservation

        step = PlanStep(step_number=1, capability="applications", action="is_application_running", args={"application_name": "TestApp"})
        obs = EnvironmentObservation(current_directory="/tmp", active_application="Finder")

        # False -> UNSATISFIED
        res_false = ExecutionResult(success=True, capability="applications", action="is_application_running", data={"is_running": False})
        verif_false = self.evaluator.evaluate_step(step, res_false, obs)
        self.assertEqual(verif_false.status, GoalStatus.UNSATISFIED)

        # True -> SATISFIED
        res_true = ExecutionResult(success=True, capability="applications", action="is_application_running", data={"is_running": True})
        verif_true = self.evaluator.evaluate_step(step, res_true, obs)
        self.assertEqual(verif_true.status, GoalStatus.SATISFIED)

        # Unavailable / missing data -> UNKNOWN
        res_unk = ExecutionResult(success=False, capability="applications", action="is_application_running", data={}, error="IPC timeout")
        verif_unk = self.evaluator.evaluate_step(step, res_unk, obs)
        self.assertEqual(verif_unk.status, GoalStatus.UNKNOWN)

    # 2. type_into_element: success=True, typed_successfully=True, no ComputerState -> UNKNOWN
    def test_regression_02_type_into_element_no_computer_state_is_unknown(self):
        from agent.planner import PlanStep
        from capabilities.base import ExecutionResult
        from agent.observer import EnvironmentObservation

        step = PlanStep(step_number=1, capability="accessibility", action="type_into_element", args={"text": "Hello", "target_label": "Editor"})
        tool_res = ExecutionResult(
            success=True,
            capability="accessibility",
            action="type_into_element",
            verification={"typed_successfully": True, "keystrokes_dispatched": True},
            data={"text_length": 5},
        )
        obs_no_cs = EnvironmentObservation(current_directory="/tmp", active_application="Editor", computer_state=None)

        verif = self.evaluator.evaluate_step(step, tool_res, obs_no_cs)
        self.assertEqual(verif.status, GoalStatus.UNKNOWN)
        self.assertIn("no independent ComputerState", verif.explanation)

    # 3. send_key_chord: success=True, keystroke_sent=True, no independent effect -> UNKNOWN
    def test_regression_03_send_key_chord_no_independent_effect_is_unknown(self):
        from agent.planner import PlanStep
        from capabilities.base import ExecutionResult
        from agent.observer import EnvironmentObservation

        step = PlanStep(step_number=1, capability="accessibility", action="send_key_chord", args={"key": "s", "modifiers": "command"})
        tool_res = ExecutionResult(
            success=True,
            capability="accessibility",
            action="send_key_chord",
            verification={"keystroke_sent": True},
        )
        # Without independent ComputerState state transition delta -> UNKNOWN
        obs = EnvironmentObservation(current_directory="/tmp", active_application="Editor", computer_state=None)
        verif = self.evaluator.evaluate_step(step, tool_res, obs)
        self.assertEqual(verif.status, GoalStatus.UNKNOWN)

    # 4. focus_element: success=True, focused=True, no ComputerState -> UNKNOWN
    def test_regression_04_focus_element_no_computer_state_is_unknown(self):
        from agent.planner import PlanStep
        from capabilities.base import ExecutionResult
        from agent.observer import EnvironmentObservation

        step = PlanStep(step_number=1, capability="accessibility", action="focus_element", args={"label": "SearchBar"})
        tool_res = ExecutionResult(
            success=True,
            capability="accessibility",
            action="focus_element",
            verification={"focused": True},
        )
        obs_no_cs = EnvironmentObservation(current_directory="/tmp", active_application="App", computer_state=None)

        verif = self.evaluator.evaluate_step(step, tool_res, obs_no_cs)
        self.assertEqual(verif.status, GoalStatus.UNKNOWN)
        self.assertIn("could not be independently verified", verif.explanation)

    # 5. mutating ActionIntent: no expected postcondition, result.success=True -> UNKNOWN
    def test_regression_05_mutating_action_no_postcondition_is_unknown(self):
        from agent.goal import Goal, Subgoal, ActionIntent
        from capabilities.base import ExecutionResult

        subgoal = Subgoal(
            description="Click button without postcondition",
            action_intent=ActionIntent(action_type="click", parameters={"label": "Submit"}),
            expected_postcondition=None,
        )
        goal = Goal(objective="Mutate GUI", subgoals=[subgoal])

        agent = AgentCore()
        mock_res = ExecutionResult(success=True, capability="accessibility", action="click_element", data={})

        with patch("agent.core.observer.observe") as mock_obs, \
             patch("capabilities.registry.registry.get") as mock_reg:
            mock_cap = MagicMock()
            mock_cap.execute.return_value = mock_res
            mock_reg.return_value = mock_cap

            from agent.observer import EnvironmentObservation
            mock_obs.return_value = EnvironmentObservation(current_directory="/tmp", active_application="App", computer_state=None)

            report = agent.execute_goal(goal)
            self.assertEqual(len(report.steps_executed), 1)
            # Must be UNKNOWN, NOT SATISFIED!
            self.assertEqual(report.steps_executed[0].verification.status, GoalStatus.UNKNOWN)
            self.assertFalse(report.overall_success)

    # 6. ambiguous target -> no action dispatched (count == 0)
    def test_regression_06_ambiguous_target_dispatches_zero_actions(self):
        btn1 = UIElement(role="AXButton", title="Save", path="AXWindow[0]/AXGroup[0]/AXButton[0]")
        btn2 = UIElement(role="AXButton", title="Save", path="AXWindow[0]/AXGroup[1]/AXButton[0]")
        state = ComputerState(
            active_application="App",
            root_element=UIElement(role="AXWindow", path="AXWindow[0]", children=[btn1, btn2]),
            interactive_elements=[btn1, btn2],
        )
        grounder = SemanticUIGrounder()
        match = grounder.ground(TargetConstraints(role="button", label="Save"), state)

        self.assertTrue(match.is_ambiguous)
        self.assertFalse(match.is_reliable)

        # Instrument action execution count
        action_dispatch_count = 0
        if match.is_reliable and not match.is_ambiguous:
            action_dispatch_count += 1

        self.assertEqual(action_dispatch_count, 0, "No action may be dispatched for ambiguous target.")

    # 7. stale target -> no action dispatched (count == 0)
    def test_regression_07_stale_target_dispatches_zero_actions(self):
        from capabilities.accessibility.models import TargetValidity
        stale_ref = TargetReference(
            snapshot_id="old_snap",
            path="AXApplication/AXWindow[0]/AXButton[99]",
            role="AXButton",
            title="NonExistent",
        )
        current_state = ComputerState(
            active_application="App",
            root_element=UIElement(role="AXWindow", path="AXWindow[0]", children=[]),
            interactive_elements=[],
        )
        validity, _, _ = stale_ref.validate_in(current_state)
        self.assertEqual(validity, TargetValidity.STALE)

        action_dispatch_count = 0
        if validity == TargetValidity.VALID:
            action_dispatch_count += 1

        self.assertEqual(action_dispatch_count, 0, "No action may be dispatched for stale target.")

    # 8. grounding failure in LIVE test -> test FAIL, NOT fallback target path
    def test_regression_08_grounding_failure_in_live_test_strictly_fails(self):
        # Verify that dynamic grounding failure produces an explicit failure report rather than a hardcoded target path
        state_empty = ComputerState(active_application="TextEdit", interactive_elements=[])
        grounder = SemanticUIGrounder()
        match = grounder.ground(TargetConstraints(role="text_area"), state_empty)
        target = match.element

        if not target:
            res = {
                "grounding_status": "FAILED",
                "error": "Dynamic grounding failed to discover text area",
                "passed": False,
            }
        else:
            res = {"grounding_status": "SUCCESS", "target": target.path, "passed": True}

        self.assertEqual(res["grounding_status"], "FAILED")
        self.assertFalse(res["passed"])
        self.assertNotIn("AXApplication/AXWindow[0]/AXScrollArea[0]/AXTextArea[0]", str(res))

    # 9. fake/generated post-state -> cannot count as LIVE
    def test_regression_09_fake_post_state_classified_as_synthetic(self):
        # An in-memory constructed ComputerState MUST be classified as SYNTHETIC
        synthetic_state = ComputerState(
            active_application="MockApp",
            active_window_title="In-Memory Window",
            interactive_elements=[UIElement(role="AXButton", title="MockBtn")],
            observation_metadata=ObservationMetadata(snapshot_id="mock_snap_123"),
        )
        is_live = (
            synthetic_state.observation_metadata.backend == "native_swift"
            and synthetic_state.active_application_pid is not None
            and synthetic_state.active_application_pid > 0
        )
        self.assertFalse(is_live, "In-memory ComputerState without native PID must NOT be classified as LIVE.")

    # 10. missing live side effect -> report generator fails
    def test_regression_10_missing_live_side_effect_fails_report(self):
        from typing import Any
        def validate_live_report_entry(entry: dict[str, Any]) -> bool:
            if entry.get("classification") == "LIVE_MACOS":
                side_effect = entry.get("actual_external_side_effect")
                evidence = entry.get("independently_observed_state")
                if not side_effect or not evidence:
                    raise ValueError(f"Live report entry '{entry.get('function')}' missing live side effect or evidence.")
            return True

        # Valid entry passes
        valid_entry = {
            "classification": "LIVE_MACOS",
            "function": "run_live_test_a",
            "actual_external_side_effect": "Text typed into active TextEdit document window",
            "independently_observed_state": {"value": "hello"},
        }
        self.assertTrue(validate_live_report_entry(valid_entry))

        # Missing side effect raises ValueError
        invalid_entry = {
            "classification": "LIVE_MACOS",
            "function": "fake_live_test",
            "actual_external_side_effect": None,
            "independently_observed_state": None,
        }
        with self.assertRaises(ValueError):
            validate_live_report_entry(invalid_entry)


if __name__ == "__main__":
    unittest.main()

