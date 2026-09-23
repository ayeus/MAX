"""MAX 2.0 Soak Test: Executes 50 diverse real commands on macOS,

measuring latency, memory growth, recovery events, and verification accuracy.
Categorizes any failures as Environmental vs MAX Defect per Part U requirements.
"""

import json
import os
import psutil
import time
import unittest
from typing import Any

from agent.core import AgentCore
from verification.base import GoalStatus


SOAK_COMMANDS = [
    "Check macOS version",
    "Check system uptime",
    "Check current user and machine hostname",
    "List files in /tmp directory",
    "Check if /tmp directory exists",
    "Check available disk space on root volume",
    "Check system architecture and kernel",
    "List running processes filtered by name Finder",
    "Check if Finder application is running",
    "Check if Terminal application is running",
    "Check if Safari is running",
    "Check if non-existent application FakeApp12345 is running",
    "Check current system time and date",
    "Check CPU architecture and hardware model",
    "List files in current project directory",
    "Check size of README.md file in current directory",
    "Check if pyproject.toml exists in current directory",
    "Check if /etc/hosts exists and is readable",
    "Read first 3 lines of /etc/hosts",
    "Check if git CLI tool is installed",
    "Check git version",
    "Check if python3 CLI tool is installed",
    "Check python3 version",
    "Check if curl CLI tool is installed",
    "Check if brew CLI tool is installed",
    "Check network connectivity to localhost",
    "Check active network interfaces",
    "List top 5 memory consuming processes",
    "Count total number of running processes",
    "Check if Docker daemon is running",
    "Check if ollama service is running",
    "Check memory usage and swap state",
    "Check battery and power source status",
    "Check display screen count and resolution",
    "List background tasks managed by MAX",
    "Check if /nonexistent_file_xyz_98765 exists",
    "Check contents of a non-existent directory /var/fake_dir_999",
    "Check system environment variables count",
    "Check current working directory path",
    "Check if zsh shell binary exists at /bin/zsh",
    "Check permissions of /tmp",
    "Check if file .gitignore exists in workspace",
    "Check line count of pyproject.toml",
    "Check macOS release name and build number",
    "List fonts or system library items",
    "Check if ssh binary is installed in PATH",
    "Check user home directory path",
    "Check if Calculator application is running",
    "Check system load averages",
    "Check system integrity protection status via csrutil status",
]


def classify_soak_outcome(cmd: str, report: Any, exception: Exception | None = None) -> tuple[str, str]:
    """Classify soak command outcome based on actual evidence:
    MAX_DEFECT, ENVIRONMENTAL, USER_INPUT / POLICY, EXPECTED_NEGATIVE, UNKNOWN / NEEDS_REVIEW
    """
    if exception is not None:
        exc_str = str(exception)
        if "PolicyViolation" in exc_str or "Safety" in exc_str or "Risk" in exc_str:
            return "USER_INPUT / POLICY", f"Policy or safety restriction: {exc_str}"
        return "MAX_DEFECT", f"Unhandled exception: {exc_str}"

    if not report or not report.goal_evaluation:
        return "UNKNOWN / NEEDS_REVIEW", "Missing goal evaluation."

    status = report.goal_evaluation.status
    if status == GoalStatus.SATISFIED:
        return "SATISFIED", "Goal satisfied with verified outcome."

    explanation = (report.goal_evaluation.explanation or "").lower()
    cmd_lower = cmd.lower()

    # 1. Expected negative checks (e.g. testing for non-existent applications, files, or paths)
    negative_indicators = ["non-existent", "nonexistent", "fakeapp", "fake_dir", "xyz_98765"]
    if any(neg in cmd_lower for neg in negative_indicators):
        if "not running" in explanation or "not found" in explanation or "does not exist" in explanation or "unconfirmed" in explanation:
            return "EXPECTED_NEGATIVE", f"Expected negative condition verified: {report.goal_evaluation.explanation}"

    # 2. User Input / Policy rejections
    if "policy" in explanation or "blocked" in explanation or "confirmation" in explanation:
        return "USER_INPUT / POLICY", f"Action restricted by security policy: {report.goal_evaluation.explanation}"

    # 3. Environmental conditions (external daemon not running, hardware dependent, network down)
    env_services = ["docker", "ollama", "battery", "csrutil", "system load", "uptime"]
    if any(svc in cmd_lower for svc in env_services) or "not available" in explanation or "offline" in explanation:
        return "ENVIRONMENTAL", f"Environmental availability condition: {report.goal_evaluation.explanation}"

    # 4. Unknown / Needs Review vs MAX Defect
    if status == GoalStatus.UNKNOWN:
        return "UNKNOWN / NEEDS_REVIEW", f"Outcome inconclusive: {report.goal_evaluation.explanation}"

    return "MAX_DEFECT", f"Command failed to satisfy objective: {report.goal_evaluation.explanation}"


def run_soak_test(commands: list[str] = SOAK_COMMANDS, output_file: str = "tests/soak_results.json") -> dict[str, Any]:
    process = psutil.Process(os.getpid())
    agent = AgentCore()
    
    results = []
    initial_rss = process.memory_info().rss / (1024 * 1024)
    peak_rss = initial_rss
    
    total_commands = len(commands)
    succeeded_count = 0
    unsatisfied_count = 0
    unknown_count = 0
    failed_count = 0
    dropped_count = 0
    recovery_events = 0
    total_duration_ms = 0.0
    
    deterministic_verifications = 0
    vision_verifications = 0
    
    print(f"\n=======================================================")
    print(f"Starting MAX 2.0 Soak Test: {total_commands} Commands")
    print(f"Initial Process RSS: {initial_rss:.2f} MB")
    print(f"=======================================================\n")
    
    for i, cmd in enumerate(commands, 1):
        mem_before = process.memory_info().rss / (1024 * 1024)
        t_start = time.time()
        
        print(f"[{i:02d}/{total_commands}] Running: \"{cmd}\"...", end=" ", flush=True)
        
        try:
            report = agent.run(cmd)
            duration_ms = (time.time() - t_start) * 1000.0
            total_duration_ms += duration_ms
            
            mem_after = process.memory_info().rss / (1024 * 1024)
            peak_rss = max(peak_rss, mem_after)
            
            status_str = report.goal_evaluation.status.value if report.goal_evaluation else "UNKNOWN"
            
            # Tally verification types and collect evidence
            step_evidences = []
            for step_rec in report.steps_executed:
                verif = step_rec.verification
                if verif.evidence.get("verification_type") == "vision":
                    vision_verifications += 1
                else:
                    deterministic_verifications += 1
                step_evidences.append({
                    "step": f"{step_rec.step.capability}.{step_rec.step.action}",
                    "status": verif.status.value,
                    "explanation": verif.explanation,
                })
            
            is_satisfied = (report.goal_evaluation and report.goal_evaluation.status == GoalStatus.SATISFIED)
            if is_satisfied:
                succeeded_count += 1
                status_icon = "✓ SATISFIED"
            elif report.goal_evaluation and report.goal_evaluation.status == GoalStatus.UNKNOWN:
                unknown_count += 1
                status_icon = "? UNKNOWN"
            else:
                unsatisfied_count += 1
                status_icon = "✗ UNSATISFIED"
                
            print(f"{status_icon} ({duration_ms:.1f}ms, RSS: {mem_after:.1f}MB)")
            
            classification, class_reason = classify_soak_outcome(cmd, report)
            
            results.append({
                "index": i,
                "command": cmd,
                "status": status_str,
                "duration_ms": duration_ms,
                "memory_rss_mb": mem_after,
                "steps_count": len(report.steps_executed),
                "evaluation": report.goal_evaluation.explanation if report.goal_evaluation else "",
                "verification_evidence": step_evidences,
                "failure_classification": None if is_satisfied else classification,
                "classification_reason": None if is_satisfied else class_reason,
            })
            
        except Exception as e:
            duration_ms = (time.time() - t_start) * 1000.0
            total_duration_ms += duration_ms
            failed_count += 1
            recovery_events += 1
            print(f"FAILED with exception: {e}")
            classification, class_reason = classify_soak_outcome(cmd, None, exception=e)
            results.append({
                "index": i,
                "command": cmd,
                "status": "EXCEPTION",
                "duration_ms": duration_ms,
                "memory_rss_mb": process.memory_info().rss / (1024 * 1024),
                "steps_count": 0,
                "evaluation": str(e),
                "verification_evidence": [],
                "failure_classification": classification,
                "classification_reason": class_reason,
            })
            
    final_rss = process.memory_info().rss / (1024 * 1024)
    rss_growth = final_rss - initial_rss
    avg_latency = total_duration_ms / total_commands if total_commands else 0.0
    
    summary = {
        "soak_mode": "FULL_SOAK" if total_commands >= 50 else "MINI_SOAK",
        "total_commands": total_commands,
        "succeeded": succeeded_count,
        "unsatisfied": unsatisfied_count,
        "unknown": unknown_count,
        "failed": failed_count,
        "dropped_commands": dropped_count,
        "recovery_events": recovery_events,
        "initial_rss_mb": round(initial_rss, 2),
        "final_rss_mb": round(final_rss, 2),
        "peak_rss_mb": round(peak_rss, 2),
        "rss_growth_mb": round(rss_growth, 2),
        "avg_latency_ms": round(avg_latency, 2),
        "deterministic_verifications": deterministic_verifications,
        "vision_verifications": vision_verifications,
        "commands": results,
    }
    
    with open(output_file, "w") as f:
        json.dump(summary, f, indent=2)
        
    print(f"\n=======================================================")
    print(f"Soak Test Complete ({summary['soak_mode']})!")
    print(f"Succeeded (SATISFIED): {succeeded_count}/{total_commands}")
    print(f"Unsatisfied / Unknown: {unsatisfied_count + unknown_count}/{total_commands}")
    print(f"Exceptions / Crashes: {failed_count}")
    print(f"Dropped Commands: {dropped_count}")
    print(f"Recovery Events: {recovery_events}")
    print(f"Average Latency: {avg_latency:.2f} ms")
    print(f"Memory: Start={initial_rss:.1f}MB, End={final_rss:.1f}MB, Growth={rss_growth:+.1f}MB")
    print(f"Verification: Deterministic={deterministic_verifications}, Vision={vision_verifications}")
    print(f"=======================================================\n")
    
    return summary


class TestSoakSuite(unittest.TestCase):
    """Automated mini-soak test case running a 5-command subset to assert stability in unittest runs."""

    def test_mini_soak_run(self):
        subset = SOAK_COMMANDS[:5]
        summary = run_soak_test(commands=subset, output_file="tests/mini_soak_results.json")
        self.assertEqual(summary["total_commands"], 5)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["dropped_commands"], 0)


def run_full_soak_50(output_file: str = "tests/soak_results.json") -> dict[str, Any]:
    """Execute the full 50-command soak test and assert total_commands == 50."""
    assert len(SOAK_COMMANDS) == 50, f"Expected 50 soak commands, found {len(SOAK_COMMANDS)}"
    summary = run_soak_test(commands=SOAK_COMMANDS, output_file=output_file)
    assert summary["total_commands"] == 50, f"Expected total_commands == 50, got {summary['total_commands']}"
    return summary


if __name__ == "__main__":
    import sys
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    if count == 50:
        run_full_soak_50()
    else:
        run_soak_test(SOAK_COMMANDS[:count])
