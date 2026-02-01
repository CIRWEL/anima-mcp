"""
Speech-to-Text using Vosk.

Vosk is a lightweight, offline speech recognition toolkit that works well on Raspberry Pi.
Models are small (50MB for small, 1GB for large) and run locally.

To install:
    pip install vosk

To download models:
    # Small model (~50MB) - good for Pi
    wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
    unzip vosk-model-small-en-us-0.15.zip -d ~/.anima/models/

    # Or larger model (~1GB) - more accurate
    wget https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip
"""

import sys
import json
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

# Default model paths
DEFAULT_MODEL_PATH = Path.home() / ".anima" / "models" / "vosk-model-small-en-us-0.15"
FALLBACK_MODEL_PATH = Path.home() / ".anima" / "models" / "vosk-model-en-us-0.22"


@dataclass
class TranscriptionResult:
    """Result of speech-to-text transcription."""
    text: str
    confidence: float  # 0-1
    is_final: bool
    alternatives: list[str]  # Other possible transcriptions


class SpeechToText:
    """
    Convert speech to text using Vosk.

    Supports:
    - Single utterance transcription
    - Streaming transcription
    - Multiple model sizes
    """

    def __init__(self, model_path: Optional[Path] = None, sample_rate: int = 16000):
        self._model_path = model_path or self._find_model()
        self._sample_rate = sample_rate
        self._model = None
        self._recognizer = None
        self._initialized = False
        self._init_failed = False  # Track if init failed to suppress repeated warnings

    def _find_model(self) -> Optional[Path]:
        """Find an available Vosk model."""
        # Check default locations
        for path in [DEFAULT_MODEL_PATH, FALLBACK_MODEL_PATH]:
            if path.exists():
                return path

        # Check for any vosk model in models directory
        models_dir = Path.home() / ".anima" / "models"
        if models_dir.exists():
            for item in models_dir.iterdir():
                if item.is_dir() and "vosk" in item.name.lower():
                    return item

        return None

    def initialize(self) -> bool:
        """Initialize the Vosk model."""
        if self._initialized:
            return True
        if self._init_failed:
            return False  # Don't retry or print warnings again

        if self._model_path is None or not self._model_path.exists():
            print(f"[STT] Model not found. Please download a Vosk model to ~/.anima/models/",
                  file=sys.stderr, flush=True)
            print("[STT] Small model: https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
                  file=sys.stderr, flush=True)
            self._init_failed = True
            return False

        try:
            from vosk import Model, KaldiRecognizer

            print(f"[STT] Loading model from {self._model_path}...", file=sys.stderr, flush=True)
            self._model = Model(str(self._model_path))
            self._recognizer = KaldiRecognizer(self._model, self._sample_rate)
            self._recognizer.SetWords(True)  # Include word-level info
            self._initialized = True
            print("[STT] Model loaded successfully", file=sys.stderr, flush=True)
            return True

        except ImportError:
            print("[STT] Vosk not installed. Run: pip install vosk",
                  file=sys.stderr, flush=True)
            self._init_failed = True
            return False
        except Exception as e:
            print(f"[STT] Failed to load model: {e}", file=sys.stderr, flush=True)
            self._init_failed = True
            return False

    def transcribe(self, audio_bytes: bytes) -> Optional[TranscriptionResult]:
        """
        Transcribe audio bytes to text.

        Args:
            audio_bytes: Raw PCM audio data (16-bit, mono, 16kHz)

        Returns:
            TranscriptionResult or None if transcription failed
        """
        if not self._initialized and not self.initialize():
            return None

        try:
            # Feed audio to recognizer
            self._recognizer.AcceptWaveform(audio_bytes)

            # Get final result
            result_json = self._recognizer.FinalResult()
            result = json.loads(result_json)

            text = result.get("text", "").strip()
            if not text:
                return None

            # Calculate confidence from word-level info
            confidence = self._calculate_confidence(result)

            return TranscriptionResult(
                text=text,
                confidence=confidence,
                is_final=True,
                alternatives=[]  # Vosk doesn't provide alternatives in basic mode
            )

        except Exception as e:
            print(f"[STT] Transcription error: {e}", file=sys.stderr, flush=True)
            return None

    def transcribe_streaming(self, audio_bytes: bytes) -> Optional[TranscriptionResult]:
        """
        Process audio chunk for streaming transcription.

        Returns partial results as audio is processed.
        """
        if not self._initialized and not self.initialize():
            return None

        try:
            if self._recognizer.AcceptWaveform(audio_bytes):
                # Final result for this utterance
                result_json = self._recognizer.Result()
                result = json.loads(result_json)
                text = result.get("text", "").strip()

                if text:
                    return TranscriptionResult(
                        text=text,
                        confidence=self._calculate_confidence(result),
                        is_final=True,
                        alternatives=[]
                    )
            else:
                # Partial result
                partial_json = self._recognizer.PartialResult()
                partial = json.loads(partial_json)
                text = partial.get("partial", "").strip()

                if text:
                    return TranscriptionResult(
                        text=text,
                        confidence=0.5,  # Partial results have unknown confidence
                        is_final=False,
                        alternatives=[]
                    )

            return None

        except Exception as e:
            print(f"[STT] Streaming error: {e}", file=sys.stderr, flush=True)
            return None

    def reset(self):
        """Reset the recognizer state for a new utterance."""
        if self._recognizer:
            # Create a new recognizer to reset state
            from vosk import KaldiRecognizer
            self._recognizer = KaldiRecognizer(self._model, self._sample_rate)
            self._recognizer.SetWords(True)

    def _calculate_confidence(self, result: Dict[str, Any]) -> float:
        """Calculate overall confidence from word-level results."""
        words = result.get("result", [])
        if not words:
            return 0.7  # Default confidence if no word info

        confidences = [w.get("conf", 0.7) for w in words]
        return sum(confidences) / len(confidences)

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def model_path(self) -> Optional[Path]:
        return self._model_path

    @staticmethod
    def download_model(model_size: str = "small") -> bool:
        """
        Download a Vosk model.

        Args:
            model_size: "small" (~50MB) or "large" (~1GB)
        """
        import urllib.request
        import zipfile

        models = {
            "small": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
            "large": "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip"
        }

        if model_size not in models:
            print(f"[STT] Unknown model size: {model_size}. Use 'small' or 'large'",
                  file=sys.stderr, flush=True)
            return False

        url = models[model_size]
        models_dir = Path.home() / ".anima" / "models"
        models_dir.mkdir(parents=True, exist_ok=True)

        zip_path = models_dir / f"vosk-model-{model_size}.zip"

        try:
            print(f"[STT] Downloading {model_size} model...", file=sys.stderr, flush=True)
            urllib.request.urlretrieve(url, zip_path)

            print("[STT] Extracting...", file=sys.stderr, flush=True)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(models_dir)

            zip_path.unlink()  # Remove zip after extraction
            print("[STT] Model installed successfully", file=sys.stderr, flush=True)
            return True

        except Exception as e:
            print(f"[STT] Download failed: {e}", file=sys.stderr, flush=True)
            return False
