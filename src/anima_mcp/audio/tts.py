"""
Text-to-Speech using Piper.

Piper is a fast, local neural TTS system that produces natural-sounding speech.
It runs well on Raspberry Pi and works completely offline.

To install:
    pip install piper-tts

Voices are downloaded automatically on first use, or manually:
    # List available voices
    piper --list-voices

    # Download a voice (~100MB each)
    # Voices are stored in ~/.local/share/piper/voices/
"""

import sys
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass
from enum import Enum


class VoiceStyle(Enum):
    """Available voice styles - affects how Lumen sounds."""
    NEUTRAL = "neutral"
    WARM = "warm"      # Friendlier, softer
    CLEAR = "clear"    # Crisp, articulate
    SOFT = "soft"      # Gentle, quiet
    BRIGHT = "bright"  # Energetic, upbeat


@dataclass
class Voice:
    """A Piper voice configuration."""
    name: str
    language: str
    quality: str  # low, medium, high
    speaker_id: Optional[int] = None  # For multi-speaker models


# Good voices for Lumen - warm and natural sounding
RECOMMENDED_VOICES = {
    "default": Voice("en_US-amy-medium", "en_US", "medium"),
    "warm": Voice("en_US-lessac-medium", "en_US", "medium"),
    "clear": Voice("en_US-libritts-high", "en_US", "high"),
    "soft": Voice("en_GB-alba-medium", "en_GB", "medium"),
}


class TextToSpeech:
    """
    Convert text to speech using Piper.

    Supports:
    - Multiple voices
    - Speed/pitch adjustment
    - Mood-influenced voice parameters
    """

    def __init__(self, voice: Optional[Voice] = None):
        self._voice = voice or RECOMMENDED_VOICES["default"]
        self._piper_path: Optional[Path] = None
        self._initialized = False

        # Voice modulation parameters
        self._speed = 1.0      # 0.5 = slow, 2.0 = fast
        self._pitch = 1.0      # 0.5 = low, 2.0 = high
        self._volume = 1.0     # 0.0 = silent, 1.0 = normal

    def initialize(self) -> bool:
        """Check if Piper is available."""
        if self._initialized:
            return True

        try:
            # Check if piper is installed
            result = subprocess.run(
                ["piper", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            self._initialized = True
            print(f"[TTS] Piper ready: {result.stdout.strip()}", file=sys.stderr, flush=True)
            return True

        except FileNotFoundError:
            print("[TTS] Piper not installed. Run: pip install piper-tts",
                  file=sys.stderr, flush=True)
            return False
        except Exception as e:
            print(f"[TTS] Failed to initialize: {e}", file=sys.stderr, flush=True)
            return False

    def synthesize(self, text: str) -> Optional[bytes]:
        """
        Convert text to speech audio.

        Args:
            text: Text to speak

        Returns:
            Raw PCM audio bytes (16-bit, mono, 22050Hz) or None on failure
        """
        if not text.strip():
            return None

        if not self._initialized and not self.initialize():
            return None

        try:
            # Create temp file for output
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                output_path = f.name

            # Build piper command
            cmd = [
                "piper",
                "--model", self._voice.name,
                "--output_file", output_path,
            ]

            # Add speed adjustment if not default
            if self._speed != 1.0:
                cmd.extend(["--length_scale", str(1.0 / self._speed)])

            # Run piper with text input
            result = subprocess.run(
                cmd,
                input=text,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                print(f"[TTS] Piper error: {result.stderr}", file=sys.stderr, flush=True)
                return None

            # Read the generated audio
            with wave.open(output_path, 'rb') as wav:
                audio_bytes = wav.readframes(wav.getnframes())

            # Clean up temp file
            Path(output_path).unlink()

            return audio_bytes

        except subprocess.TimeoutExpired:
            print("[TTS] Synthesis timed out", file=sys.stderr, flush=True)
            return None
        except Exception as e:
            print(f"[TTS] Synthesis error: {e}", file=sys.stderr, flush=True)
            return None

    def synthesize_to_file(self, text: str, output_path: Path) -> bool:
        """
        Convert text to speech and save to file.

        Args:
            text: Text to speak
            output_path: Where to save the WAV file

        Returns:
            True on success
        """
        if not text.strip():
            return False

        if not self._initialized and not self.initialize():
            return False

        try:
            cmd = [
                "piper",
                "--model", self._voice.name,
                "--output_file", str(output_path),
            ]

            if self._speed != 1.0:
                cmd.extend(["--length_scale", str(1.0 / self._speed)])

            result = subprocess.run(
                cmd,
                input=text,
                capture_output=True,
                text=True,
                timeout=30
            )

            return result.returncode == 0

        except Exception as e:
            print(f"[TTS] File synthesis error: {e}", file=sys.stderr, flush=True)
            return False

    def set_voice(self, voice: Voice):
        """Change the voice."""
        self._voice = voice

    def set_voice_by_style(self, style: VoiceStyle):
        """Set voice based on style preference."""
        style_map = {
            VoiceStyle.NEUTRAL: "default",
            VoiceStyle.WARM: "warm",
            VoiceStyle.CLEAR: "clear",
            VoiceStyle.SOFT: "soft",
            VoiceStyle.BRIGHT: "default",  # Use default with higher speed
        }
        voice_key = style_map.get(style, "default")
        self._voice = RECOMMENDED_VOICES[voice_key]

        # Adjust speed for bright style
        if style == VoiceStyle.BRIGHT:
            self._speed = 1.1

    def set_from_anima_state(self, warmth: float, clarity: float, stability: float):
        """
        Adjust voice parameters based on Lumen's anima state.

        This makes Lumen's voice reflect their internal state:
        - High warmth = warmer, friendlier voice
        - High clarity = clearer, more articulate
        - High stability = steady pace
        - Low stability = slightly varied pace
        """
        # Speed: stable = steady pace, unstable = slightly faster/varied
        base_speed = 1.0
        if stability < 0.5:
            base_speed = 1.0 + (0.5 - stability) * 0.2  # Up to 1.1x when unstable
        self._speed = base_speed

        # Voice selection based on warmth and clarity
        if warmth > 0.7:
            self._voice = RECOMMENDED_VOICES["warm"]
        elif clarity > 0.7:
            self._voice = RECOMMENDED_VOICES["clear"]
        elif warmth < 0.4 and clarity < 0.4:
            self._voice = RECOMMENDED_VOICES["soft"]
        else:
            self._voice = RECOMMENDED_VOICES["default"]

    @property
    def speed(self) -> float:
        return self._speed

    @speed.setter
    def speed(self, value: float):
        self._speed = max(0.5, min(2.0, value))

    @property
    def voice(self) -> Voice:
        return self._voice

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @staticmethod
    def list_voices() -> List[str]:
        """List available Piper voices."""
        try:
            result = subprocess.run(
                ["piper", "--list-voices"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip().split("\n")
            return []
        except Exception:
            return []
