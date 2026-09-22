"""Wake word detection engine for MAX."""

import re
from typing import Optional
from pydantic import BaseModel


class WakeDetectionResult(BaseModel):
    detected: bool
    wake_word: Optional[str] = None
    inline_task: Optional[str] = None
    is_standalone: bool = False
    raw_text: str = ""


class WakeWordDetector:
    """Detects spoken activation triggers for MAX and separates wake words from inline tasks."""

    DEFAULT_WAKE_WORDS = ["max", "hey max", "hi max", "okay max", "ok max", "hello max"]

    def __init__(self, wake_word: str = "max", aliases: Optional[list[str]] = None):
        self.primary_name = wake_word.strip().lower()
        self.aliases = [a.lower() for a in (aliases or ["hey " + self.primary_name, "hi " + self.primary_name, "okay " + self.primary_name, "ok " + self.primary_name, "hello " + self.primary_name])]

        # Pattern matching prefix wake word: e.g. "Max, open Chrome", "Hey Max!", "Max"
        escaped_name = re.escape(self.primary_name)
        self.prefix_pattern = re.compile(
            rf"^(?:(?:hey|hi|hello|ok|okay)\s+)?{escaped_name}\b[,\s:!.-]*(.*)$",
            re.IGNORECASE | re.DOTALL,
        )

        # General boundary pattern to detect wake word anywhere in the utterance
        self.general_pattern = re.compile(
            rf"\b(?:(?:hey|hi|hello|ok|okay)\s+)?{escaped_name}\b",
            re.IGNORECASE,
        )

    def detect(self, text: str) -> WakeDetectionResult:
        cleaned = text.strip()
        if not cleaned:
            return WakeDetectionResult(detected=False, raw_text=text)

        # 1. Check for prefix wake word (e.g. "Max", "Max, open chrome", "Hey Max do X")
        prefix_match = self.prefix_pattern.match(cleaned)
        if prefix_match:
            inline = prefix_match.group(1).strip()
            # Remove leading punctuation from inline task
            inline = re.sub(r"^[,\s:!.-]+", "", inline).strip()
            is_standalone = len(inline) == 0

            return WakeDetectionResult(
                detected=True,
                wake_word=self.primary_name,
                inline_task=inline if inline else None,
                is_standalone=is_standalone,
                raw_text=text,
            )

        # 2. Check general boundary presence
        gen_match = self.general_pattern.search(cleaned)
        if gen_match:
            # Wake word was spoken in sentence
            start, end = gen_match.span()
            before = cleaned[:start].strip()
            after = cleaned[end:].strip()
            remainder = f"{before} {after}".strip()
            remainder = re.sub(r"^[,\s:!.-]+", "", remainder).strip()

            return WakeDetectionResult(
                detected=True,
                wake_word=self.primary_name,
                inline_task=remainder if remainder else None,
                is_standalone=len(remainder) == 0,
                raw_text=text,
            )

        return WakeDetectionResult(detected=False, raw_text=text)
