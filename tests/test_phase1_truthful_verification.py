"""Phase 1 Verification Invariant Tests for MAX.

Enforces truthful execution and anti-false-success hardening across:
- Invariant A: Mandatory Step Failure Cannot Become SATISFIED via Unrelated Recovery
- Invariant B: Unsupported Mandatory Step Aborts with UNSUPPORTED and Zero Execution
- Invariant C: Unsupported Step in Multi-Step Plan Rejected Before Execution
- Invariant D: Execution Success with Unprovable Postcondition Produces UNKNOWN
- Invariant E: Multi-Step Goal Composition (Truth Table: SATISFIED, UNSATISFIED, UNKNOWN, UNSUPPORTED)
- Invariant F: Optional Step Failure Does Not Invalidate Mandatory Goal
- Invariant G: Target Level vs. Delta Semantics (Brightness)
"""

import unittest
from unittest.mock import MagicMock, patch

from agent.core import AgentCore, StepExecutionRecord
from agent.planner import Planner, Plan, PlanStep, PlannerStatus
from agent.context import AgentContext
from agent.observer import AgentObservation, EnvironmentObservation
from agent.intent import IntentResolver
from voice.normalization import normalizer
from verification.base import GoalStatus, AgentState, VerificationResult, GoalEvaluation
from verification.evaluator import GoalEvaluator, goal_evaluator
from capabilities.base import ExecutionResult
from capabilities.registry import CapabilityRegistry, registry


class TestPhase1TruthfulVerification(unittest.TestCase):
    """Rigorous invariant tests for Phase 1 Truthful Execution."""

    def setUp(self):
        self.context = AgentContext(
            observation=AgentObservation(current_directory="/tmp", active_application="Finder"),
            recent_history=[],
        )
        self.evaluator = GoalEvaluator()

    # =========================================================================
    # Invariant Test A: Mandatory Step Failure Cannot Become SATISFIED via Recovery
    # =========================================================================
    def test_invariant_a1_recovery_cannot_mask_mandatory_failure(self):
        """Invariant A1: If mandatory step 1 fails, and recovery step 2 succeeds,

        the overall goal MUST NOT be SATISFIED. It must report UNSATISFIED.
        """
        step1 = PlanStep(
            step_number=1,
            capability="applications",
            action="launch_application",
            args={"application_name": "NonExistentAppXYZ"},
            is_optional=False,
        )
        rec1 = StepExecutionRecord(
            step=step1,
            result=ExecutionResult(success=False, capability="applications", action="launch_application", error="App not found"),
            verification=VerificationResult(status=GoalStatus.UNSATISFIED, explanation="Application process not found in OS table."),
        )

        # Recovery step executes and succeeds (e.g. listing installed applications)
        step_recov = PlanStep(
            step_number=2,
            capability="applications",
            action="list_installed_applications",
            args={"filter_text": "Non"},
            is_optional=False,
        )
        rec_recov = StepExecutionRecord(
            step=step_recov,
            result=ExecutionResult(success=True, capability="applications", action="list_installed_applications"),
            verification=VerificationResult(status=GoalStatus.SATISFIED, explanation="Retrieved list of applications."),
        )

        obs = AgentObservation(current_directory="/tmp", active_application="Finder")
        goal_eval = self.evaluator.evaluate_goal(
            user_request="Launch NonExistentAppXYZ",
            steps_executed=[rec1, rec_recov],
            remaining_steps=[],
            last_observation=obs,
        )

        self.assertNotEqual(
            goal_eval.status,
            GoalStatus.SATISFIED,
            "False Recovery Loophole detected: Recovery step must NOT satisfy original mandatory goal!",
        )
        self.assertEqual(goal_eval.status, GoalStatus.UNSATISFIED)
        self.assertIn("launch_application", goal_eval.explanation)

    def test_invariant_a2_mandatory_step_retried_and_verified_succeeds(self):
        """Invariant A2: If mandatory step 1 fails, recovery step runs, and step 1 is retried

        and verified SATISFIED, the overall goal successfully resolves to SATISFIED.
        """
        step1 = PlanStep(
            step_number=1,
            capability="applications",
            action="launch_application",
            args={"application_name": "Calculator"},
            is_optional=False,
        )
        rec1_failed = StepExecutionRecord(
            step=step1,
            result=ExecutionResult(success=False, capability="applications", action="launch_application", error="Timeout"),
            verification=VerificationResult(status=GoalStatus.UNSATISFIED, explanation="Application failed to appear in time."),
        )
        step_recov = PlanStep(
            step_number=2,
            capability="applications",
            action="activate_application",
            args={"application_name": "Calculator"},
            is_optional=False,
        )
        rec_recov = StepExecutionRecord(
            step=step_recov,
            result=ExecutionResult(success=True, capability="applications", action="activate_application"),
            verification=VerificationResult(status=GoalStatus.SATISFIED, explanation="Brought to foreground."),
        )
        # Step 1 is retried and succeeds
        rec1_retry_success = StepExecutionRecord(
            step=step1,
            result=ExecutionResult(success=True, capability="applications", action="launch_application"),
            verification=VerificationResult(status=GoalStatus.SATISFIED, explanation="Calculator verified running in process list."),
        )

        obs = AgentObservation(current_directory="/tmp", active_application="Calculator")
        goal_eval = self.evaluator.evaluate_goal(
            user_request="Launch Calculator",
            steps_executed=[rec1_failed, rec_recov, rec1_retry_success],
            remaining_steps=[],
            last_observation=obs,
        )

        self.assertEqual(
            goal_eval.status,
            GoalStatus.SATISFIED,
            "Retried and verified mandatory requirement should satisfy the goal.",
        )

    # =========================================================================
    # Invariant Test B: Atomic Capability Gating on Single-Step Unsupported Request
    # =========================================================================
    def test_invariant_b_unsupported_request_aborts_with_zero_execution(self):
        """Invariant B: Request for unsupported hardware capability aborts with UNSUPPORTED

        and executes exactly zero steps.
        """
        agent = AgentCore()
        report = agent.run("Please set my screen refresh rate to 144Hz")

        self.assertEqual(report.state, AgentState.UNSUPPORTED)
        self.assertEqual(report.goal_evaluation.status, GoalStatus.UNSUPPORTED)
        self.assertFalse(report.overall_success)
        self.assertEqual(len(report.steps_executed), 0, "Zero steps must be executed for unsupported capability!")
        self.assertIn("UNSUPPORTED", report.final_summary)

    # =========================================================================
    # Invariant Test C: Multi-Step Plan with Unsupported Step Rejection
    # =========================================================================
    @patch("agent.planner.model_manager")
    def test_invariant_c_multistep_with_unregistered_step_atomic_rejection(self, mock_mm):
        """Invariant C: If an LLM generates a plan with [Step 1: valid, Step 2: unregistered],

        the planner MUST mark the plan UNSUPPORTED and the executor must execute ZERO steps.
        """
        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.content = (
            '{"thought": "Create folder then sync cluster state", "plan": ['
            '{"capability": "terminal", "action": "execute_command", "args": {"command": "mkdir /tmp/test"}},'
            '{"capability": "cluster_sync_daemon", "action": "sync_nodes", "args": {"nodes": 3}}'
            ']}'
        )
        mock_provider.generate.return_value = mock_response
        planner = Planner(provider=mock_provider)

        plan = planner.create_plan("Create folder and sync cluster nodes", self.context)

        self.assertEqual(plan.status, PlannerStatus.UNSUPPORTED)
        self.assertEqual(len(plan.plan), 0, "Atomic gating must drop the entire plan, not execute partial steps!")
        self.assertIn("cluster_sync_daemon.sync_nodes", plan.unsupported_operations)

        # Confirm AgentCore dispatches zero steps when receiving this
        agent = AgentCore(planner=planner)
        report = agent.run("Create folder and sync cluster nodes")
        self.assertEqual(report.state, AgentState.UNSUPPORTED)
        self.assertEqual(len(report.steps_executed), 0)

    # =========================================================================
    # Invariant Test D: Unverified Success Produces UNKNOWN, Not SATISFIED
    # =========================================================================
    def test_invariant_d_unverified_action_produces_unknown(self):
        """Invariant D: An action that succeeds at execution time but has no postcondition

        proof must report UNKNOWN, never SATISFIED.
        """
        step = PlanStep(
            step_number=1,
            capability="macos",
            action="show_notification",
            args={"message": "System test"},
            is_optional=False,
        )
        res = ExecutionResult(success=True, capability="macos", action="show_notification")
        obs = AgentObservation(current_directory="/tmp", active_application="Finder")

        step_verif = self.evaluator.evaluate_step(step, res, obs)
        self.assertEqual(
            step_verif.status,
            GoalStatus.UNKNOWN,
            "Execution success without verifiable postcondition must produce UNKNOWN.",
        )

        rec = StepExecutionRecord(step=step, result=res, verification=step_verif)
        goal_eval = self.evaluator.evaluate_goal(
            user_request="Show notification",
            steps_executed=[rec],
            remaining_steps=[],
            last_observation=obs,
        )
        self.assertEqual(goal_eval.status, GoalStatus.UNKNOWN)

    # =========================================================================
    # Invariant Test E: Multi-Step Goal Composition
    # =========================================================================
    def test_invariant_e_multi_step_goal_composition(self):
        """Invariant E: Multi-step goal status composition truth table:

        - S + S -> S
        - S + UNSATISFIED -> UNSATISFIED
        - S + UNKNOWN -> UNKNOWN
        - S + UNSUPPORTED -> UNSUPPORTED
        """
        step1 = PlanStep(step_number=1, capability="terminal", action="execute_command", args={"command": "mkdir /tmp/d"}, is_optional=False)
        rec1_sat = StepExecutionRecord(
            step=step1,
            result=ExecutionResult(success=True, capability="terminal", action="execute_command"),
            verification=VerificationResult(status=GoalStatus.SATISFIED, explanation="Directory created."),
        )

        step2 = PlanStep(step_number=2, capability="terminal", action="execute_command", args={"command": "touch /tmp/d/f"}, is_optional=False)
        obs = AgentObservation(current_directory="/tmp", active_application="Finder")

        # 1. SATISFIED + SATISFIED -> SATISFIED
        rec2_sat = StepExecutionRecord(
            step=step2,
            result=ExecutionResult(success=True, capability="terminal", action="execute_command"),
            verification=VerificationResult(status=GoalStatus.SATISFIED, explanation="File created."),
        )
        eval_sat = self.evaluator.evaluate_goal("Create dir and file", [rec1_sat, rec2_sat], [], obs)
        self.assertEqual(eval_sat.status, GoalStatus.SATISFIED)

        # 2. SATISFIED + UNSATISFIED -> UNSATISFIED
        rec2_unsat = StepExecutionRecord(
            step=step2,
            result=ExecutionResult(success=False, capability="terminal", action="execute_command", error="Permission denied"),
            verification=VerificationResult(status=GoalStatus.UNSATISFIED, explanation="File was not created."),
        )
        eval_unsat = self.evaluator.evaluate_goal("Create dir and file", [rec1_sat, rec2_unsat], [], obs)
        self.assertEqual(eval_unsat.status, GoalStatus.UNSATISFIED)

        # 3. SATISFIED + UNKNOWN -> UNKNOWN
        rec2_unk = StepExecutionRecord(
            step=step2,
            result=ExecutionResult(success=True, capability="terminal", action="execute_command"),
            verification=VerificationResult(status=GoalStatus.UNKNOWN, explanation="Cannot verify outcome independently."),
        )
        eval_unk = self.evaluator.evaluate_goal("Create dir and file", [rec1_sat, rec2_unk], [], obs)
        self.assertEqual(eval_unk.status, GoalStatus.UNKNOWN)

        # 4. SATISFIED + UNSUPPORTED -> UNSUPPORTED
        rec2_unsupp = StepExecutionRecord(
            step=step2,
            result=ExecutionResult(success=False, capability="terminal", action="execute_command"),
            verification=VerificationResult(status=GoalStatus.UNSUPPORTED, explanation="Operation unsupported."),
        )
        eval_unsupp = self.evaluator.evaluate_goal("Create dir and file", [rec1_sat, rec2_unsupp], [], obs)
        self.assertEqual(eval_unsupp.status, GoalStatus.UNSUPPORTED)

    # =========================================================================
    # Invariant Test F: Optional Step Failure Does Not Invalidate Mandatory Goal
    # =========================================================================
    def test_invariant_f_optional_step_failure_recorded_without_goal_failure(self):
        """Invariant F: If an optional step fails, the mandatory goal remains SATISFIED,

        and the optional failure is recorded in trace and limitations.
        """
        step_mandatory = PlanStep(
            step_number=1,
            capability="terminal",
            action="execute_command",
            args={"command": "mkdir /tmp/important"},
            is_optional=False,
        )
        step_optional = PlanStep(
            step_number=2,
            capability="macos",
            action="show_notification",
            args={"message": "Created directory"},
            is_optional=True,
        )

        mock_planner = MagicMock()
        mock_planner.create_plan.return_value = Plan(
            thought="Create folder and optionally notify",
            plan=[step_mandatory, step_optional],
            status=PlannerStatus.VALID,
        )

        mock_executor = MagicMock()
        def mock_execute(step):
            if step.step_number == 1:
                return ExecutionResult(success=True, capability="terminal", action="execute_command", verification={"exit_code_zero": True})
            return ExecutionResult(success=False, capability="macos", action="show_notification", error="Notification Center busy")
        mock_executor.execute_step.side_effect = mock_execute

        agent = AgentCore(planner=mock_planner, executor=mock_executor)
        report = agent.run("Create important directory and notify me")

        self.assertEqual(
            report.goal_evaluation.status,
            GoalStatus.SATISFIED,
            "Mandatory goal must remain SATISFIED even if optional step failed.",
        )
        self.assertTrue(report.overall_success)

        # Ensure optional failure is recorded in limitations
        optional_limitation_found = any(
            "Optional step 2" in lim or "show_notification" in lim
            for lim in report.limitations
        )
        self.assertTrue(
            optional_limitation_found,
            f"Optional failure must be recorded in limitations: {report.limitations}",
        )

    # =========================================================================
    # Invariant Test G: Target Level vs. Delta Brightness
    # =========================================================================
    def test_invariant_g_brightness_target_level_vs_delta(self):
        """Invariant G: 'increase my brightness to 90%' specifies target=0.90 (not delta=+0.1).

        Verification must confirm reaching ~0.90, failing if it only increased to 0.60.
        """
        # 1. Linguistic Normalization & Intent Resolution
        interp = normalizer.normalize("increase my brightness to 90%")
        self.assertEqual(interp.intent, "set_brightness")
        self.assertAlmostEqual(interp.parameters.get("level", 0.0), 0.90, places=2)

        resolver = IntentResolver()
        plan = resolver.resolve("increase my brightness to 90%")
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.plan), 1)
        self.assertEqual(plan.plan[0].action, "set_brightness")
        self.assertAlmostEqual(plan.plan[0].args.get("level", 0.0), 0.90, places=2)

        # 2. Delta command without target level
        interp_delta = normalizer.normalize("increase brightness")
        self.assertEqual(interp_delta.intent, "increase_brightness")
        self.assertAlmostEqual(interp_delta.parameters.get("delta", 0.0), 0.1, places=2)

        # 3. Postcondition Verification Semantics
        target_step = plan.plan[0]
        obs = AgentObservation(current_directory="/tmp", active_application="Finder")

        # Scenario: Pre was 0.50, Delta ran and reached 0.60 (Target was 0.90)
        with patch("macos.brightness.is_brightness_supported", return_value=True), \
             patch("macos.brightness.get_display_brightness", return_value=(True, 0.60, None)):
            res_delta_only = ExecutionResult(
                success=True,
                capability="macos",
                action="set_brightness",
                evidence={"before": 0.50, "after": 0.60, "target": 0.90},
            )
            v_fail = self.evaluator.evaluate_step(target_step, res_delta_only, obs)
            self.assertEqual(
                v_fail.status,
                GoalStatus.UNSATISFIED,
                "Reaching 0.60 when target was 0.90 MUST be UNSATISFIED, even though brightness increased!",
            )

        # Scenario: Reached target 0.90
        with patch("macos.brightness.is_brightness_supported", return_value=True), \
             patch("macos.brightness.get_display_brightness", return_value=(True, 0.90, None)):
            res_target_reached = ExecutionResult(
                success=True,
                capability="macos",
                action="set_brightness",
                evidence={"before": 0.50, "after": 0.90, "target": 0.90},
            )
            v_pass = self.evaluator.evaluate_step(target_step, res_target_reached, obs)
            self.assertEqual(
                v_pass.status,
                GoalStatus.SATISFIED,
                "Reaching target 0.90 MUST be SATISFIED.",
            )


if __name__ == "__main__":
    unittest.main()
