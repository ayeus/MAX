"""Unit tests for semantic UI grounding and computer-use disambiguation."""

import unittest
from capabilities.accessibility.models import UIElement, ComputerState
from capabilities.accessibility.grounding import (
    SemanticUIGrounder,
    TargetConstraints,
    GroundingConfidence,
)


class TestComputerUseGrounding(unittest.TestCase):
    def setUp(self):
        self.grounder = SemanticUIGrounder()
        self.sample_state = ComputerState(
            active_application="Notes",
            active_window_title="All iCloud Notes",
            interactive_elements=[
                UIElement(
                    role="AXButton",
                    title="New Note",
                    description="Create a new note",
                    actions=["AXPress"],
                    bounds={"x": 50, "y": 80, "width": 80, "height": 30},
                ),
                UIElement(
                    role="AXSearchField",
                    title="",
                    description="Search all notes",
                    value="",
                    is_focused=False,
                    actions=["AXConfirm"],
                    bounds={"x": 150, "y": 80, "width": 200, "height": 28},
                ),
                UIElement(
                    role="AXTextArea",
                    title="",
                    description="note body text entry",
                    value="Existing body text",
                    is_focused=True,
                    actions=["AXConfirm"],
                    bounds={"x": 300, "y": 150, "width": 500, "height": 400},
                ),
                UIElement(
                    role="AXButton",
                    title="Delete Note",
                    description="Delete selected note",
                    actions=["AXPress"],
                    bounds={"x": 820, "y": 80, "width": 60, "height": 30},
                ),
                UIElement(
                    role="AXCheckBox",
                    title="Pin Note",
                    description="Keep note pinned to top",
                    value="0",
                    actions=["AXPress"],
                ),
            ],
        )

    def test_exact_title_match(self):
        """Exact title match resolves with EXACT or STRONG confidence and is_reliable=True."""
        match = self.grounder.ground(
            TargetConstraints(label="New Note", role="button"),
            self.sample_state,
        )
        self.assertTrue(match.is_reliable)
        self.assertIn(match.confidence, (GroundingConfidence.EXACT, GroundingConfidence.STRONG))
        self.assertIsNotNone(match.element)
        self.assertEqual(match.element.title, "New Note")
        self.assertEqual(match.element.role, "AXButton")

    def test_description_and_placeholder_match(self):
        """Description match finds elements when accessible title is empty."""
        match = self.grounder.ground(
            TargetConstraints(label="Search all notes", role="search"),
            self.sample_state,
        )
        self.assertTrue(match.is_reliable)
        self.assertIsNotNone(match.element)
        self.assertEqual(match.element.role, "AXSearchField")

    def test_role_alias_resolution(self):
        """Standard alias 'text_area' or 'input' resolves to AXTextArea."""
        match = self.grounder.ground(
            TargetConstraints(role="text_area"),
            self.sample_state,
        )
        self.assertTrue(match.is_reliable)
        self.assertIsNotNone(match.element)
        self.assertEqual(match.element.role, "AXTextArea")

    def test_nonexistent_element_returns_none(self):
        """Constraints matching no elements return NONE confidence and is_reliable=False."""
        match = self.grounder.ground(
            TargetConstraints(label="Submit Payment", role="button"),
            self.sample_state,
        )
        self.assertFalse(match.is_reliable)
        self.assertEqual(match.confidence, GroundingConfidence.NONE)
        self.assertIsNone(match.element)
        self.assertIn("No matching UI elements found", match.rationale)

    def test_ambiguity_rejection(self):
        """Multiple conflicting candidates with identical scores trigger ambiguity refusal."""
        ambiguous_state = ComputerState(
            active_application="TestApp",
            active_window_title="Ambiguous Window",
            interactive_elements=[
                UIElement(role="AXButton", title="Save", bounds={"x": 10, "y": 10, "width": 40, "height": 20}),
                UIElement(role="AXButton", title="Save", bounds={"x": 100, "y": 10, "width": 40, "height": 20}),
            ],
        )
        match = self.grounder.ground(
            TargetConstraints(label="Save", role="button"),
            ambiguous_state,
        )
        # Refuses blind action when multiple identical items conflict
        self.assertFalse(match.is_reliable)
        self.assertEqual(match.confidence, GroundingConfidence.WEAK)
        self.assertIn("Ambiguous target", match.rationale)


if __name__ == "__main__":
    unittest.main()
