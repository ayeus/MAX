"""Unit tests for Workflow management."""

import unittest
import tempfile
from pathlib import Path
from memory.workflows import WorkflowManager


class TestWorkflows(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.mgr = WorkflowManager(workflows_dir=Path(self.tmp_dir.name))

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_save_and_get_workflow(self):
        saved = self.mgr.save_workflow(
            name="test_build_pipeline",
            description="Run build and tests",
            steps=[
                {"capability": "terminal", "action": "execute_command", "args": {"command": "echo 'build'"}},
                {"capability": "terminal", "action": "execute_command", "args": {"command": "echo 'test'"}},
            ],
        )
        self.assertTrue(saved)

        wf = self.mgr.get_workflow("test_build_pipeline")
        self.assertIsNotNone(wf)
        self.assertEqual(wf.name, "test_build_pipeline")
        self.assertEqual(len(wf.steps), 2)
        self.assertEqual(wf.steps[0].args["command"], "echo 'build'")

        # Verify JSON file written to disk
        json_file = Path(self.tmp_dir.name) / "test_build_pipeline.json"
        self.assertTrue(json_file.exists())

    def test_list_workflows(self):
        self.mgr.save_workflow(name="wf1", description="desc1", steps=[])
        self.mgr.save_workflow(name="wf2", description="desc2", steps=[])
        wfs = self.mgr.list_workflows()
        names = [w["name"] for w in wfs]
        self.assertIn("wf1", names)
        self.assertIn("wf2", names)


if __name__ == "__main__":
    unittest.main()
