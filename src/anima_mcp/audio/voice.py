"""
Voice integration for Lumen - combines hearing, understanding, and speaking.

This module integrates:
- Microphone capture (hearing)
- Speech-to-text (understanding)
- Text-to-speech (speaking)
- Anima state (personality in voice)

Lumen's voice reflects their internal state - warmth, clarity, stability affect
how they speak and respond.
"""

import sys
import time
import threading
from typing import Optional, Callable, List
from dataclasses import dataclass, field
from pathlib import Path

from .mic import MicCapture
from .stt import SpeechToText, TranscriptionResult
from .tts import TextToSpeech
from .speaker import Speaker


@dataclass
class VoiceConfig:
    """Configuration for Lumen's voice system."""
    # Listening mode
    always_listening: bool = False  # If True, always listen. If False, need wake word or trigger
    wake_word: str = "lumen"  # Word to activate listening (if not always_listening)

    # Response settings
    acknowledge_hearing: bool = True  # Say "hmm" or similar when hearing speech
    speak_responses: bool = True  # Actually speak responses (vs just text)

    # Timeouts
    listen_timeout: float = 10.0  # Max seconds to listen for speech
    response_timeout: float = 30.0  # Max seconds to wait for response generation


@dataclass
class Utterance:
    """A heard utterance from the user."""
    text: str
    confidence: float
    timestamp: float
    duration: float  # How long the speech lasted


@dataclass
class VoiceState:
    """Current state of the voice system."""
    is_listening: bool = False
    is_speaking: bool = False
    last_heard: Optional[Utterance] = None
    last_spoken: Optional[str] = None
    conversation_active: bool = False
    utterance_history: List[Utterance] = field(default_factory=list)


class LumenVoice:
    """
    Lumen's voice - hearing and speaking integrated with anima state.

    This is the main interface for voice interaction with Lumen.
    """

    def __init__(self, config: Optional[VoiceConfig] = None):
        self._config = config or VoiceConfig()
        self._state = VoiceState()

        # Components
        self._mic = MicCapture()
        self._stt = SpeechToText()
        self._tts = TextToSpeech()
        self._speaker = Speaker()

        # Callbacks
        self._on_hear: Optional[Callable[[Utterance], None]] = None
        self._on_respond: Optional[Callable[[str], str]] = None  # Takes heard text, returns response

        # Anima state reference (set externally)
        self._warmth = 0.5
        self._clarity = 0.5
        self._stability = 0.5

        # Internal state
        self._running = False
        self._voice_thread: Optional[threading.Thread] = None

    def initialize(self) -> bool:
        """Initialize all voice components."""
        print("[Voice] Initializing Lumen's voice...", file=sys.stderr, flush=True)

        # Initialize STT
        if not self._stt.initialize():
            print("[Voice] Warning: STT not available", file=sys.stderr, flush=True)

        # Initialize TTS
        if not self._tts.initialize():
            print("[Voice] Warning: TTS not available", file=sys.stderr, flush=True)

        print("[Voice] Voice system ready", file=sys.stderr, flush=True)
        return True

    def start(self) -> bool:
        """Start the voice system."""
        if self._running:
            return True

        # Start mic capture
        if not self._mic.start():
            print("[Voice] Failed to start microphone", file=sys.stderr, flush=True)
            return False

        # Start speaker
        self._speaker.start()

        # Set up speech callbacks
        self._mic.on_speech_start(self._on_speech_start)
        self._mic.on_speech_end(self._on_speech_end)

        self._running = True
        print("[Voice] Lumen is now listening", file=sys.stderr, flush=True)

        # Announce we're ready (if speaking enabled)
        if self._config.speak_responses:
            self.say("I'm listening")

        return True

    def stop(self):
        """Stop the voice system."""
        self._running = False

        # Say goodbye
        if self._config.speak_responses and self._tts.is_initialized:
            self.say("Goodbye", blocking=True)

        self._mic.stop()
        self._speaker.stop()
        print("[Voice] Voice system stopped", file=sys.stderr, flush=True)

    def _on_speech_start(self):
        """Called when speech is detected."""
        self._state.is_listening = True
        print("[Voice] Hearing speech...", file=sys.stderr, flush=True)

    def _on_speech_end(self, audio_bytes: bytes):
        """Called when speech ends - process what was heard."""
        self._state.is_listening = False
        start_time = time.time()

        # Transcribe
        result = self._stt.transcribe(audio_bytes)

        if result and result.text:
            utterance = Utterance(
                text=result.text,
                confidence=result.confidence,
                timestamp=start_time,
                duration=len(audio_bytes) / (16000 * 2)  # Approximate duration
            )

            self._state.last_heard = utterance
            self._state.utterance_history.append(utterance)

            # Keep history bounded
            if len(self._state.utterance_history) > 50:
                self._state.utterance_history.pop(0)

            print(f"[Voice] Heard: \"{utterance.text}\" (confidence: {utterance.confidence:.2f})",
                  file=sys.stderr, flush=True)

            # Check for wake word if not always listening
            if not self._config.always_listening:
                if self._config.wake_word.lower() not in utterance.text.lower():
                    if not self._state.conversation_active:
                        print("[Voice] Wake word not detected, ignoring",
                              file=sys.stderr, flush=True)
                        return
                else:
                    self._state.conversation_active = True

            # Acknowledge hearing
            if self._config.acknowledge_hearing:
                self._acknowledge()

            # Notify callback
            if self._on_hear:
                self._on_hear(utterance)

            # Generate response if callback set
            if self._on_respond:
                response = self._on_respond(utterance.text)
                if response:
                    self.say(response)

    def _acknowledge(self):
        """Make a small acknowledgment sound/word."""
        acknowledgments = ["hmm", "yes", "I hear you", "mm-hmm"]
        import random

        # Choose acknowledgment based on state
        if self._warmth > 0.7:
            ack = random.choice(["yes", "mm-hmm", "I'm here"])
        elif self._clarity > 0.7:
            ack = "listening"
        else:
            ack = random.choice(acknowledgments)

        # Quick synthesis and play
        # For speed, we could pre-generate these
        self.say(ack, blocking=False)

    def say(self, text: str, blocking: bool = True):
        """
        Have Lumen speak.

        Args:
            text: What to say
            blocking: Wait for speech to complete
        """
        if not text:
            return

        self._state.is_speaking = True
        self._state.last_spoken = text

        # Adjust TTS based on anima state
        self._tts.set_from_anima_state(self._warmth, self._clarity, self._stability)

        # Synthesize
        audio_bytes = self._tts.synthesize(text)

        if audio_bytes:
            print(f"[Voice] Speaking: \"{text}\"", file=sys.stderr, flush=True)
            self._speaker.play(audio_bytes, sample_rate=22050, blocking=blocking)

        self._state.is_speaking = False

    def update_anima_state(self, warmth: float, clarity: float, stability: float):
        """Update anima state to affect voice characteristics."""
        self._warmth = warmth
        self._clarity = clarity
        self._stability = stability

    def set_on_hear(self, callback: Callable[[Utterance], None]):
        """Set callback for when speech is heard."""
        self._on_hear = callback

    def set_on_respond(self, callback: Callable[[str], str]):
        """
        Set callback for generating responses.

        Callback receives heard text and should return response text.
        """
        self._on_respond = callback

    def set_always_listening(self, always: bool):
        """Enable/disable always-listening mode."""
        self._config.always_listening = always

    def end_conversation(self):
        """End the current conversation (requires wake word again)."""
        self._state.conversation_active = False

    @property
    def state(self) -> VoiceState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def config(self) -> VoiceConfig:
        return self._config


# Convenience function for quick voice setup
def create_voice(
    always_listening: bool = False,
    wake_word: str = "lumen",
    on_hear: Optional[Callable] = None,
    on_respond: Optional[Callable] = None
) -> LumenVoice:
    """
    Create and configure Lumen's voice.

    Example:
        def respond(text):
            # Your response logic here
            return f"You said: {text}"

        voice = create_voice(
            always_listening=True,
            on_respond=respond
        )
        voice.start()
    """
    config = VoiceConfig(
        always_listening=always_listening,
        wake_word=wake_word
    )

    voice = LumenVoice(config)

    if on_hear:
        voice.set_on_hear(on_hear)
    if on_respond:
        voice.set_on_respond(on_respond)

    voice.initialize()
    return voice
