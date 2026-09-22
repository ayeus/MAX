"""Voice subsystem for MAX."""

from .tts import speak_text, list_available_voices, TTSResult
from .recorder import record_microphone, AudioRecording
from .whisper_stt import transcribe_audio, is_whisper_available, TranscriptionResult, STTService
from .wake import WakeWordDetector, WakeDetectionResult
from .assistant import VoiceAssistant

__all__ = [
    "speak_text",
    "list_available_voices",
    "TTSResult",
    "record_microphone",
    "AudioRecording",
    "transcribe_audio",
    "is_whisper_available",
    "TranscriptionResult",
    "STTService",
    "WakeWordDetector",
    "WakeDetectionResult",
    "VoiceAssistant",
]

