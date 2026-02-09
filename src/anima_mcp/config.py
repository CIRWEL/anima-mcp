"""
Configuration - Lumen's Nervous System Calibration

Configuration values define how Lumen interprets its senses.
These aren't just "settings" - they're the creature's nervous system calibration.

Adapts to:
- Environment (altitude, climate)
- Hardware (Pi model, sensor types)
- Learned preferences over time
"""

import json
import yaml
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Tuple, Optional, Dict, Any


@dataclass
class NervousSystemCalibration:
    """
    How Lumen interprets its senses - the creature's nervous system calibration.
    
    These ranges define what Lumen considers "normal" vs "extreme" in its environment.
    """
    
    # Thermal ranges (Celsius)
    cpu_temp_min: float = 40.0      # Below this = cold
    cpu_temp_max: float = 80.0     # Above this = hot
    
    ambient_temp_min: float = 15.0  # Below this = cold environment
    ambient_temp_max: float = 35.0  # Above this = hot environment
    
    # Ideal values (deviation from these = instability)
    humidity_ideal: float = 45.0    # Ideal humidity (%)
    pressure_ideal: float = 1013.25 # Sea level standard (hPa)
    
    # Light perception (lux)
    light_min_lux: float = 1.0
    light_max_lux: float = 1000.0
    
    # Neural signal weights (how much neural vs physical signals matter)
    neural_weight: float = 0.3      # Weight for neural signals
    physical_weight: float = 0.7    # Weight for physical signals
    
    # Component weights for anima dimensions
    warmth_weights: Dict[str, float] = field(default_factory=lambda: {
        "cpu_temp": 0.4,
        "ambient_temp": 0.33,
        "neural": 0.27,
    })
    
    clarity_weights: Dict[str, float] = field(default_factory=lambda: {
        "prediction_accuracy": 0.5,  # How well I predict my own state = internal seeing
        "neural": 0.3,               # Alpha power = relaxed awareness
        "sensor_coverage": 0.2,      # Data richness
        # "light" removed: LEDs affect sensor creating feedback loop
    })
    
    stability_weights: Dict[str, float] = field(default_factory=lambda: {
        "humidity_dev": 0.25,
        "memory": 0.3,
        "missing_sensors": 0.2,
        "pressure_dev": 0.15,  # Pressure sensor contribution
        "neural": 0.1,
    })
    
    presence_weights: Dict[str, float] = field(default_factory=lambda: {
        "disk": 0.25,
        "memory": 0.3,
        "cpu": 0.25,
        "neural": 0.2,
    })
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NervousSystemCalibration":
        """Create from dictionary."""
        return cls(**data)
    
    def validate(self) -> Tuple[bool, Optional[str]]:
        """Validate calibration values are sensible."""
        if self.cpu_temp_min >= self.cpu_temp_max:
            return False, "cpu_temp_min must be < cpu_temp_max"
        
        if self.ambient_temp_min >= self.ambient_temp_max:
            return False, "ambient_temp_min must be < ambient_temp_max"
        
        if self.light_min_lux >= self.light_max_lux:
            return False, "light_min_lux must be < light_max_lux"
        
        if not (0 <= self.humidity_ideal <= 100):
            return False, "humidity_ideal must be 0-100"
        
        if self.pressure_ideal < 0:
            return False, "pressure_ideal must be positive"
        
        if not (0 <= self.neural_weight <= 1) or not (0 <= self.physical_weight <= 1):
            return False, "neural_weight and physical_weight must be 0-1"
        
        # Check weights sum to ~1.0 (allow some tolerance)
        for weight_dict in [self.warmth_weights, self.clarity_weights, 
                           self.stability_weights, self.presence_weights]:
            total = sum(weight_dict.values())
            if not (0.9 <= total <= 1.1):  # Allow 10% tolerance
                return False, f"Weights should sum to ~1.0, got {total}"
        
        return True, None


@dataclass
class DisplayConfig:
    """Display system configuration."""
    led_brightness: float = 0.12  # Base brightness (auto-brightness overrides this)
    update_interval: float = 2.0  # seconds
    breathing_enabled: bool = True
    breathing_cycle: float = 8.0  # seconds
    breathing_variation: float = 0.1  # ±10%
    # Enhanced LED features
    pulsing_enabled: bool = True  # Pulsing for low clarity/instability
    color_transitions_enabled: bool = True  # Smooth color changes
    pattern_mode: str = "standard"  # "standard", "minimal", "expressive", "alert"
    auto_brightness_enabled: bool = True  # Auto-adjust based on ambient light
    auto_brightness_min: float = 0.04  # Dim minimum (still visible at night)
    auto_brightness_max: float = 0.20  # Visible during day; self-model + auto-brightness compensate for sensor feedback
    pulsing_threshold_clarity: float = 0.4  # Clarity threshold for pulsing
    pulsing_threshold_stability: float = 0.4  # Stability threshold for pulsing


@dataclass
class AnimaConfig:
    """Complete configuration for anima-mcp."""
    nervous_system: NervousSystemCalibration = field(default_factory=NervousSystemCalibration)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    
    # Metadata for tracking changes
    metadata: Dict[str, Any] = field(default_factory=lambda: {
        "calibration_last_updated": None,
        "calibration_last_updated_by": None,  # "manual", "automatic", "agent"
        "calibration_update_count": 0,
        "calibration_history": [],  # List of recent changes
    })
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "nervous_system": self.nervous_system.to_dict(),
            "display": asdict(self.display),
            "metadata": self.metadata.copy(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnimaConfig":
        """Create from dictionary."""
        return cls(
            nervous_system=NervousSystemCalibration.from_dict(
                data.get("nervous_system", {})
            ),
            display=DisplayConfig(**data.get("display", {})),
            metadata=data.get("metadata", {
                "calibration_last_updated": None,
                "calibration_last_updated_by": None,
                "calibration_update_count": 0,
                "calibration_history": [],
            }),
        )
    
    def validate(self) -> Tuple[bool, Optional[str]]:
        """Validate entire configuration."""
        valid, error = self.nervous_system.validate()
        if not valid:
            return False, f"Nervous system calibration: {error}"
        
        if not (0 <= self.display.led_brightness <= 1):
            return False, "led_brightness must be 0-1"
        
        if self.display.update_interval <= 0:
            return False, "update_interval must be positive"
        
        return True, None


class ConfigManager:
    """Manages configuration loading, saving, and adaptation."""
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize config manager.
        
        Args:
            config_path: Path to config file (default: anima_config.yaml in current dir)
        """
        if config_path is None:
            config_path = Path("anima_config.yaml")
        self.config_path = Path(config_path)
        self._config: Optional[AnimaConfig] = None
    
    def load(self, force_reload: bool = False) -> AnimaConfig:
        """Load configuration from file or return defaults."""
        if self._config is not None and not force_reload:
            return self._config
        
        if self.config_path.exists():
            try:
                if self.config_path.suffix == ".yaml" or self.config_path.suffix == ".yml":
                    with open(self.config_path, "r") as f:
                        data = yaml.safe_load(f)
                else:
                    with open(self.config_path, "r") as f:
                        data = json.load(f)
                
                self._config = AnimaConfig.from_dict(data)
                
                # Validate
                valid, error = self._config.validate()
                if not valid:
                    print(f"[Config] Warning: Invalid config, using defaults: {error}")
                    self._config = AnimaConfig()
            except Exception as e:
                print(f"[Config] Error loading config, using defaults: {e}")
                self._config = AnimaConfig()
        else:
            # No config file - use defaults
            self._config = AnimaConfig()
        
        return self._config
    
    def save(self, config: Optional[AnimaConfig] = None, update_source: Optional[str] = None) -> bool:
        """
        Save configuration to file.
        
        Args:
            config: Config to save (uses current if None)
            update_source: Source of update ("manual", "automatic", "agent") for tracking
        
        Returns:
            True if saved successfully
        """
        if config is None:
            config = self._config or self.load()
        
        # Validate before saving
        valid, error = config.validate()
        if not valid:
            print(f"[Config] Cannot save invalid config: {error}")
            return False
        
        # Track calibration changes
        if update_source:
            from datetime import datetime
            # Load old config to compare
            old_config = self.load()
            old_cal = old_config.nervous_system.to_dict()
            new_cal = config.nervous_system.to_dict()
            
            # Detect changes
            changes = {}
            for key in old_cal:
                old_val = old_cal.get(key)
                new_val = new_cal.get(key)
                # Handle float comparison (allow small differences)
                if isinstance(old_val, float) and isinstance(new_val, float):
                    if abs(old_val - new_val) > 0.001:
                        changes[key] = {
                            "old": old_val,
                            "new": new_val,
                        }
                elif old_val != new_val:
                    changes[key] = {
                        "old": old_val,
                        "new": new_val,
                    }
            
            if changes:
                # Initialize metadata if needed
                if "calibration_last_updated" not in config.metadata:
                    config.metadata = {
                        "calibration_last_updated": None,
                        "calibration_last_updated_by": None,
                        "calibration_update_count": 0,
                        "calibration_history": [],
                    }
                
                # Update metadata
                config.metadata["calibration_last_updated"] = datetime.now().isoformat()
                config.metadata["calibration_last_updated_by"] = update_source
                config.metadata["calibration_update_count"] = config.metadata.get("calibration_update_count", 0) + 1
                
                # Add to history (keep last 10)
                history_entry = {
                    "timestamp": datetime.now().isoformat(),
                    "source": update_source,
                    "changes": changes,
                }
                history = config.metadata.get("calibration_history", [])
                history.append(history_entry)
                config.metadata["calibration_history"] = history[-10:]  # Keep last 10
        
        try:
            data = config.to_dict()
            
            if self.config_path.suffix == ".yaml" or self.config_path.suffix == ".yml":
                with open(self.config_path, "w") as f:
                    yaml.dump(data, f, default_flow_style=False, sort_keys=False)
            else:
                with open(self.config_path, "w") as f:
                    json.dump(data, f, indent=2)
            
            self._config = config
            # Force reload on next access to ensure consistency
            return True
        except Exception as e:
            print(f"[Config] Error saving config: {e}")
            return False
    
    def reload(self) -> AnimaConfig:
        """Force reload configuration from file."""
        self._config = None
        return self.load()
    
    def get_calibration(self) -> NervousSystemCalibration:
        """Get current nervous system calibration."""
        return self.load().nervous_system
    
    def get_display_config(self) -> DisplayConfig:
        """Get current display configuration."""
        return self.load().display
    
    def adapt_to_environment(
        self,
        observed_temps: list[float],
        observed_pressures: list[float],
        observed_humidity: list[float],
    ) -> NervousSystemCalibration:
        """
        Adapt calibration based on observed environment.
        
        Learns what's "normal" for this environment and adjusts ranges.
        
        Args:
            observed_temps: Observed ambient temperatures
            observed_pressures: Observed barometric pressures
            observed_humidity: Observed humidity values
        
        Returns:
            Adapted calibration
        """
        cal = self.get_calibration()
        
        # Adapt ambient temp range based on observations
        if observed_temps:
            temp_min = min(observed_temps)
            temp_max = max(observed_temps)
            # Expand range by 20% for safety margin
            range_expansion = (temp_max - temp_min) * 0.2
            cal.ambient_temp_min = max(0, temp_min - range_expansion)
            cal.ambient_temp_max = temp_max + range_expansion
        
        # Adapt pressure ideal based on observations
        if observed_pressures:
            cal.pressure_ideal = sum(observed_pressures) / len(observed_pressures)
        
        # Adapt humidity ideal based on observations
        if observed_humidity:
            cal.humidity_ideal = sum(observed_humidity) / len(observed_humidity)
            # Clamp to reasonable range
            cal.humidity_ideal = max(20, min(80, cal.humidity_ideal))
        
        return cal


# Global config manager instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager(config_path: Optional[Path] = None) -> ConfigManager:
    """Get global config manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager(config_path)
    return _config_manager


def get_calibration() -> NervousSystemCalibration:
    """Get current nervous system calibration."""
    return get_config_manager().get_calibration()


def get_display_config() -> DisplayConfig:
    """Get current display configuration."""
    return get_config_manager().get_display_config()
