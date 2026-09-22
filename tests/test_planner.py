"""Unit tests for planner JSON parsing and prompt construction."""

import unittest
from agent.planner import clean_json_response, Plan, PlanStep
from llm.prompts import build_planning_prompt, SYSTEM_PROMPT


class TestPlanner(unittest.TestCase):

    def test_clean_json_response_with_markdown(self):
        raw = """```json
{
  "thought": "I will inspect the directory",
  "plan": [
    {
      "step_number": 1,
      "capability": "filesystem",
      "action": "list_directory",
      "args": {"path": "."},
      "verification_criteria": "Listed items",
      "is_optional": false
    }
  ]
}
```"""
        cleaned = clean_json_response(raw)
        self.assertTrue(cleaned.startswith("{"))
        self.assertTrue(cleaned.endswith("}"))

    def test_clean_json_response_plain(self):
        plain = '{"thought": "test", "plan": []}'
        self.assertEqual(clean_json_response(plain), plain)

    def test_build_planning_prompt_contains_rules(self):
        prompt = build_planning_prompt(
            user_request="Find all images",
            environment_context={"current_directory": "/test"},
            capabilities_schema=[{"capability": "filesystem", "operations": []}],
        )
        self.assertIn("Find all images", prompt)
        self.assertIn("terminal", prompt)
        self.assertIn("filesystem", prompt)
        self.assertIn("/test", prompt)


if __name__ == "__main__":
    unittest.main()
