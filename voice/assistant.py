"""Continuous Hands-Free Voice Assistant for MAX with Wake Word Detection and Cancellation."""

from enum import Enum
import logging
import os
from pathlib import Path
import time
from typing import Callable, Optional
from rich.console import Console
from rich.panel import Panel

from agent.core import AgentCore
from voice.recorder import record_microphone
from voice.tts import speak_text, stop_speaking, play_earcon
from voice.whisper_stt import transcribe_audio, is_whisper_available
from voice.wake import WakeWordDetector, WakeDetectionResult

logger = logging.getLogger(__name__)


class VoiceState(str, Enum):
    IDLE = "IDLE"
    WAKE_DETECTING = "WAKE_DETECTING"
    CAPTURING = "CAPTURING"
    TRANSCRIBING = "TRANSCRIBING"
    THINKING = "THINKING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    REPLANNING = "REPLANNING"
    SPEAKING = "SPEAKING"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"
    RECOVERING = "RECOVERING"
    DONE = "DONE"


def is_cancel_command(text: str) -> bool:
    """Check if the spoken text represents a cancellation command."""
    cleaned = text.strip().lower()
    cancel_triggers = ["stop", "cancel", "max stop", "max cancel", "abort", "never mind", "quit", "halt"]
    return any(cleaned == t or cleaned.startswith(t + " ") for t in cancel_triggers)


class VoiceAssistant:
    """Continuous voice operator that listens for wake word 'Max', acknowledges,

    and executes arbitrary computer control tasks via AgentCore with full cancellation support.
    """

    def __init__(
        self,
        wake_word: str = "max",
        whisper_model: str = "base.en",
        voice: Optional[str] = None,
        ack_phrase: str = "Yes, I'm listening.",
        earcon_sound: str = "/System/Library/Sounds/Tink.aiff",
        use_earcon_ack: bool = True,
        agent: Optional[AgentCore] = None,
        console: Optional[Console] = None,
    ):
        self.wake_detector = WakeWordDetector(wake_word=wake_word)
        self.whisper_model = whisper_model
        self.voice = voice
        self.ack_phrase = ack_phrase
        self.earcon_sound = earcon_sound
        self.use_earcon_ack = use_earcon_ack
        self.agent = agent or AgentCore()
        self.console = console or Console()
        self.is_running = False
        self.state: VoiceState = VoiceState.IDLE
        self.state_updated_at: float = time.time()

    def set_state(self, new_state: VoiceState) -> None:
        """Thread-safe state transition with timestamp recording."""
        self.state = new_state
        self.state_updated_at = time.time()

    def cancel(self) -> None:
        """Cancel any active task, silence speech, and return to IDLE."""
        self.set_state(VoiceState.CANCELLED)
        if self.agent:
            self.agent.cancel()
        stop_speaking()
        self.console.print("[bold yellow]🛑 Operation cancelled by user.[/bold yellow]")
        self.set_state(VoiceState.IDLE)

    def check_watchdog(self, max_duration_seconds: float = 40.0) -> bool:
        """Check if assistant is stuck in an active state and recover if timed out."""
        if self.state in (VoiceState.IDLE, VoiceState.DONE, VoiceState.CANCELLED):
            return False
        elapsed = time.time() - self.state_updated_at
        if elapsed > max_duration_seconds:
            logger.warning(f"Voice watchdog triggered: stuck in {self.state.value} for {elapsed:.1f}s. Recovering.")
            self.recover_state(f"Watchdog timeout in {self.state.value}")
            return True
        return False

    def recover_state(self, reason: str) -> None:
        """Recover from stuck state without terminating MAX process."""
        self.set_state(VoiceState.RECOVERING)
        if self.agent:
            self.agent.cancel()
        stop_speaking()
        self.console.print(f"[bold red]⚠️ Recovery triggered:[/bold red] {reason}")
        time.sleep(0.1)
        self.set_state(VoiceState.IDLE)

    def listen_and_process_wake_word(self, duration: float = 3.0) -> WakeDetectionResult:
        """Capture a short audio sample and evaluate whether the wake word was spoken."""
        self.set_state(VoiceState.WAKE_DETECTING)
        rec = record_microphone(duration_seconds=duration, vad=True, silence_timeout=0.8)
        if not rec.success or not rec.wav_path:
            self.set_state(VoiceState.IDLE)
            return WakeDetectionResult(detected=False)

        wav_p = Path(rec.wav_path)
        try:
            self.set_state(VoiceState.TRANSCRIBING)
            stt = transcribe_audio(wav_p, model_name=self.whisper_model)
            if not stt.success or not stt.text:
                self.set_state(VoiceState.IDLE)
                return WakeDetectionResult(detected=False)

            detection = self.wake_detector.detect(stt.text)
            return detection
        finally:
            if wav_p.exists():
                try:
                    wav_p.unlink()
                except Exception:
                    pass

    def record_and_transcribe_task(self, max_duration: float = 8.0) -> Optional[str]:
        """Record the user's task prompt using Voice Activity Detection and transcribe it."""
        self.set_state(VoiceState.CAPTURING)
        rec = record_microphone(duration_seconds=max_duration, vad=True, silence_timeout=1.2)
        if not rec.success or not rec.wav_path:
            self.set_state(VoiceState.IDLE)
            return None

        wav_p = Path(rec.wav_path)
        try:
            self.set_state(VoiceState.TRANSCRIBING)
            stt = transcribe_audio(wav_p, model_name=self.whisper_model)
            if not stt.success or not stt.text:
                self.set_state(VoiceState.IDLE)
                return None
            return stt.text.strip()
        finally:
            if wav_p.exists():
                try:
                    wav_p.unlink()
                except Exception:
                    pass

    def execute_task(self, task_instruction: str, speak_summary: bool = True) -> str:
        """Run the task instruction through AgentCore and verbally report the outcome."""
        if is_cancel_command(task_instruction):
            self.cancel()
            return "Cancelled."

        self.set_state(VoiceState.EXECUTING)
        self.console.print(f"\n[bold cyan]▶ Executing Task:[/bold cyan] \"{task_instruction}\"\n")
        report = self.agent.run(task_instruction)

        summary = report.final_summary
        self.console.print(Panel(summary, title="Outcome", border_style="green"))

        if speak_summary and summary and self.state != VoiceState.CANCELLED:
            self.set_state(VoiceState.SPEAKING)
            self.console.print(f"[dim]🗣️ Speaking outcome...[/dim]")
            speak_text(summary, voice=self.voice)

        self.set_state(VoiceState.DONE)
        return summary

    def step(self) -> bool:
        """Execute a single cycle of the voice assistant with cancellation support."""
        self.check_watchdog()

        detection = self.listen_and_process_wake_word(duration=3.0)
        if not detection.detected:
            self.set_state(VoiceState.IDLE)
            return False

        self.console.print(f"\n[bold green]✨ Wake word detected![/bold green] (Spoken: \"{detection.raw_text}\")")

        # Check for immediate cancel
        if detection.inline_task and is_cancel_command(detection.inline_task):
            self.cancel()
            return True

        # Non-blocking acknowledgment cue
        if self.use_earcon_ack:
            play_earcon(self.earcon_sound)
        else:
            if detection.inline_task:
                speak_text("On it.", voice=self.voice)
            else:
                self.console.print(f"[bold yellow]🗣️ Responding:[/bold yellow] \"{self.ack_phrase}\"")
                speak_text(self.ack_phrase, voice=self.voice)

        task_to_run: Optional[str] = None

        if detection.inline_task:
            # One-shot command: e.g. "Max, open Chrome"
            self.console.print(f"[bold cyan]Inline task detected:[/bold cyan] \"{detection.inline_task}\"")
            task_to_run = detection.inline_task
        else:
            # Standalone call: e.g. "Max!"
            self.console.print("[bold green]🎙️  Listening for your task... Speak now![/bold green]")
            task_to_run = self.record_and_transcribe_task(max_duration=8.0)

            if not task_to_run:
                self.console.print("[yellow]No speech detected. Returning to idle.[/yellow]")
                self.set_state(VoiceState.IDLE)
                return True

            if is_cancel_command(task_to_run):
                self.cancel()
                return True

            self.console.print(f"[bold white]You asked:[/bold white] \"{task_to_run}\"")

        self.execute_task(task_to_run)
        self.set_state(VoiceState.IDLE)
        return True

    def run_continuous(self, on_cycle: Optional[Callable[[], None]] = None):
        """Run continuous hands-free assistant loop until interrupted."""
        if not is_whisper_available():
            self.console.print("[bold red]Error: Local Whisper STT is not available.[/bold red]")
            self.console.print("Please install whisper: pip install openai-whisper")
            return

        self.is_running = True
        self.console.print(Panel(
            f"[bold cyan]🎙️  MAX Hands-Free Voice Assistant Active[/bold cyan]\n"
            f"Call [bold white]'{self.wake_detector.primary_name.title()}'[/bold white] or [bold white]'Hey {self.wake_detector.primary_name.title()}'[/bold white] at any time.\n"
            f"Say [bold yellow]'MAX, stop'[/bold yellow] or press [bold red]Ctrl+C[/bold red] to stop.",
            border_style="cyan"
        ))

        try:
            while self.is_running:
                self.console.print("[dim]Listening for wake word...[/dim]", end="\r")
                self.step()
                if on_cycle:
                    on_cycle()
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.console.print("\n\n[bold yellow]Stopping voice assistant. Goodbye![/bold yellow]")
            speak_text("Goodbye!", voice=self.voice)
        finally:
            self.is_running = False
            self.set_state(VoiceState.IDLE)
