"""
Speaker output for Braincraft HAT.

The Braincraft HAT has a 3W speaker output for audio playback.
This module handles playing audio through the speaker.
"""

import sys
import time
import threading
import queue
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class AudioPlayback:
    """Audio to play."""
    audio_bytes: bytes
    sample_rate: int = 22050  # Piper default
    channels: int = 1
    sample_width: int = 2  # 16-bit


class Speaker:
    """
    Play audio through Braincraft HAT speaker.

    Supports:
    - Queued playback (non-blocking)
    - Direct playback (blocking)
    - Volume control
    """

    def __init__(self):
        self._audio_queue: queue.Queue[AudioPlayback] = queue.Queue(maxsize=10)
        self._playback_thread: Optional[threading.Thread] = None
        self._running = False
        self._volume = 0.8  # 0.0 - 1.0
        self._audio_interface = None
        self._device = None

    def _init_audio(self) -> bool:
        """Initialize audio output interface."""
        try:
            import sounddevice as sd

            # Find output device
            devices = sd.query_devices()
            output_device = None

            for i, dev in enumerate(devices):
                name = dev['name'].lower()
                # Look for speaker or audio output
                if 'speaker' in name or 'audio' in name or 'output' in name:
                    if dev['max_output_channels'] > 0:
                        output_device = i
                        break

            if output_device is None:
                output_device = sd.default.device[1]

            print(f"[Speaker] Using device {output_device}: {devices[output_device]['name']}",
                  file=sys.stderr, flush=True)

            self._audio_interface = sd
            self._device = output_device
            return True

        except ImportError:
            print("[Speaker] sounddevice not installed. Run: pip install sounddevice",
                  file=sys.stderr, flush=True)
            return False
        except Exception as e:
            print(f"[Speaker] Failed to init audio: {e}", file=sys.stderr, flush=True)
            return False

    def start(self) -> bool:
        """Start the playback thread for queued audio."""
        if self._running:
            return True

        if not self._init_audio():
            return False

        self._running = True
        self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._playback_thread.start()
        print("[Speaker] Started", file=sys.stderr, flush=True)
        return True

    def stop(self):
        """Stop the playback thread."""
        self._running = False
        if self._playback_thread:
            self._playback_thread.join(timeout=2.0)
            self._playback_thread = None
        print("[Speaker] Stopped", file=sys.stderr, flush=True)

    def _playback_loop(self):
        """Main playback loop - plays queued audio."""
        while self._running:
            try:
                playback = self._audio_queue.get(timeout=0.5)
                self._play_audio(playback)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[Speaker] Playback error: {e}", file=sys.stderr, flush=True)

    def _play_audio(self, playback: AudioPlayback):
        """Play audio bytes."""
        import numpy as np
        sd = self._audio_interface

        try:
            # Convert bytes to numpy array
            audio_data = np.frombuffer(playback.audio_bytes, dtype=np.int16)
            audio_float = audio_data.astype(np.float32) / 32768.0

            # Apply volume
            audio_float *= self._volume

            # Play
            sd.play(audio_float, samplerate=playback.sample_rate, device=self._device)
            sd.wait()

        except Exception as e:
            print(f"[Speaker] Play error: {e}", file=sys.stderr, flush=True)

    def play(self, audio_bytes: bytes, sample_rate: int = 22050, blocking: bool = False):
        """
        Play audio.

        Args:
            audio_bytes: Raw PCM audio data (16-bit)
            sample_rate: Sample rate of the audio
            blocking: If True, wait for playback to complete
        """
        playback = AudioPlayback(
            audio_bytes=audio_bytes,
            sample_rate=sample_rate
        )

        if blocking:
            if not self._audio_interface:
                if not self._init_audio():
                    return
            self._play_audio(playback)
        else:
            if not self._running:
                self.start()
            try:
                self._audio_queue.put_nowait(playback)
            except queue.Full:
                print("[Speaker] Queue full, dropping audio", file=sys.stderr, flush=True)

    def play_file(self, path: Path, blocking: bool = False):
        """Play a WAV file."""
        import wave

        try:
            with wave.open(str(path), 'rb') as wav:
                audio_bytes = wav.readframes(wav.getnframes())
                sample_rate = wav.getframerate()

            self.play(audio_bytes, sample_rate, blocking)

        except Exception as e:
            print(f"[Speaker] Failed to play file: {e}", file=sys.stderr, flush=True)

    def speak(self, text: str, tts: 'TextToSpeech', blocking: bool = True):
        """
        Convenience method: synthesize and play text.

        Args:
            text: Text to speak
            tts: TextToSpeech instance to use
            blocking: Wait for speech to complete
        """
        audio_bytes = tts.synthesize(text)
        if audio_bytes:
            self.play(audio_bytes, sample_rate=22050, blocking=blocking)

    def clear_queue(self):
        """Clear any pending audio in the queue."""
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = max(0.0, min(1.0, value))

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def queue_size(self) -> int:
        return self._audio_queue.qsize()
