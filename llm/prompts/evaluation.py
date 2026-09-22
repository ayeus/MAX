"""Prompt constructor for evaluating plan execution outcomes."""

import json


def build_evaluation_prompt(
    user_request: str,
    plan_steps: list[dict],
    execution_results: list[dict],
) -> str:
    """Build prompt to summarize execution results honestly based on actual evidence."""
    return f"""### USER DESIRED OUTCOME:
"{user_request}"

### EXECUTED PLAN AND EVIDENCE:
Steps executed:
{json.dumps(plan_steps, indent=2)}

Real execution evidence and outputs:
{json.dumps(execution_results, indent=2)}

INSTRUCTIONS:
Provide a concise, factual summary of what was actually achieved on the Mac based on the evidence above.
- If an operation succeeded, state what was accomplished and cite the real output or state.
- If an operation failed or encountered an issue (e.g. permission missing, command failed, file not found), state the exact factual failure and why.
- NEVER fabricate success if verification failed.
- Do not narrate your chain-of-thought; provide clear, factual direct reporting.
"""
