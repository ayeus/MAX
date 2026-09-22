"""Unit tests for voice and speech synthesis subsystem."""

import unittest
from voice.tts import list_available_voices, speak_text
from voice.whisper_stt import is_whisper_available, transcribe_audio


class TestVoice(unittest.TestCase):

    def test_list_available_voices(self):
        voices = list_available_voices()
        self.assertGreater(len(voices), 0)
        names = [v.name for v in voices]
        self.assertTrue(any(n in names for n in ("Samantha", "Albert", "Daniel", "Alex", "Fred")))

    def test_speak_empty_text_noop(self):
        res = speak_text("")
        self.assertTrue(res.success)
        self.assertEqual(res.duration_ms, 0.0)

    def test_whisper_availability_check(self):
        # Must return a boolean without crashing
        avail = is_whisper_available()
        self.assertIsInstance(avail, bool)

    def test_transcribe_missing_audio_file(self):
        res = transcribe_audio("/non/existent/path/test.wav")
        self.assertFalse(res.success)
        self.assertIn("does not exist", res.error)


if __name__ == "__main__":
    unittest.main()
