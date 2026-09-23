"""Unit tests for Voice Reliability, State Machine, Earcon Fallback, and Watchdog."""

import unittest
from unittest.mock import MagicMock, patch
import os
import time
import threading

from voice.assistant import VoiceAssistant, VoiceState, is_cancel_command
from voice.tts import speak_async, stop_speaking, play_earcon


class TestVoiceReliability(unittest.TestCase):

    def test_voice_states_enumeration(self):
        """Verify all required states exist in VoiceState enum."""
        expected_states = [
            "IDLE", "WAKE_DETECTING", "CAPTURING", "TRANSCRIBING",
            "THINKING", "EXECUTING", "VERIFYING", "REPLANNING",
            "SPEAKING", "CANCELLED", "ERROR", "RECOVERING", "DONE"
        ]
        for state_name in expected_states:
            self.assertIn(state_name, VoiceState.__members__)

    def test_cancel_command_detection(self):
        """Verify various forms of cancellation triggers are recognized."""
        self.assertTrue(is_cancel_command("stop"))
        self.assertTrue(is_cancel_command("cancel"))
        self.assertTrue(is_cancel_command("max stop"))
        self.assertTrue(is_cancel_command("max cancel"))
        self.assertTrue(is_cancel_command("abort"))
        self.assertTrue(is_cancel_command("never mind"))
        self.assertTrue(is_cancel_command("halt"))
        self.assertTrue(is_cancel_command("stop please"))

        self.assertFalse(is_cancel_command("open chrome"))
        self.assertFalse(is_cancel_command("what is the weather"))
        self.assertFalse(is_cancel_command("calculator"))

    def test_earcon_missing_file_fallback(self):
        """Verify play_earcon handles nonexistent audio files gracefully without crashing."""
        non_existent = "/tmp/non_existent_earcon_123456.aiff"
        if os.path.exists(non_existent):
            os.remove(non_existent)

        # Should return without raising an exception
        res = play_earcon(non_existent)
        self.assertFalse(res)

    def test_earcon_valid_system_sound(self):
        """Verify play_earcon works with standard macOS system sound if present."""
        system_sound = "/System/Library/Sounds/Tink.aiff"
        if not os.path.exists(system_sound):
            self.skipTest("Required macOS system sound unavailable")
        res = play_earcon(system_sound)
        self.assertTrue(res)

    def test_voice_assistant_watchdog_triggers_on_stuck_state(self):
        """Verify watchdog detects stuck state and recovers to IDLE."""
        assistant = VoiceAssistant(agent=MagicMock())
        assistant.set_state(VoiceState.EXECUTING)
        # Artificially age the state
        assistant.state_updated_at = time.time() - 100.0

        recovered = assistant.check_watchdog(max_duration_seconds=30.0)
        self.assertTrue(recovered)
        self.assertEqual(assistant.state, VoiceState.IDLE)

    def test_voice_assistant_watchdog_does_not_trigger_when_idle(self):
        """Verify watchdog does not trigger when assistant is legitimately IDLE."""
        assistant = VoiceAssistant(agent=MagicMock())
        assistant.set_state(VoiceState.IDLE)
        assistant.state_updated_at = time.time() - 1000.0

        recovered = assistant.check_watchdog(max_duration_seconds=30.0)
        self.assertFalse(recovered)
        self.assertEqual(assistant.state, VoiceState.IDLE)

    def test_async_speech_and_stop(self):
        """Verify speak_async starts without blocking and stop_speaking terminates it."""
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            stop_event = threading.Event()

            def slow_communicate(*args, **kwargs):
                stop_event.wait(timeout=2.0)
                return ("", "")

            mock_proc.communicate.side_effect = slow_communicate
            def mock_terminate():
                stop_event.set()
            mock_proc.terminate.side_effect = mock_terminate
            mock_proc.kill.side_effect = mock_terminate
            mock_popen.return_value = mock_proc

            thread = speak_async("Hello world from async speech test")
            self.assertIsNotNone(thread)

            # Wait briefly for thread to spawn subprocess and enter communicate
            time.sleep(0.05)
            self.assertTrue(mock_popen.called, "subprocess.Popen was not invoked for async speech")

            # Now call stop_speaking and verify termination/cleanup was executed on the process
            stop_speaking()
            self.assertTrue(
                mock_proc.terminate.called or mock_proc.kill.called,
                "Neither terminate() nor kill() was invoked on active speech process"
            )
            thread.join(timeout=1.0)


if __name__ == "__main__":
    unittest.main()
