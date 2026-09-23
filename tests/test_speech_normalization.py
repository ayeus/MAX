"""Unit and integration tests for MAX Speech Normalization & Interpretation Layer.

Taxonomy:
- UNIT: Linguistic transformations, regex compound repair, filler stripping.
- INTEGRATION: Semantic intent classification, phrasing synonyms, and ambiguity detection.
"""

import unittest
from voice.normalization import SpeechNormalizer, normalizer
from voice.interpretation import SpeechInterpretation


class TestSpeechNormalization(unittest.TestCase):
    """Test suite for SpeechNormalizer and semantic interpretation."""

    def setUp(self):
        self.normalizer = SpeechNormalizer()

    def test_whisper_phonetic_split_repair(self):
        """[UNIT] Verify Whisper phonetic split compounds are repaired to canonical words."""
        cases = [
            ("increase my bright ness", "brightness"),
            ("open spot light search", "Spotlight"),
            ("focus key board element", "keyboard"),
            ("copy to clip board", "clipboard"),
            ("scan file system directory", "filesystem"),
            ("launch text edit", "TextEdit"),
            ("search app store", "App Store"),
        ]
        for raw, expected_token in cases:
            cleaned, fixes = self.normalizer.apply_compound_corrections(raw)
            self.assertIn(
                expected_token.lower(),
                cleaned.lower(),
                f"Failed compound repair for '{raw}' -> expected '{expected_token}' in '{cleaned}'",
            )
            self.assertGreater(len(fixes), 0, f"Expected correction trace for '{raw}'")

    def test_filler_and_conversational_prefix_stripping(self):
        """[UNIT] Verify conversational noise and wake prefixes are stripped cleanly."""
        cases = [
            ("Hey Max, please open Safari", "open Safari"),
            ("Max: can you open Chrome", "open Chrome"),
            ("Ok Max, could you please increase brightness", "increase brightness"),
            ("um, uh, turn up brightness", "turn up brightness"),
            ("I want you to launch Terminal", "launch Terminal"),
            ("go ahead and dim the screen", "dim the screen"),
        ]
        for raw, expected_stem in cases:
            interp = self.normalizer.normalize(raw)
            self.assertEqual(
                interp.normalized_text.lower(),
                expected_stem.lower(),
                f"Stem mismatch for '{raw}': got '{interp.normalized_text}', expected '{expected_stem}'",
            )

    def test_macos_application_alias_resolution(self):
        """[UNIT] Verify colloquial application names map to canonical macOS app bundle names."""
        aliases = [
            ("chrome", "Google Chrome"),
            ("chrome browser", "Google Chrome"),
            ("google chrome", "Google Chrome"),
            ("safari browser", "Safari"),
            ("vs code", "Visual Studio Code"),
            ("vscode", "Visual Studio Code"),
            ("visual studio code", "Visual Studio Code"),
            ("text edit", "TextEdit"),
            ("texteditor", "Texteditor"),  # fallback title case
            ("terminal app", "Terminal"),
            ("system preferences", "System Settings"),
            ("system settings", "System Settings"),
        ]
        for spoken, canonical in aliases:
            resolved = self.normalizer.resolve_app_name(spoken)
            self.assertEqual(
                resolved,
                canonical,
                f"App resolution mismatch: spoken '{spoken}' -> '{resolved}', expected '{canonical}'",
            )

    def test_brightness_phrasing_synonyms(self):
        """[INTEGRATION] Verify diverse natural language brightness phrasing resolves to canonical intent."""
        increase_phrases = [
            "increase my brightness",
            "increase the screen brightness",
            "raise display brightness",
            "boost brightness",
            "bump up brightness",
            "turn up the brightness",
            "turn the brightness up",
            "make the screen brighter",
            "make my display a little brighter",
            "brighten the screen",
            "brighten my display",
        ]
        for phrase in increase_phrases:
            interp = self.normalizer.normalize(phrase)
            self.assertEqual(
                interp.intent,
                "increase_brightness",
                f"Phrase '{phrase}' failed to map to 'increase_brightness' (got '{interp.intent}')",
            )
            self.assertFalse(interp.is_ambiguous, f"Phrase '{phrase}' was marked ambiguous unexpectedly")

        decrease_phrases = [
            "decrease my brightness",
            "lower screen brightness",
            "reduce the brightness",
            "dim the display",
            "dim my screen",
            "turn down the brightness",
            "turn the brightness down",
            "make the screen dimmer",
            "make display a bit darker",
        ]
        for phrase in decrease_phrases:
            interp = self.normalizer.normalize(phrase)
            self.assertEqual(
                interp.intent,
                "decrease_brightness",
                f"Phrase '{phrase}' failed to map to 'decrease_brightness' (got '{interp.intent}')",
            )
            self.assertFalse(interp.is_ambiguous, f"Phrase '{phrase}' was marked ambiguous unexpectedly")

    def test_ambiguity_detection_and_clarification_prompts(self):
        """[INTEGRATION] Verify vague or underspecified commands trigger ambiguity flags with user prompts."""
        ambiguous_cases = [
            ("open something", "Which app should I open?"),
            ("launch an app", "Which app should I open?"),
            ("close whatever", "Which application should I close?"),
            ("quit the app", "Which application should I close?"),
            ("delete that file", "Which file or item should I delete?"),
        ]
        for phrase, expected_prompt_part in ambiguous_cases:
            interp = self.normalizer.normalize(phrase)
            self.assertTrue(
                interp.is_ambiguous,
                f"Phrase '{phrase}' should be flagged ambiguous but was not",
            )
            self.assertIsNotNone(interp.ambiguity_reason)
            self.assertIsNotNone(interp.clarification_prompt)
            self.assertIn(
                expected_prompt_part.lower(),
                (interp.clarification_prompt or "").lower(),
                f"Clarification prompt mismatch for '{phrase}': got '{interp.clarification_prompt}'",
            )

    def test_empty_or_pure_wake_utterances(self):
        """[UNIT] Verify empty speech or pure wake words produce ambiguous/no-op interpretation without crashing."""
        empty_interp = self.normalizer.normalize("")
        self.assertTrue(empty_interp.is_ambiguous)
        self.assertEqual(empty_interp.confidence, 0.0)

        wake_only_interp = self.normalizer.normalize("Hey Max")
        self.assertTrue(wake_only_interp.is_ambiguous)
        self.assertEqual(wake_only_interp.normalized_text, "")
        self.assertIn("listening", (wake_only_interp.clarification_prompt or "").lower())


if __name__ == "__main__":
    unittest.main()
