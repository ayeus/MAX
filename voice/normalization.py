"""Linguistic and semantic speech normalization layer for MAX.

Normalizes speech recognition artifacts, Whisper compound-word splits,
macOS terminology, filler words, and phrasing synonyms into canonical intents.
Detects target ambiguity and provides clarification prompts.
"""

from __future__ import annotations
import re
from typing import Optional, Any
from .interpretation import SpeechInterpretation


class SpeechNormalizer:
    """Reusable linguistic and semantic normalizer for spoken utterances."""

    # 1. Phonetic / Whisper transcription split compounds
    COMPOUND_CORRECTIONS: list[tuple[re.Pattern, str]] = [
        (re.compile(r"\bbright\s+ness\b", re.IGNORECASE), "brightness"),
        (re.compile(r"\bspot\s+light\b", re.IGNORECASE), "Spotlight"),
        (re.compile(r"\bkey\s+board\b", re.IGNORECASE), "keyboard"),
        (re.compile(r"\bclip\s+board\b", re.IGNORECASE), "clipboard"),
        (re.compile(r"\bfile\s+system\b", re.IGNORECASE), "filesystem"),
        (re.compile(r"\btime\s+out\b", re.IGNORECASE), "timeout"),
        (re.compile(r"\bwi\s+fi\b", re.IGNORECASE), "wifi"),
        (re.compile(r"\bapp\s+store\b", re.IGNORECASE), "App Store"),
        (re.compile(r"\btext\s+edit\b", re.IGNORECASE), "TextEdit"),
    ]

    # 2. Leading conversational fillers and wake fragments
    FILLER_PREFIXES: list[re.Pattern] = [
        re.compile(r"^(?:(?:hey|hi|hello|ok|okay)\s+)?max(?:[,\s:!-]+|$)", re.IGNORECASE),
        re.compile(r"^(?:can\s+you\s+(?:please\s+)?|could\s+you\s+(?:please\s+)?|please\s+|would\s+you\s+|i\s+want\s+you\s+to\s+|go\s+ahead\s+and\s+)", re.IGNORECASE),
        re.compile(r"^(?:um+|uh+|er+|ah+|like)[,\s]+", re.IGNORECASE),
    ]

    # 3. macOS Application Aliases (canonical app names)
    APP_ALIASES: dict[str, str] = {
        "chrome browser": "Google Chrome",
        "google chrome": "Google Chrome",
        "chrome": "Google Chrome",
        "safari browser": "Safari",
        "safari": "Safari",
        "textedit": "TextEdit",
        "text edit": "TextEdit",
        "text editor": "TextEdit",
        "visual studio code": "Visual Studio Code",
        "visual studio": "Visual Studio Code",
        "vs code": "Visual Studio Code",
        "vscode": "Visual Studio Code",
        "terminal app": "Terminal",
        "terminal": "Terminal",
        "system settings": "System Settings",
        "system preferences": "System Settings",
        "settings": "System Settings",
        "preferences": "System Settings",
        "finder": "Finder",
        "calculator": "Calculator",
        "notes": "Notes",
        "apple notes": "Notes",
        "messages": "Messages",
        "imessage": "Messages",
        "mail": "Mail",
        "apple mail": "Mail",
        "calendar": "Calendar",
        "activity monitor": "Activity Monitor",
    }

    # 4. Semantic Intent Patterns
    # Brightness adjustment
    BRIGHTNESS_TARGET_PATTERNS = [
        re.compile(
            r"\b(?:set|turn|make|change|adjust|increase|raise|boost|decrease|lower|reduce|dim|drop)?\s*"
            r"(?:(?:the|my|screen|display)\s+)*brightness\s+"
            r"(?:to|at|=)?\s*(\d+(?:\.\d+)?)\s*(%|percent)?\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:set|make|turn)\s+(?:(?:the|my)\s+)?(?:screen|display)\s+(?:to|at)?\s*(\d+(?:\.\d+)?)\s*(%|percent)?\s*(?:brightness)?\b",
            re.IGNORECASE,
        ),
    ]

    BRIGHTNESS_INCREASE_PATTERNS = [
        re.compile(r"\b(?:increase|raise|boost|bump\s+up|turn\s+up)\s+(?:(?:the|my|screen|display)\s+)*brightness\b", re.IGNORECASE),
        re.compile(r"\b(?:make|turn)\s+(?:(?:the|my)\s+)?(?:screen|display)\s+(?:a\s+(?:little|bit)\s+)?brighter\b", re.IGNORECASE),
        re.compile(r"\bbrighten\s+(?:(?:the|my)\s+)?(?:screen|display)\b", re.IGNORECASE),
        re.compile(r"\bturn\s+(?:(?:the|my|screen|display)\s+)*brightness\s+up\b", re.IGNORECASE),
    ]

    BRIGHTNESS_DECREASE_PATTERNS = [
        re.compile(r"\b(?:decrease|lower|reduce|dim|drop|turn\s+down)\s+(?:(?:the|my|screen|display)\s+)*brightness\b", re.IGNORECASE),
        re.compile(r"\b(?:make|turn)\s+(?:(?:the|my)\s+)?(?:screen|display)\s+(?:a\s+(?:little|bit)\s+)?(?:dimmer|darker)\b", re.IGNORECASE),
        re.compile(r"\bdim\s+(?:(?:the|my)\s+)?(?:screen|display)\b", re.IGNORECASE),
        re.compile(r"\bturn\s+(?:(?:the|my|screen|display)\s+)*brightness\s+down\b", re.IGNORECASE),
    ]


    # Terminal command execution
    TERMINAL_COMMAND_PATTERNS = [
        re.compile(r"^(?:run|execute)\s+(?:terminal\s+|shell\s+|bash\s+)?command:?\s*(.+)$", re.IGNORECASE),
        re.compile(r"^(?:run|execute)\s+in\s+terminal:?\s*(.+)$", re.IGNORECASE),
    ]

    # Application launching
    APP_LAUNCH_PATTERNS = [
        re.compile(r"^(?:open|launch|start|run|bring\s+up)\s+(.+)$", re.IGNORECASE),
    ]

    # Application quitting
    APP_QUIT_PATTERNS = [
        re.compile(r"^(?:close|quit|exit|terminate|kill)\s+(.+)$", re.IGNORECASE),
    ]

    # Ambiguous placeholder targets
    AMBIGUOUS_TARGETS = {
        "something", "an app", "some app", "the app", "it", "that", "this", "whatever", "anything", "...", "stuff"
    }

    def clean_text(self, text: str) -> str:
        """Strip punctuation, excessive whitespace, and edge noise."""
        cleaned = text.strip()
        cleaned = re.sub(r"^[,\s:!.\-—]+", "", cleaned)
        cleaned = re.sub(r"[,\s:!.\-—]+$", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned

    def remove_fillers(self, text: str) -> tuple[str, list[str]]:
        """Remove leading conversational prefixes and conversational fillers."""
        current = text.strip()
        corrections = []
        changed = True
        while changed:
            changed = False
            for pat in self.FILLER_PREFIXES:
                m = pat.match(current)
                if m:
                    removed = m.group(0).strip()
                    current = current[m.end():].strip()
                    current = self.clean_text(current)
                    corrections.append(f"removed_filler: '{removed}'")
                    changed = True
        return current, corrections

    def apply_compound_corrections(self, text: str) -> tuple[str, list[str]]:
        """Fix phonetic/compound splits produced by Whisper."""
        current = text
        corrections = []
        for pat, replacement in self.COMPOUND_CORRECTIONS:
            if pat.search(current):
                current = pat.sub(replacement, current)
                corrections.append(f"compound_fix: -> '{replacement}'")
        return current, corrections

    def resolve_app_name(self, raw_name: str) -> str:
        """Resolve a spoken app name or alias to its canonical system application name."""
        cleaned = raw_name.strip().lower()
        # Direct lookup in known aliases
        if cleaned in self.APP_ALIASES:
            return self.APP_ALIASES[cleaned]
        # Strip trailing "browser" or "app"
        for suffix in (" browser", " app", " application"):
            if cleaned.endswith(suffix):
                stem = cleaned[:-len(suffix)].strip()
                if stem in self.APP_ALIASES:
                    return self.APP_ALIASES[stem]
                return stem.title()
        return raw_name.strip().title()

    def normalize(self, raw_utterance: str, stt_confidence: float = 1.0) -> SpeechInterpretation:
        """Full pipeline: clean, denoise, normalize, extract intent, and evaluate ambiguity."""
        cleaned = self.clean_text(raw_utterance)
        if not cleaned:
            return SpeechInterpretation(
                raw_text=raw_utterance,
                normalized_text="",
                confidence=0.0,
                is_ambiguous=True,
                ambiguity_reason="No speech detected.",
                clarification_prompt="I didn't hear anything. How can I help you?",
            )

        corrections: list[str] = []

        # 1. Apply phonetic / compound split fixes
        text_after_compounds, compound_fixes = self.apply_compound_corrections(cleaned)
        corrections.extend(compound_fixes)

        # 2. Remove conversational fillers and wake word prefixes
        text_without_fillers, filler_fixes = self.remove_fillers(text_after_compounds)
        corrections.extend(filler_fixes)

        normalized = self.clean_text(text_without_fillers)
        if not normalized:
            # Utterance was purely a wake word or filler (e.g. "Max", "Hey Max")
            return SpeechInterpretation(
                raw_text=raw_utterance,
                normalized_text="",
                confidence=stt_confidence,
                is_ambiguous=True,
                ambiguity_reason="Wake word only without command.",
                clarification_prompt="Yes, I'm listening.",
            )

        # 3. Intent & Target Semantic Extraction
        intent: Optional[str] = None
        target: Optional[str] = None
        params: dict[str, Any] = {}
        is_ambiguous = False
        ambiguity_reason: Optional[str] = None
        clarification_prompt: Optional[str] = None

        # Check Brightness Target Level (Invariant 8: Target level vs delta)
        for pat in self.BRIGHTNESS_TARGET_PATTERNS:
            m = pat.search(normalized)
            if m:
                raw_val = float(m.group(1))
                unit = (m.group(2) or "").strip().lower()
                is_pct = unit in ("%", "percent") or raw_val > 1.0
                target_level = max(0.0, min(1.0, raw_val / 100.0 if is_pct else raw_val))
                intent = "set_brightness"
                target = "display"
                params = {"level": target_level}
                break

        # Check Brightness Increase
        if not intent:
            for pat in self.BRIGHTNESS_INCREASE_PATTERNS:
                if pat.search(normalized):
                    intent = "increase_brightness"
                    target = "display"
                    params = {"delta": 0.1}
                    break

        # Check Brightness Decrease
        if not intent:
            for pat in self.BRIGHTNESS_DECREASE_PATTERNS:
                if pat.search(normalized):
                    intent = "decrease_brightness"
                    target = "display"
                    params = {"delta": 0.1}
                    break

        # Check Window Closing
        if not intent:
            if re.search(r"\bclose\s+(?:this|current|active|the)\s+window\b", normalized, re.IGNORECASE):
                intent = "close_window"
                target = "front_window"

        # Check Terminal Command Execution
        if not intent:
            for pat in self.TERMINAL_COMMAND_PATTERNS:
                m = pat.match(normalized)
                if m:
                    raw_cmd = m.group(1).strip()
                    intent = "execute_command"
                    target = "terminal"
                    params = {"command": raw_cmd}
                    break

        # Check App Launching
        if not intent:
            for pat in self.APP_LAUNCH_PATTERNS:
                m = pat.match(normalized)
                if m:
                    raw_target = m.group(1).strip()
                    cleaned_target = self.clean_text(raw_target).lower()
                    if cleaned_target in self.AMBIGUOUS_TARGETS or cleaned_target == "...":
                        is_ambiguous = True
                        ambiguity_reason = "Unspecified application target."
                        clarification_prompt = "I didn't catch the app name. Which app should I open?"
                        intent = "launch_application"
                    else:
                        intent = "launch_application"
                        target = self.resolve_app_name(raw_target)
                        params = {"application_name": target}
                    break

        # Check App Quitting
        if not intent:
            for pat in self.APP_QUIT_PATTERNS:
                m = pat.match(normalized)
                if m:
                    raw_target = m.group(1).strip()
                    cleaned_target = self.clean_text(raw_target).lower()
                    if cleaned_target in ("this window", "current window", "window"):
                        intent = "close_window"
                        target = "front_window"
                    elif cleaned_target in self.AMBIGUOUS_TARGETS or cleaned_target == "...":
                        is_ambiguous = True
                        ambiguity_reason = "Unspecified application target."
                        clarification_prompt = "Which application should I close?"
                        intent = "quit_application"
                    else:
                        intent = "quit_application"
                        target = self.resolve_app_name(raw_target)
                        params = {"application_name": target}
                    break

        # General ambiguity check for vague verbs with placeholder targets
        if not intent and any(v in normalized.lower() for v in ("delete", "remove", "erase")):
            words = normalized.lower().split()
            if any(w in self.AMBIGUOUS_TARGETS for w in words):
                is_ambiguous = True
                ambiguity_reason = "Ambiguous destructive target."
                clarification_prompt = "Which file or item should I delete?"

        return SpeechInterpretation(
            raw_text=raw_utterance,
            normalized_text=normalized,
            confidence=stt_confidence,
            corrections=corrections,
            is_ambiguous=is_ambiguous,
            ambiguity_reason=ambiguity_reason,
            clarification_prompt=clarification_prompt,
            intent=intent,
            target=target,
            parameters=params,
        )


normalizer = SpeechNormalizer()
