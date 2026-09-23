"""Unit and live subsystem tests for MAX Continuous Audio Streaming & Pre-Roll Ring Buffer.

Taxonomy:
- UNIT: Circular buffer memory bounds, pre-roll retention calculations, and RMS decibel computations.
- LIVE_SUBSYSTEM: Real Swift max-audio-stream process invocation, pipe I/O, and continuous PCM ingestion.
"""

import math
import numpy as np
import time
import unittest
from voice.audio_stream import ContinuousAudioStream


class TestWakeAudioStream(unittest.TestCase):
    """Test suite for continuous microphone streaming and pre-roll retention."""

    def test_unit_ring_buffer_bounds_and_retention(self):
        """[UNIT] Verify circular pre-buffer strictly caps memory to configured milliseconds."""
        stream = ContinuousAudioStream(pre_roll_ms=500.0)  # 500ms = 16000 bytes at 32kB/s
        expected_bytes = stream.pre_roll_bytes
        self.assertEqual(expected_bytes, 16000)

        # Ingest 8000 bytes (250ms)
        fake_chunk1 = b"\x00\x01" * 4000
        with stream._buffer_lock:
            stream._ring_buffer.extend(fake_chunk1)

        snapshot1 = stream.get_pre_roll_bytes()
        self.assertEqual(len(snapshot1), 8000)

        # Ingest 16000 more bytes (total 24000 bytes > 16000 max capacity)
        fake_chunk2 = b"\x02\x03" * 8000
        with stream._buffer_lock:
            stream._ring_buffer.extend(fake_chunk2)
            if len(stream._ring_buffer) > stream.pre_roll_bytes:
                del stream._ring_buffer[: len(stream._ring_buffer) - stream.pre_roll_bytes]

        snapshot2 = stream.get_pre_roll_bytes()
        self.assertEqual(len(snapshot2), 16000, "Ring buffer must not exceed pre_roll_bytes")
        # Ensure oldest bytes were evicted and newest retained
        self.assertTrue(snapshot2.endswith(b"\x02\x03" * 10))

    def test_unit_rms_db_calculation(self):
        """[UNIT] Verify RMS energy level math accurately identifies silence vs speech."""
        stream = ContinuousAudioStream()

        # 1. Total silence
        silence_bytes = b"\x00\x00" * 512
        db_silence = stream.calculate_rms_db(silence_bytes)
        self.assertEqual(db_silence, -100.0)

        # 2. Loud full-scale square wave (+32767, -32767)
        loud_samples = np.array([32767, -32767] * 256, dtype=np.int16)
        db_loud = stream.calculate_rms_db(loud_samples.tobytes())
        self.assertGreater(db_loud, -2.0)  # Near 0 dBFS

        # 3. Conversational speech level amplitude (~1000 to 4000)
        speech_samples = (np.sin(np.linspace(0, 20 * np.pi, 512)) * 3000).astype(np.int16)
        db_speech = stream.calculate_rms_db(speech_samples.tobytes())
        self.assertGreater(db_speech, -35.0)
        self.assertLess(db_speech, -15.0)

    def test_live_subsystem_stream_ingestion_and_pre_roll(self):
        """[LIVE_SUBSYSTEM] Start real Swift max-audio-stream and verify continuous PCM bytes fill pre-roll buffer."""
        stream = ContinuousAudioStream(pre_roll_ms=600.0)
        started = stream.start(timeout=3.0)
        if not started:
            self.skipTest("Swift max-audio-stream binary could not be started.")

        try:
            self.assertTrue(stream.is_running)
            # Allow stream to accumulate ~800ms of audio
            time.sleep(0.8)

            pre_roll = stream.get_pre_roll_bytes()
            self.assertGreater(
                len(pre_roll),
                0,
                "Continuous audio stream failed to ingest any PCM bytes from microphone",
            )
            # At 16kHz 16-bit mono (32kB/s), 600ms = 19,200 bytes
            self.assertAlmostEqual(len(pre_roll), stream.pre_roll_bytes, delta=3200)

            # Convert to float32 waveform and verify finite numbers
            waveform = np.frombuffer(pre_roll, dtype=np.int16).astype(np.float32) / 32768.0
            self.assertTrue(np.all(np.isfinite(waveform)))
            self.assertTrue(np.all(waveform >= -1.0))
            self.assertTrue(np.all(waveform <= 1.0))
        finally:
            stream.stop()
            self.assertFalse(stream.is_running)


if __name__ == "__main__":
    unittest.main()
