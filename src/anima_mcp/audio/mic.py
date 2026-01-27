"""
PDM Microphone capture for Braincraft HAT.

The Braincraft HAT has 2x PDM MEMS microphones for stereo audio input.
This module captures audio and provides it for speech recognition.
"""

import sys
import time
import threading
import queue
from typing import Optional, Callable
from dataclasses import dataclass

# Audio settings for speech recognition
SAMPLE_RATE = 16000  # 16kHz - standard for speech recognition
CHANNELS = 1  # Mono for speech (mix stereo down)
CHUNK_SIZE = 1024  # Samples per chunk


@dataclass
class AudioChunk:
    """A chunk of audio data."""
    data: bytes
    timestamp: float
    duration: float  # seconds


class MicCapture:
    """
    Capture audio from Braincraft HAT PDM microphones.

    Supports:
    - Continuous capture for always-listening mode
    - Push-to-talk style capture
    - Voice activity detection (VAD) for smart listening
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE, channels: int = CHANNELS):
        self._sample_rate = sample_rate
        self._channels = channels
        self._running = False
        self._audio_queue: queue.Queue[AudioChunk] = queue.Queue(maxsize=100)
        self._capture_thread: Optional[threading.Thread] = None
        self._stream = None
        self._audio_interface = None

        # Voice activity detection
        self._vad_enabled = True
        self._silence_threshold = 500  # RMS threshold for silence
        self._speech_timeout = 1.5  # Seconds of silence before stopping

        # Callbacks
        self._on_speech_start: Optional[Callable] = None
        self._on_speech_end: Optional[Callable[[bytes], None]] = None

    def _init_audio(self) -> bool:
        """Initialize audio interface."""
        try:
            import sounddevice as sd

            # Find the PDM mic device
            devices = sd.query_devices()
            mic_device = None

            for i, dev in enumerate(devices):
                name = dev['name'].lower()
                # Look for PDM or USB audio device
                if 'pdm' in name or 'mic' in name or 'input' in name:
                    if dev['max_input_channels'] > 0:
                        mic_device = i
                        break

            if mic_device is None:
                # Fallback to default input
                mic_device = sd.default.device[0]

            print(f"[Mic] Using device {mic_device}: {devices[mic_device]['name']}",
                  file=sys.stderr, flush=True)

            self._audio_interface = sd
            self._device = mic_device
            return True

        except ImportError:
            print("[Mic] sounddevice not installed. Run: pip install sounddevice",
                  file=sys.stderr, flush=True)
            return False
        except Exception as e:
            print(f"[Mic] Failed to init audio: {e}", file=sys.stderr, flush=True)
            return False

    def start(self) -> bool:
        """Start capturing audio."""
        if self._running:
            return True

        if not self._init_audio():
            return False

        self._running = True
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()
        print("[Mic] Started capturing", file=sys.stderr, flush=True)
        return True

    def stop(self):
        """Stop capturing audio."""
        self._running = False
        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
        print("[Mic] Stopped capturing", file=sys.stderr, flush=True)

    def _capture_loop(self):
        """Main capture loop - runs in background thread."""
        import numpy as np
        sd = self._audio_interface

        speech_buffer = []
        in_speech = False
        silence_start = None

        def audio_callback(indata, frames, time_info, status):
            nonlocal speech_buffer, in_speech, silence_start

            if status:
                print(f"[Mic] Status: {status}", file=sys.stderr, flush=True)

            # Convert to mono if stereo
            if indata.shape[1] > 1:
                audio_data = np.mean(indata, axis=1)
            else:
                audio_data = indata[:, 0]

            # Calculate RMS for VAD
            rms = np.sqrt(np.mean(audio_data ** 2)) * 32768

            timestamp = time.time()
            duration = frames / self._sample_rate

            if self._vad_enabled:
                # Voice activity detection
                if rms > self._silence_threshold:
                    # Speech detected
                    if not in_speech:
                        in_speech = True
                        speech_buffer = []
                        if self._on_speech_start:
                            self._on_speech_start()

                    silence_start = None
                    speech_buffer.append(audio_data.copy())

                elif in_speech:
                    # Possible end of speech
                    speech_buffer.append(audio_data.copy())

                    if silence_start is None:
                        silence_start = timestamp
                    elif timestamp - silence_start > self._speech_timeout:
                        # Speech ended
                        in_speech = False
                        if speech_buffer and self._on_speech_end:
                            # Concatenate and convert to bytes
                            full_audio = np.concatenate(speech_buffer)
                            audio_bytes = (full_audio * 32768).astype(np.int16).tobytes()
                            self._on_speech_end(audio_bytes)
                        speech_buffer = []
            else:
                # No VAD - just queue all audio
                audio_bytes = (audio_data * 32768).astype(np.int16).tobytes()
                chunk = AudioChunk(
                    data=audio_bytes,
                    timestamp=timestamp,
                    duration=duration
                )
                try:
                    self._audio_queue.put_nowait(chunk)
                except queue.Full:
                    pass  # Drop oldest if queue full

        try:
            with sd.InputStream(
                device=self._device,
                samplerate=self._sample_rate,
                channels=self._channels,
                blocksize=CHUNK_SIZE,
                callback=audio_callback
            ):
                while self._running:
                    time.sleep(0.1)
        except Exception as e:
            print(f"[Mic] Capture error: {e}", file=sys.stderr, flush=True)
            self._running = False

    def get_chunk(self, timeout: float = 0.1) -> Optional[AudioChunk]:
        """Get next audio chunk from queue."""
        try:
            return self._audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def set_vad_enabled(self, enabled: bool):
        """Enable/disable voice activity detection."""
        self._vad_enabled = enabled

    def set_silence_threshold(self, threshold: int):
        """Set RMS threshold for silence detection."""
        self._silence_threshold = threshold

    def on_speech_start(self, callback: Callable):
        """Set callback for when speech starts."""
        self._on_speech_start = callback

    def on_speech_end(self, callback: Callable[[bytes], None]):
        """Set callback for when speech ends (receives audio bytes)."""
        self._on_speech_end = callback

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def is_running(self) -> bool:
        return self._running
