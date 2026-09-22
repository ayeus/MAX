"""Unit tests for Wake Word Detection and Hands-Free Voice Assistant."""

import unittest
from unittest.mock import MagicMock, patch
from voice.wake import WakeWordDetector, WakeDetectionResult
from voice.assistant import VoiceAssistant
from voice.recorder import AudioRecording


class TestWakeWordAndAssistant(unittest.TestCase):
    """Test suite for WakeWordDetector and VoiceAssistant."""

    def setUp(self):
        self.detector = WakeWordDetector(wake_word="max")

    def test_standalone_wake_words(self):
        """Test detection of standalone wake word calls without inline commands."""
        test_phrases = [
            "Max",
            "max",
            "MAX",
            "Hey Max",
            "hey max",
            "Hi Max",
            "hi max",
            "Okay Max",
            "ok max",
            "hello max",
            "Max!",
            "Hey Max.",
            "Max...",
        ]
        for phrase in test_phrases:
            res = self.detector.detect(phrase)
            self.assertTrue(res.detected, f"Failed to detect standalone: '{phrase}'")
            self.assertTrue(res.is_standalone, f"Expected is_standalone=True for: '{phrase}'")
            self.assertIsNone(res.inline_task, f"Expected inline_task=None for: '{phrase}'")

    def test_inline_command_extraction(self):
        """Test extraction of inline tasks spoken in the same breath as the wake word."""
        cases = [
            ("Max, open Google Chrome", "open Google Chrome"),
            ("Hey Max! Search the web for Python documentation", "Search the web for Python documentation"),
            ("Okay Max run git status", "run git status"),
            ("Max: find all markdown files in my project", "find all markdown files in my project"),
            ("Hi Max, check if Docker is running", "check if Docker is running"),
            ("Max start a background task to sleep 10", "start a background task to sleep 10"),
        ]
        for phrase, expected_task in cases:
            res = self.detector.detect(phrase)
            self.assertTrue(res.detected, f"Failed to detect: '{phrase}'")
            self.assertFalse(res.is_standalone, f"Expected is_standalone=False for: '{phrase}'")
            self.assertEqual(res.inline_task, expected_task, f"Task mismatch for: '{phrase}'")

    def test_negative_cases_no_false_positives(self):
        """Ensure non-wake words and partial matches do not trigger activation."""
        negative_phrases = [
            "maximum speed",
            "maximized window",
            "the climax was intense",
            "hello there",
            "open google chrome",
            "what is the time",
            "just testing",
            "",
            "   ",
        ]
        for phrase in negative_phrases:
            res = self.detector.detect(phrase)
            self.assertFalse(res.detected, f"False positive on: '{phrase}'")

    def test_custom_wake_word(self):
        """Verify custom wake words can be configured."""
        custom_detector = WakeWordDetector(wake_word="jarvis")
        res = custom_detector.detect("Hey Jarvis, what is my battery level?")
        self.assertTrue(res.detected)
        self.assertEqual(res.inline_task, "what is my battery level?")

        res_max = custom_detector.detect("Hey Max")
        self.assertFalse(res_max.detected)

    @patch("voice.assistant.speak_text")
    def test_voice_assistant_execute_task(self, mock_speak):
        """Verify VoiceAssistant dispatches task to AgentCore and speaks outcome."""
        mock_agent = MagicMock()
        mock_report = MagicMock()
        mock_report.final_summary = "Task executed successfully."
        mock_agent.run.return_value = mock_report

        assistant = VoiceAssistant(wake_word="max", agent=mock_agent)
        summary = assistant.execute_task("Open Chrome", speak_summary=True)

        self.assertEqual(summary, "Task executed successfully.")
        mock_agent.run.assert_called_once_with("Open Chrome")
        mock_speak.assert_called_once_with("Task executed successfully.", voice=None)

    @patch("voice.assistant.play_earcon")
    @patch("voice.assistant.record_microphone")
    @patch("voice.assistant.transcribe_audio")
    @patch("voice.assistant.speak_text")
    def test_voice_assistant_step_standalone_cycle(self, mock_speak, mock_stt, mock_record, mock_earcon):
        """Test full step cycle when user says standalone 'Max' followed by a command with earcon."""
        from voice.whisper_stt import TranscriptionResult

        mock_record.side_effect = [
            AudioRecording(success=True, wav_path="/tmp/fake_wake.wav", duration_seconds=3.0),
            AudioRecording(success=True, wav_path="/tmp/fake_task.wav", duration_seconds=8.0),
        ]
        mock_stt.side_effect = [
            TranscriptionResult(success=True, text="Hey Max"),
            TranscriptionResult(success=True, text="open terminal"),
        ]

        mock_agent = MagicMock()
        mock_report = MagicMock()
        mock_report.final_summary = "Terminal launched."
        mock_agent.run.return_value = mock_report

        assistant = VoiceAssistant(wake_word="max", agent=mock_agent, use_earcon_ack=True)
        handled = assistant.step()

        self.assertTrue(handled)
        # Non-blocking earcon played immediately
        mock_earcon.assert_called_once()
        # Only final summary is spoken (no blocking acknowledgment sentence)
        mock_speak.assert_called_once_with("Terminal launched.", voice=None)
        mock_agent.run.assert_called_once_with("open terminal")

    @patch("voice.assistant.record_microphone")
    @patch("voice.assistant.transcribe_audio")
    @patch("voice.assistant.speak_text")
    def test_voice_assistant_step_inline_cycle(self, mock_speak, mock_stt, mock_record):
        """Test full step cycle when user says one-shot 'Max, open terminal' with spoken ack."""
        from voice.whisper_stt import TranscriptionResult

        mock_record.return_value = AudioRecording(success=True, wav_path="/tmp/fake_inline.wav", duration_seconds=3.0)
        mock_stt.return_value = TranscriptionResult(success=True, text="Max, open terminal")

        mock_agent = MagicMock()
        mock_report = MagicMock()
        mock_report.final_summary = "Terminal opened."
        mock_agent.run.return_value = mock_report

        # Test legacy spoken acknowledgment when earcon is disabled
        assistant = VoiceAssistant(wake_word="max", agent=mock_agent, use_earcon_ack=False)
        handled = assistant.step()

        self.assertTrue(handled)
        # Should speak "On it." acknowledgment, then final summary
        self.assertEqual(mock_speak.call_count, 2)
        mock_agent.run.assert_called_once_with("open terminal")


if __name__ == "__main__":
    unittest.main()
