"""Unit tests for planner JSON parsing and prompt construction."""

import unittest
from unittest.mock import MagicMock

from agent.context import AgentContext
from agent.observer import AgentObservation
from agent.planner import clean_json_response, Planner
from capabilities.filesystem import FilesystemCapability
from capabilities.registry import registry
from llm.base import LLMResponse
from llm.prompts import build_planning_prompt, SYSTEM_PROMPT
from verification.base import PostconditionType


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

    def test_create_plan_preserves_expected_postcondition(self):
        if "filesystem" not in registry.list_capabilities():
            registry.register(FilesystemCapability())

        mock_provider = MagicMock()
        mock_provider.generate.return_value = LLMResponse(
            model="test",
            content="""{
              "thought": "Write the requested file and verify it exists.",
              "plan": [
                {
                  "step_number": 1,
                  "capability": "filesystem",
                  "action": "write_file",
                  "args": {"path": "/tmp/max-planner-postcondition.txt", "content": "READY"},
                  "verification_criteria": "File exists at the requested path",
                  "expected_postcondition": {
                    "postcondition_type": "FILE_EXISTS",
                    "target_path": "/tmp/max-planner-postcondition.txt",
                    "description": "Requested file exists after writing"
                  },
                  "is_optional": false
                }
              ]
            }""",
        )
        context = AgentContext(
            observation=AgentObservation(current_directory="/tmp", active_application="Finder"),
            recent_history=[],
        )

        plan = Planner(provider=mock_provider).create_plan(
            "Persist the model status marker for later verification",
            context,
        )

        self.assertEqual(len(plan.plan), 1)
        postcondition = plan.plan[0].expected_postcondition
        self.assertIsNotNone(postcondition)
        self.assertEqual(postcondition.postcondition_type, PostconditionType.FILE_EXISTS)
        self.assertEqual(postcondition.target_path, "/tmp/max-planner-postcondition.txt")


if __name__ == "__main__":
    unittest.main()
