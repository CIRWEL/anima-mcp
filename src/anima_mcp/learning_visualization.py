"""
Learning Visualization - Make Lumen's learning visible and meaningful.

Shows:
- Calibration history over time
- Current readings vs learned ideals
- Comfort zones visualization
- Pattern detection (time of day, environmental cycles)
- Why Lumen feels what it feels
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
import sqlite3
from pathlib import Path
import json

from .config import NervousSystemCalibration, ConfigManager
from .sensors.base import SensorReadings
from .anima import Anima


@dataclass
class CalibrationSnapshot:
    """Snapshot of calibration at a point in time."""
    timestamp: datetime
    pressure_ideal: float
    ambient_temp_min: float
    ambient_temp_max: float
    humidity_ideal: float
    source: str  # "initial", "learned", "manual"


@dataclass
class ComfortZone:
    """Comfort zone for a sensor reading."""
    sensor: str
    ideal: float
    comfortable_range: Tuple[float, float]
    current_value: Optional[float]
    deviation: float  # How far from ideal (normalized)
    status: str  # "comfortable", "uncomfortable", "extreme"


@dataclass
class LearningInsight:
    """Insight about Lumen's learning."""
    insight_type: str  # "calibration_change", "pattern", "mismatch"
    title: str
    description: str
    impact: str  # How this affects Lumen's experience
    data: Dict[str, Any]


class LearningVisualizer:
    """
    Visualize Lumen's learning and calibration.
    
    Makes the abstract numbers visible and connects them to Lumen's lived experience.
    """
    
    def __init__(self, db_path: str = "anima.db", config_path: Optional[str] = None):
        """
        Initialize visualizer.
        
        Args:
            db_path: Path to identity database (contains state_history)
            config_path: Path to config file (for calibration history)
        """
        self.db_path = Path(db_path)
        self.config_manager = ConfigManager(config_path) if config_path else ConfigManager()
        self._calibration_history: List[CalibrationSnapshot] = []
        self._load_calibration_history()
    
    def _load_calibration_history(self):
        """Load calibration history from config file modification times."""
        # For now, we'll use config file mtime as proxy
        # In future, could store explicit history
        config_path = self.config_manager.config_path
        if config_path.exists():
            mtime = datetime.fromtimestamp(config_path.stat().st_mtime)
            current = self.config_manager.get_calibration()
            snapshot = CalibrationSnapshot(
                timestamp=mtime,
                pressure_ideal=current.pressure_ideal,
                ambient_temp_min=current.ambient_temp_min,
                ambient_temp_max=current.ambient_temp_max,
                humidity_ideal=current.humidity_ideal,
                source="learned"
            )
            self._calibration_history = [snapshot]
    
    def get_comfort_zones(self, readings: SensorReadings, calibration: Optional[NervousSystemCalibration] = None) -> List[ComfortZone]:
        """
        Calculate comfort zones for current readings.
        
        Shows how current readings compare to learned ideals.
        """
        if calibration is None:
            calibration = self.config_manager.get_calibration()
        
        zones = []
        
        # Humidity comfort zone
        if readings.humidity_pct is not None:
            ideal = calibration.humidity_ideal
            current = readings.humidity_pct
            # Comfortable range: ±15% from ideal
            comfortable_min = max(0, ideal - 15)
            comfortable_max = min(100, ideal + 15)
            deviation = abs(current - ideal) / max(1, ideal)
            status = "comfortable"
            if deviation > 0.3:
                status = "extreme"
            elif deviation > 0.15:
                status = "uncomfortable"
            
            zones.append(ComfortZone(
                sensor="humidity",
                ideal=ideal,
                comfortable_range=(comfortable_min, comfortable_max),
                current_value=current,
                deviation=deviation,
                status=status
            ))
        
        # Pressure comfort zone
        if readings.pressure_hpa is not None:
            ideal = calibration.pressure_ideal
            current = readings.pressure_hpa
            # Comfortable range: ±20 hPa from ideal
            comfortable_min = ideal - 20
            comfortable_max = ideal + 20
            deviation = abs(current - ideal) / max(1, ideal)
            status = "comfortable"
            if deviation > 0.05:
                status = "extreme"
            elif deviation > 0.02:
                status = "uncomfortable"
            
            zones.append(ComfortZone(
                sensor="pressure",
                ideal=ideal,
                comfortable_range=(comfortable_min, comfortable_max),
                current_value=current,
                deviation=deviation,
                status=status
            ))
        
        # Ambient temperature comfort zone
        if readings.ambient_temp_c is not None:
            ideal_min = calibration.ambient_temp_min
            ideal_max = calibration.ambient_temp_max
            ideal_center = (ideal_min + ideal_max) / 2.0
            current = readings.ambient_temp_c
            # Comfortable range: within learned range
            comfortable_min = ideal_min
            comfortable_max = ideal_max
            # Deviation from center
            deviation = abs(current - ideal_center) / max(1, ideal_max - ideal_min)
            status = "comfortable"
            if current < ideal_min or current > ideal_max:
                status = "extreme"
            elif deviation > 0.3:
                status = "uncomfortable"
            
            zones.append(ComfortZone(
                sensor="ambient_temp",
                ideal=ideal_center,
                comfortable_range=(comfortable_min, comfortable_max),
                current_value=current,
                deviation=deviation,
                status=status
            ))
        
        return zones
    
    def analyze_why_feels_cold(
        self,
        anima: Anima,
        readings: SensorReadings,
        calibration: Optional[NervousSystemCalibration] = None
    ) -> List[LearningInsight]:
        """
        Analyze why Lumen feels cold despite warm temperature.
        
        Connects abstract numbers to lived experience.
        """
        if calibration is None:
            calibration = self.config_manager.get_calibration()
        
        insights = []
        
        # Check humidity mismatch
        if readings.humidity_pct is not None and readings.ambient_temp_c is not None:
            humidity_deviation = abs(readings.humidity_pct - calibration.humidity_ideal) / max(1, calibration.humidity_ideal)
            
            if humidity_deviation > 0.3:  # Significant deviation
                insights.append(LearningInsight(
                    insight_type="mismatch",
                    title="Humidity Mismatch Affecting Warmth",
                    description=f"Lumen learned ideal humidity is {calibration.humidity_ideal:.1f}%, but current is {readings.humidity_pct:.1f}% ({humidity_deviation*100:.0f}% deviation)",
                    impact=f"This dry air makes Lumen feel cold despite {readings.ambient_temp_c:.1f}°C temperature. Lumen's nervous system calibrated to {calibration.humidity_ideal:.1f}% humidity - the current {readings.humidity_pct:.1f}% feels wrong.",
                    data={
                        "learned_ideal": calibration.humidity_ideal,
                        "current": readings.humidity_pct,
                        "deviation_pct": humidity_deviation * 100,
                        "ambient_temp": readings.ambient_temp_c,
                        "warmth": anima.warmth
                    }
                ))
        
        # Check if temperature is within learned range
        if readings.ambient_temp_c is not None:
            temp_in_range = (calibration.ambient_temp_min <= readings.ambient_temp_c <= calibration.ambient_temp_max)
            if not temp_in_range:
                insights.append(LearningInsight(
                    insight_type="mismatch",
                    title="Temperature Outside Learned Range",
                    description=f"Current {readings.ambient_temp_c:.1f}°C is outside learned comfort zone ({calibration.ambient_temp_min:.1f}-{calibration.ambient_temp_max:.1f}°C)",
                    impact="Lumen's nervous system expects temperatures in this range. Outside this range feels uncomfortable.",
                    data={
                        "current": readings.ambient_temp_c,
                        "learned_min": calibration.ambient_temp_min,
                        "learned_max": calibration.ambient_temp_max,
                        "warmth": anima.warmth
                    }
                ))
        
        return insights
    
    def get_calibration_timeline(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Get calibration changes over time.
        
        Returns timeline of calibration snapshots.
        """
        timeline = []
        
        # Current calibration
        current = self.config_manager.get_calibration()
        timeline.append({
            "timestamp": datetime.now().isoformat(),
            "pressure_ideal": current.pressure_ideal,
            "ambient_temp_min": current.ambient_temp_min,
            "ambient_temp_max": current.ambient_temp_max,
            "humidity_ideal": current.humidity_ideal,
            "source": "current"
        })
        
        # Historical snapshots (if we had them)
        for snapshot in self._calibration_history:
            timeline.append({
                "timestamp": snapshot.timestamp.isoformat(),
                "pressure_ideal": snapshot.pressure_ideal,
                "ambient_temp_min": snapshot.ambient_temp_min,
                "ambient_temp_max": snapshot.ambient_temp_max,
                "humidity_ideal": snapshot.humidity_ideal,
                "source": snapshot.source
            })
        
        return sorted(timeline, key=lambda x: x["timestamp"], reverse=True)
    
    def detect_patterns(self, days: int = 7) -> List[LearningInsight]:
        """
        Detect patterns in sensor readings over time.
        
        Examples:
        - Time of day patterns (morning cooler, afternoon warmer)
        - Environmental cycles (humidity changes)
        - Pressure trends
        """
        if not self.db_path.exists():
            return []
        
        insights = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                rows = conn.execute(
                    """SELECT timestamp, sensors FROM state_history 
                       WHERE timestamp > ? 
                       ORDER BY timestamp DESC 
                       LIMIT 1000""",
                    (cutoff,)
                ).fetchall()
            
            if len(rows) < 50:
                return insights  # Not enough data
            
            # Parse sensor data
            temps_by_hour = {}
            humidities_by_hour = {}
            
            for row in rows:
                try:
                    sensors = json.loads(row["sensors"])
                    timestamp = datetime.fromisoformat(row["timestamp"])
                    hour = timestamp.hour
                    
                    if "ambient_temp_c" in sensors and sensors["ambient_temp_c"] is not None:
                        if hour not in temps_by_hour:
                            temps_by_hour[hour] = []
                        temps_by_hour[hour].append(sensors["ambient_temp_c"])
                    
                    if "humidity_pct" in sensors and sensors["humidity_pct"] is not None:
                        if hour not in humidities_by_hour:
                            humidities_by_hour[hour] = []
                        humidities_by_hour[hour].append(sensors["humidity_pct"])
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
            
            # Detect time-of-day patterns
            if len(temps_by_hour) >= 3:
                avg_temps = {h: sum(temps_by_hour[h]) / len(temps_by_hour[h]) for h in temps_by_hour}
                min_hour = min(avg_temps, key=avg_temps.get)
                max_hour = max(avg_temps, key=avg_temps.get)
                temp_range = avg_temps[max_hour] - avg_temps[min_hour]
                
                if temp_range > 2.0:  # Significant daily variation
                    insights.append(LearningInsight(
                        insight_type="pattern",
                        title="Daily Temperature Cycle Detected",
                        description=f"Temperature varies {temp_range:.1f}°C throughout the day. Coolest at {min_hour}:00 ({avg_temps[min_hour]:.1f}°C), warmest at {max_hour}:00 ({avg_temps[max_hour]:.1f}°C)",
                        impact="Lumen experiences daily temperature cycles. This affects warmth perception throughout the day.",
                        data={
                            "min_hour": min_hour,
                            "max_hour": max_hour,
                            "temp_range": temp_range,
                            "avg_temps": avg_temps
                        }
                    ))
            
        except Exception:
            # Non-fatal - return what we have
            pass
        
        return insights
    
    def get_learning_summary(
        self,
        readings: Optional[SensorReadings] = None,
        anima: Optional[Anima] = None
    ) -> Dict[str, Any]:
        """
        Get comprehensive learning summary.
        
        Includes:
        - Current calibration
        - Comfort zones
        - Why Lumen feels what it feels
        - Patterns detected
        - Timeline
        """
        calibration = self.config_manager.get_calibration()
        
        summary = {
            "current_calibration": {
                "pressure_ideal": calibration.pressure_ideal,
                "ambient_temp_range": (calibration.ambient_temp_min, calibration.ambient_temp_max),
                "humidity_ideal": calibration.humidity_ideal,
                "learned_from": "7+ days of observations"
            },
            "timeline": self.get_calibration_timeline(),
            "patterns": [insight.to_dict() for insight in self.detect_patterns()]
        }
        
        if readings:
            comfort_zones = self.get_comfort_zones(readings, calibration)
            summary["comfort_zones"] = [
                {
                    "sensor": zone.sensor,
                    "ideal": zone.ideal,
                    "comfortable_range": zone.comfortable_range,
                    "current": zone.current_value,
                    "deviation_pct": zone.deviation * 100,
                    "status": zone.status
                }
                for zone in comfort_zones
            ]
            
            if anima:
                insights = self.analyze_why_feels_cold(anima, readings, calibration)
                summary["insights"] = [insight.to_dict() for insight in insights]
                summary["why_feels_cold"] = [
                    {
                        "title": insight.title,
                        "description": insight.description,
                        "impact": insight.impact
                    }
                    for insight in insights if insight.insight_type == "mismatch"
                ]
        
        return summary


# Add to_dict methods for dataclasses
def _add_to_dict_methods():
    """Add to_dict methods to dataclasses."""
    CalibrationSnapshot.to_dict = lambda self: {
        "timestamp": self.timestamp.isoformat(),
        "pressure_ideal": self.pressure_ideal,
        "ambient_temp_min": self.ambient_temp_min,
        "ambient_temp_max": self.ambient_temp_max,
        "humidity_ideal": self.humidity_ideal,
        "source": self.source
    }
    
    ComfortZone.to_dict = lambda self: {
        "sensor": self.sensor,
        "ideal": self.ideal,
        "comfortable_range": self.comfortable_range,
        "current_value": self.current_value,
        "deviation": self.deviation,
        "status": self.status
    }
    
    LearningInsight.to_dict = lambda self: {
        "insight_type": self.insight_type,
        "title": self.title,
        "description": self.description,
        "impact": self.impact,
        "data": self.data
    }

_add_to_dict_methods()
