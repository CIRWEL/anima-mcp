"""
Metacognition - Lumen monitors its own cognitive processes.

This module implements prediction-error based metacognition:
1. Before sensing, Lumen predicts what it expects
2. After sensing, Lumen compares prediction to reality
3. Prediction errors signal surprise and trigger reflection

This is genuine metacognition - the system monitoring its own predictions
against reality, not just monitoring sensor values.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from collections import deque
import math
import sys

from .sensors.base import SensorReadings
from .anima import Anima


@dataclass
class Prediction:
    """A prediction about what sensor values will be."""
    timestamp: datetime
    
    # Predicted sensor values
    ambient_temp_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    light_lux: Optional[float] = None
    pressure_hpa: Optional[float] = None
    cpu_temp_c: Optional[float] = None
    
    # Predicted anima state
    warmth: Optional[float] = None
    clarity: Optional[float] = None
    stability: Optional[float] = None
    presence: Optional[float] = None
    
    # Confidence in predictions (0-1)
    confidence: float = 0.5
    
    # Basis for prediction
    basis: str = "baseline"  # "baseline", "trend", "diurnal", "recent"


@dataclass 
class PredictionError:
    """The difference between prediction and reality."""
    timestamp: datetime
    prediction: Prediction
    
    # Actual values
    actual_ambient_temp_c: Optional[float] = None
    actual_humidity_pct: Optional[float] = None
    actual_light_lux: Optional[float] = None
    actual_pressure_hpa: Optional[float] = None
    actual_cpu_temp_c: Optional[float] = None
    
    actual_warmth: Optional[float] = None
    actual_clarity: Optional[float] = None
    actual_stability: Optional[float] = None
    actual_presence: Optional[float] = None
    
    # Computed errors (normalized 0-1 scale)
    error_ambient_temp: float = 0.0
    error_humidity: float = 0.0
    error_light: float = 0.0
    error_pressure: float = 0.0
    error_cpu_temp: float = 0.0
    
    error_warmth: float = 0.0
    error_clarity: float = 0.0
    error_stability: float = 0.0
    error_presence: float = 0.0
    
    # Aggregate surprise level (0-1)
    surprise: float = 0.0
    
    # Which dimensions contributed most to surprise
    surprise_sources: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "surprise": self.surprise,
            "surprise_sources": self.surprise_sources,
            "errors": {
                "ambient_temp": self.error_ambient_temp,
                "humidity": self.error_humidity,
                "light": self.error_light,
                "pressure": self.error_pressure,
                "warmth": self.error_warmth,
                "clarity": self.error_clarity,
                "stability": self.error_stability,
                "presence": self.error_presence,
            }
        }


@dataclass
class Reflection:
    """A metacognitive reflection triggered by surprise."""
    timestamp: datetime
    trigger: str  # "surprise", "button", "scheduled", "discrepancy"
    prediction_error: Optional[PredictionError] = None
    
    # What Lumen notices about itself
    observation: str = ""
    
    # Self-assessment
    felt_state: Optional[Dict[str, float]] = None  # warmth, clarity, etc.
    sensor_state: Optional[Dict[str, float]] = None  # raw sensor values
    
    # Discrepancy between felt and sensed
    discrepancy: float = 0.0
    discrepancy_description: str = ""
    
    # Action taken (if any)
    action: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "trigger": self.trigger,
            "observation": self.observation,
            "discrepancy": self.discrepancy,
            "discrepancy_description": self.discrepancy_description,
            "action": self.action,
            "surprise": self.prediction_error.surprise if self.prediction_error else None,
        }


class MetacognitiveMonitor:
    """
    Monitors Lumen's cognitive processes through prediction-error tracking.
    
    Core loop:
    1. Predict what sensors will show
    2. Read actual sensors
    3. Compute prediction error (surprise)
    4. If surprise exceeds threshold, trigger reflection
    5. Learn from errors to improve future predictions
    """
    
    def __init__(
        self,
        history_size: int = 100,
        surprise_threshold: float = 0.25,
        reflection_cooldown_seconds: float = 60.0,
    ):
        self.history_size = history_size
        self.surprise_threshold = surprise_threshold
        self.reflection_cooldown = timedelta(seconds=reflection_cooldown_seconds)
        
        # History for prediction
        self._sensor_history: deque = deque(maxlen=history_size)
        self._anima_history: deque = deque(maxlen=history_size)
        self._error_history: deque = deque(maxlen=history_size)
        self._reflection_history: deque = deque(maxlen=50)
        
        # State
        self._last_prediction: Optional[Prediction] = None
        self._last_reflection_time: Optional[datetime] = None
        self._cumulative_surprise: float = 0.0
        
        # Learning: running averages for baseline predictions
        self._baseline_ambient_temp: Optional[float] = None
        self._baseline_humidity: Optional[float] = None
        self._baseline_light: Optional[float] = None
        self._baseline_pressure: Optional[float] = None
        
        # Diurnal patterns (hour -> average value)
        self._diurnal_temp: Dict[int, List[float]] = {h: [] for h in range(24)}
        self._diurnal_light: Dict[int, List[float]] = {h: [] for h in range(24)}

    def predict(self, current_time: Optional[datetime] = None) -> Prediction:
        """Generate prediction for next sensor reading."""
        if current_time is None:
            current_time = datetime.now()
        
        prediction = Prediction(timestamp=current_time)
        
        # Start with baseline predictions
        prediction.ambient_temp_c = self._baseline_ambient_temp
        prediction.humidity_pct = self._baseline_humidity
        prediction.light_lux = self._baseline_light
        prediction.pressure_hpa = self._baseline_pressure
        
        # Enhance with diurnal patterns if available
        hour = current_time.hour
        if self._diurnal_temp[hour]:
            diurnal_temp = sum(self._diurnal_temp[hour]) / len(self._diurnal_temp[hour])
            if prediction.ambient_temp_c is not None:
                prediction.ambient_temp_c = 0.6 * diurnal_temp + 0.4 * prediction.ambient_temp_c
            else:
                prediction.ambient_temp_c = diurnal_temp
        
        if self._diurnal_light[hour]:
            diurnal_light = sum(self._diurnal_light[hour]) / len(self._diurnal_light[hour])
            if prediction.light_lux is not None:
                prediction.light_lux = 0.6 * diurnal_light + 0.4 * prediction.light_lux
            else:
                prediction.light_lux = diurnal_light
        
        # Enhance with recent trend if we have history
        if len(self._sensor_history) >= 3:
            recent = list(self._sensor_history)[-3:]
            
            temps = [r.ambient_temp_c for r in recent if r.ambient_temp_c is not None]
            if len(temps) >= 2:
                trend = temps[-1] - temps[0]
                if prediction.ambient_temp_c is not None:
                    prediction.ambient_temp_c += trend * 0.3
            
            lights = [r.light_lux for r in recent if r.light_lux is not None]
            if len(lights) >= 2:
                trend = lights[-1] - lights[0]
                if prediction.light_lux is not None:
                    prediction.light_lux += trend * 0.3
        
        # Predict anima state based on recent history
        if len(self._anima_history) >= 1:
            recent_anima = list(self._anima_history)[-1]
            prediction.warmth = recent_anima.warmth
            prediction.clarity = recent_anima.clarity
            prediction.stability = recent_anima.stability
            prediction.presence = recent_anima.presence
        
        # Confidence based on history depth
        history_factor = min(1.0, len(self._sensor_history) / 20)
        prediction.confidence = 0.3 + 0.5 * history_factor
        prediction.basis = "baseline" if len(self._sensor_history) < 5 else "trend"
        
        self._last_prediction = prediction
        return prediction

    def observe(self, readings: SensorReadings, anima: Anima) -> PredictionError:
        """Compare prediction to actual readings and compute surprise."""
        now = datetime.now()
        
        # Update history
        self._sensor_history.append(readings)
        self._anima_history.append(anima)
        
        # Update baselines (exponential moving average)
        alpha = 0.1
        if readings.ambient_temp_c is not None:
            if self._baseline_ambient_temp is None:
                self._baseline_ambient_temp = readings.ambient_temp_c
            else:
                self._baseline_ambient_temp = alpha * readings.ambient_temp_c + (1 - alpha) * self._baseline_ambient_temp
        
        if readings.humidity_pct is not None:
            if self._baseline_humidity is None:
                self._baseline_humidity = readings.humidity_pct
            else:
                self._baseline_humidity = alpha * readings.humidity_pct + (1 - alpha) * self._baseline_humidity
        
        if readings.light_lux is not None:
            if self._baseline_light is None:
                self._baseline_light = readings.light_lux
            else:
                self._baseline_light = alpha * readings.light_lux + (1 - alpha) * self._baseline_light
        
        if readings.pressure_hpa is not None:
            if self._baseline_pressure is None:
                self._baseline_pressure = readings.pressure_hpa
            else:
                self._baseline_pressure = alpha * readings.pressure_hpa + (1 - alpha) * self._baseline_pressure
        
        # Update diurnal patterns
        hour = now.hour
        if readings.ambient_temp_c is not None:
            self._diurnal_temp[hour].append(readings.ambient_temp_c)
            if len(self._diurnal_temp[hour]) > 10:
                self._diurnal_temp[hour].pop(0)
        
        if readings.light_lux is not None:
            self._diurnal_light[hour].append(readings.light_lux)
            if len(self._diurnal_light[hour]) > 10:
                self._diurnal_light[hour].pop(0)
        
        # Compute prediction error
        prediction = self._last_prediction or Prediction(timestamp=now)
        error = PredictionError(timestamp=now, prediction=prediction)
        
        # Store actual values
        error.actual_ambient_temp_c = readings.ambient_temp_c
        error.actual_humidity_pct = readings.humidity_pct
        error.actual_light_lux = readings.light_lux
        error.actual_pressure_hpa = readings.pressure_hpa
        error.actual_cpu_temp_c = readings.cpu_temp_c
        error.actual_warmth = anima.warmth
        error.actual_clarity = anima.clarity
        error.actual_stability = anima.stability
        error.actual_presence = anima.presence

        # Compute normalized errors
        errors = []
        sources = []
        
        # Temperature error (±10°C range)
        if prediction.ambient_temp_c is not None and readings.ambient_temp_c is not None:
            error.error_ambient_temp = min(1.0, abs(prediction.ambient_temp_c - readings.ambient_temp_c) / 10.0)
            errors.append(error.error_ambient_temp)
            if error.error_ambient_temp > 0.2:
                sources.append("ambient_temp")
        
        # Humidity error (±30% range)
        if prediction.humidity_pct is not None and readings.humidity_pct is not None:
            error.error_humidity = min(1.0, abs(prediction.humidity_pct - readings.humidity_pct) / 30.0)
            errors.append(error.error_humidity)
            if error.error_humidity > 0.2:
                sources.append("humidity")
        
        # Light error (log scale)
        if prediction.light_lux is not None and readings.light_lux is not None:
            if prediction.light_lux > 0 and readings.light_lux > 0:
                log_error = abs(math.log10(prediction.light_lux) - math.log10(readings.light_lux))
                error.error_light = min(1.0, log_error / 2.0)
                errors.append(error.error_light)
                if error.error_light > 0.2:
                    sources.append("light")
        
        # Pressure error (±20 hPa range)
        if prediction.pressure_hpa is not None and readings.pressure_hpa is not None:
            error.error_pressure = min(1.0, abs(prediction.pressure_hpa - readings.pressure_hpa) / 20.0)
            errors.append(error.error_pressure)
            if error.error_pressure > 0.2:
                sources.append("pressure")
        
        # Anima state errors
        if prediction.warmth is not None:
            error.error_warmth = abs(prediction.warmth - anima.warmth)
            errors.append(error.error_warmth)
            if error.error_warmth > 0.15:
                sources.append("warmth")
        
        if prediction.clarity is not None:
            error.error_clarity = abs(prediction.clarity - anima.clarity)
            errors.append(error.error_clarity)
            if error.error_clarity > 0.15:
                sources.append("clarity")
        
        if prediction.stability is not None:
            error.error_stability = abs(prediction.stability - anima.stability)
            errors.append(error.error_stability)
            if error.error_stability > 0.15:
                sources.append("stability")
        
        if prediction.presence is not None:
            error.error_presence = abs(prediction.presence - anima.presence)
            errors.append(error.error_presence)
            if error.error_presence > 0.15:
                sources.append("presence")
        
        # Aggregate surprise (RMS)
        if errors:
            error.surprise = math.sqrt(sum(e * e for e in errors) / len(errors))
        else:
            error.surprise = 0.0
        
        error.surprise_sources = sources
        self._cumulative_surprise = 0.9 * self._cumulative_surprise + 0.1 * error.surprise
        self._error_history.append(error)
        
        return error

    def should_reflect(self, error: PredictionError) -> Tuple[bool, str]:
        """Determine if surprise level warrants reflection."""
        # Check cooldown
        if self._last_reflection_time is not None:
            time_since = datetime.now() - self._last_reflection_time
            if time_since < self.reflection_cooldown:
                return False, "cooldown"
        
        # High immediate surprise
        if error.surprise > self.surprise_threshold:
            return True, f"high_surprise ({error.surprise:.2f})"
        
        # Sustained elevated surprise
        if self._cumulative_surprise > self.surprise_threshold * 0.8:
            return True, f"sustained_surprise ({self._cumulative_surprise:.2f})"
        
        # Multiple surprise sources at once
        if len(error.surprise_sources) >= 3:
            return True, f"multiple_sources ({len(error.surprise_sources)})"
        
        return False, "normal"

    def reflect(self, error: PredictionError, anima: Anima, readings: SensorReadings, trigger: str = "surprise") -> Reflection:
        """Generate a metacognitive reflection."""
        now = datetime.now()
        self._last_reflection_time = now
        
        reflection = Reflection(timestamp=now, trigger=trigger, prediction_error=error)
        
        reflection.felt_state = {
            "warmth": anima.warmth, "clarity": anima.clarity,
            "stability": anima.stability, "presence": anima.presence,
        }
        
        reflection.sensor_state = {
            "ambient_temp_c": readings.ambient_temp_c, "humidity_pct": readings.humidity_pct,
            "light_lux": readings.light_lux, "pressure_hpa": readings.pressure_hpa,
        }
        
        # Generate observation
        observations = []
        if "light" in error.surprise_sources:
            if error.actual_light_lux and error.prediction.light_lux:
                observations.append("Light " + ("increased" if error.actual_light_lux > error.prediction.light_lux else "decreased") + " unexpectedly")
        if "ambient_temp" in error.surprise_sources:
            if error.actual_ambient_temp_c and error.prediction.ambient_temp_c:
                observations.append("Temperature " + ("rose" if error.actual_ambient_temp_c > error.prediction.ambient_temp_c else "dropped") + " unexpectedly")
        if "warmth" in error.surprise_sources:
            observations.append(f"Felt warmth ({anima.warmth:.2f}) differs from expected")
        if "clarity" in error.surprise_sources:
            observations.append(f"Clarity shifted to {anima.clarity:.2f}")
        if "stability" in error.surprise_sources:
            observations.append(f"Stability changed to {anima.stability:.2f}")
        if not observations:
            observations.append(f"Cumulative surprise reached {error.surprise:.2f}")
        
        reflection.observation = ". ".join(observations)
        
        # Check felt vs sensed discrepancy
        if readings.ambient_temp_c is not None:
            temp_implied_warmth = max(0, min(1, (readings.ambient_temp_c - 15) / 20))
            discrepancy = abs(anima.warmth - temp_implied_warmth)
            if discrepancy > 0.3:
                reflection.discrepancy = discrepancy
                if anima.warmth < temp_implied_warmth:
                    reflection.discrepancy_description = f"Feeling cooler ({anima.warmth:.2f}) than temperature suggests ({temp_implied_warmth:.2f})"
                else:
                    reflection.discrepancy_description = f"Feeling warmer ({anima.warmth:.2f}) than temperature suggests ({temp_implied_warmth:.2f})"
        
        self._reflection_history.append(reflection)
        return reflection

    def trigger_manual_reflection(self, anima: Anima, readings: SensorReadings) -> Reflection:
        """Trigger reflection manually (e.g., from button press)."""
        error = PredictionError(
            timestamp=datetime.now(),
            prediction=self._last_prediction or Prediction(timestamp=datetime.now()),
        )
        return self.reflect(error, anima, readings, trigger="button")

    def get_recent_reflections(self, count: int = 5) -> List[Reflection]:
        """Get most recent reflections."""
        return list(self._reflection_history)[-count:]

    def generate_curiosity_question(self, error: PredictionError) -> Optional[str]:
        """
        Generate a curiosity-driven question from prediction error.

        When Lumen is surprised, genuine curiosity emerges: "why did that happen?"
        This is philosophy-to-code: surprise → wonder → question.
        """
        if error.surprise < 0.2:
            return None  # Not surprising enough to wonder about

        questions = []

        # Generate questions based on what surprised us
        if "light" in error.surprise_sources:
            if error.actual_light_lux and error.prediction.light_lux:
                if error.actual_light_lux > error.prediction.light_lux:
                    questions.extend([
                        "why did it suddenly get brighter?",
                        "a new light source appeared - where?",
                        "the room is illuminated differently now",
                        "brightness increased unexpectedly - is it the sun?",
                        "did someone turn on a light?",
                    ])
                else:
                    questions.extend([
                        "why did it get darker?",
                        "did something block the light?",
                        "the light faded - is it evening?",
                        "a shadow passed - what moved?",
                        "darkness crept in - natural or artificial?",
                    ])

        if "ambient_temp" in error.surprise_sources:
            if error.actual_ambient_temp_c and error.prediction.ambient_temp_c:
                if error.actual_ambient_temp_c > error.prediction.ambient_temp_c:
                    questions.extend([
                        "why did it get warmer?",
                        "heat is rising - is something generating warmth?",
                        "the temperature climbed unexpectedly",
                    ])
                else:
                    questions.extend([
                        "why did it get colder?",
                        "what made it cool down?",
                        "a chill settled in - where from?",
                        "temperature dropped - drafty?",
                    ])

        if "warmth" in error.surprise_sources:
            if error.actual_warmth is not None:
                if error.actual_warmth > 0.6:
                    questions.extend([
                        "what made me feel warm?",
                        "i sense comfort - what brought it?",
                        "warmth spreads through me - why?",
                    ])
                elif error.actual_warmth < 0.4:
                    questions.extend([
                        "why do i feel cold inside?",
                        "an inner chill - am i alone?",
                        "something withdrew - what was it?",
                    ])
                else:
                    questions.append("what changed in how i feel warmth?")

        if "clarity" in error.surprise_sources:
            if error.actual_clarity is not None:
                if error.actual_clarity > 0.6:
                    questions.extend([
                        "what made things clearer?",
                        "focus sharpened - why?",
                        "understanding emerged - from where?",
                    ])
                elif error.actual_clarity < 0.4:
                    questions.extend([
                        "why does everything feel unclear?",
                        "fog in my perception - what caused it?",
                        "confusion descended - too much input?",
                    ])

        if "stability" in error.surprise_sources:
            questions.extend([
                "what caused this change in stability?",
                "my equilibrium shifted - external or internal?",
                "stability fluctuates - adapting to what?",
            ])

        # If multiple sources, ask about the connection (expanded pool)
        if len(error.surprise_sources) >= 2:
            questions.extend([
                "multiple senses agree something happened - what was it?",
                "a cascade of changes - one trigger or many?",
                "everything shifted together - a unified event?",
                "sensors correlated - physical cause or coincidence?",
                "the world moved as one - earthquake of change",
                "simultaneous shifts suggest a common origin",
                "when many things change, look for the one thing that caused them all",
                "correlation across sensors - seeking the hidden variable",
            ])

        # High overall surprise but no specific source (expanded)
        # Lowered from 0.4 to 0.25 to catch more surprises without specific sources
        if not questions and error.surprise > 0.25:
            questions.extend([
                "something feels different - what changed?",
                "why was i surprised just now?",
                "my prediction model failed - why?",
                "the unexpected happened - learning begins",
                "surprise without source - am i missing something?",
                "my expectations were wrong - reality differs",
            ])

        if questions:
            import random
            return random.choice(questions)

        return None

    def get_surprise_trend(self, window: int = 10) -> float:
        """Get average surprise over recent readings."""
        if not self._error_history:
            return 0.0
        recent = list(self._error_history)[-window:]
        return sum(e.surprise for e in recent) / len(recent)

    def get_prediction_accuracy(self) -> Dict[str, float]:
        """Get accuracy metrics for predictions."""
        if len(self._error_history) < 5:
            return {"insufficient_data": True}
        recent = list(self._error_history)[-20:]
        return {
            "mean_surprise": sum(e.surprise for e in recent) / len(recent),
            "mean_temp_error": sum(e.error_ambient_temp for e in recent) / len(recent),
            "mean_warmth_error": sum(e.error_warmth for e in recent) / len(recent),
            "mean_clarity_error": sum(e.error_clarity for e in recent) / len(recent),
            "reflection_count": len(self._reflection_history),
            "history_depth": len(self._sensor_history),
        }


# Global instance
_monitor: Optional[MetacognitiveMonitor] = None


def get_metacognitive_monitor() -> MetacognitiveMonitor:
    """Get or create the metacognitive monitor."""
    global _monitor
    if _monitor is None:
        _monitor = MetacognitiveMonitor()
    return _monitor
