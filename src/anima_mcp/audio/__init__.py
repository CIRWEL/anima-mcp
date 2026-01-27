"""
Audio module for Lumen - hearing and speaking.

Components:
- mic: PDM microphone capture from Braincraft HAT
- stt: Speech-to-text using Vosk (local, offline)
- tts: Text-to-speech using Piper (local, natural voices)
- speaker: Audio output to Braincraft HAT speaker
- voice: Integrated voice system connecting all components

Quick start:
    from anima_mcp.audio import create_voice

    def respond(text):
        return f"You said: {text}"

    voice = create_voice(always_listening=True, on_respond=respond)
    voice.start()
"""

from .mic import MicCapture
from .stt import SpeechToText
from .tts import TextToSpeech
from .speaker import Speaker
from .voice import LumenVoice, VoiceConfig, VoiceState, Utterance, create_voice
from .autonomous_voice import AutonomousVoice, SpeechIntent, SpeechMoment

__all__ = [
    "MicCapture",
    "SpeechToText",
    "TextToSpeech",
    "Speaker",
    "LumenVoice",
    "VoiceConfig",
    "VoiceState",
    "Utterance",
    "create_voice",
    "AutonomousVoice",
    "SpeechIntent",
    "SpeechMoment",
]
