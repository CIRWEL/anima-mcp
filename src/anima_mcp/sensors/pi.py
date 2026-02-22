"""
Real Pi sensors - BrainCraft HAT and connected sensors.

Only imported when running on actual Pi hardware.

Hardware:
- BrainCraft HAT: Display (240x240 TFT), LEDs (3 DotStar), sensors
  - AHT20: Temperature + humidity
  - VEML7700: Ambient light sensor
  - BMP280: Barometric pressure + temperature

Neural signals derived from Pi's computational state (computational proprioception).
"""

import sys
import psutil
from datetime import datetime
from pathlib import Path
from .base import SensorBackend, SensorReadings


class PiSensors(SensorBackend):
    """
    Real Raspberry Pi sensors via BrainCraft HAT.
    
    BrainCraft HAT provides:
    - Display (240x240 TFT)
    - LEDs (3 DotStar)
    - Sensors: Temperature, humidity, light, pressure
    
    Neural signals derived from Pi's own computational state (computational proprioception).
    """

    def __init__(self):
        """Initialize Pi sensors."""
        self._i2c = None
        self._aht = None
        self._light_sensor = None
        self._bmp280 = None
        self._last_pressure = None
        self._init_sensors()
        # Prime psutil cpu_percent so first real call returns meaningful data
        psutil.cpu_percent(interval=None)

    def _init_sensors(self):
        """Initialize available sensors with retry logic."""
        from ..error_recovery import retry_with_backoff, RetryConfig, safe_call
        
        # Retry config for sensor initialization
        init_config = RetryConfig(max_attempts=3, initial_delay=0.5, max_delay=2.0)
        
        # Create shared I2C bus with retry
        def init_i2c():
            import board
            import busio
            return busio.I2C(board.SCL, board.SDA)
        
        self._i2c = safe_call(
            lambda: retry_with_backoff(init_i2c, config=init_config),
            default=None
        )
        
        if self._i2c is None:
            print("[PiSensors] I2C init failed after retries", file=sys.stderr, flush=True)
            return

        # AHT20 sensor (temperature + humidity) at 0x38 with retry
        def init_aht():
            import adafruit_ahtx0
            return adafruit_ahtx0.AHTx0(self._i2c)
        
        self._aht = safe_call(
            lambda: retry_with_backoff(init_aht, config=init_config),
            default=None
        )
        if self._aht:
            print("[PiSensors] AHT20 initialized", file=sys.stderr, flush=True)
        else:
            print("[PiSensors] AHT20 not available after retries", file=sys.stderr, flush=True)

        # VEML7700 light sensor at 0x10 with retry
        def init_light():
            import adafruit_veml7700
            return adafruit_veml7700.VEML7700(self._i2c)
        
        self._light_sensor = safe_call(
            lambda: retry_with_backoff(init_light, config=init_config),
            default=None
        )
        if self._light_sensor:
            print("[PiSensors] VEML7700 initialized", file=sys.stderr, flush=True)
        else:
            print("[PiSensors] VEML7700 not available after retries", file=sys.stderr, flush=True)

        # BMP280 pressure/temperature sensor at 0x76 or 0x77 with retry
        def init_bmp():
            import adafruit_bmp280
            bmp = adafruit_bmp280.Adafruit_BMP280_I2C(self._i2c)
            bmp.sea_level_pressure = 1013.25
            return bmp
        
        self._bmp280 = safe_call(
            lambda: retry_with_backoff(init_bmp, config=init_config),
            default=None
        )
        if self._bmp280:
            print("[PiSensors] BMP280 initialized", file=sys.stderr, flush=True)
        else:
            print("[PiSensors] BMP280 not available after retries", file=sys.stderr, flush=True)

        # Brain HAT (EEG hardware) - Not available
        # No physical EEG hardware exists. Neural signals come from computational proprioception.
        self._brain_hat = None

    def _read_cpu_temp(self) -> float | None:
        """Read Pi CPU temperature from sysfs with retry."""
        from ..error_recovery import retry_with_backoff, RetryConfig, safe_call
        
        def read_temp():
            temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
            if temp_path.exists():
                return int(temp_path.read_text().strip()) / 1000.0
            return None
        
        read_config = RetryConfig(max_attempts=2, initial_delay=0.1, max_delay=0.5)
        return safe_call(
            lambda: retry_with_backoff(read_temp, config=read_config),
            default=None
        )

    def _read_throttle_status(self) -> dict:
        """Read Pi voltage/throttle state from vcgencmd.

        Returns dict with parsed throttle flags:
          throttle_bits: raw int (e.g. 0x50005)
          undervoltage_now: bool (bit 0)
          throttled_now: bool (bit 1)
          freq_capped_now: bool (bit 2)
          undervoltage_occurred: bool (bit 16)
        """
        import subprocess
        try:
            result = subprocess.run(
                ["vcgencmd", "get_throttled"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and "throttled=" in result.stdout:
                # Output: "throttled=0x50005\n"
                hex_str = result.stdout.strip().split("=")[1]
                bits = int(hex_str, 16)
                return {
                    "throttle_bits": bits,
                    "undervoltage_now": bool(bits & 0x1),
                    "throttled_now": bool(bits & 0x2),
                    "freq_capped_now": bool(bits & 0x4),
                    "undervoltage_occurred": bool(bits & 0x10000),
                }
        except Exception:
            pass
        return {}

    def read(self) -> SensorReadings:
        """Read all available sensors."""
        now = datetime.now()

        # CPU temp (always available on Pi)
        cpu_temp = self._read_cpu_temp()

        # AHT20 sensor (temperature + humidity) with retry
        ambient_temp = None
        humidity = None
        if self._aht:
            from ..error_recovery import retry_with_backoff, RetryConfig, safe_call
            read_config = RetryConfig(max_attempts=2, initial_delay=0.1, max_delay=0.5)
            
            def read_aht():
                return (self._aht.temperature, self._aht.relative_humidity)
            
            result = safe_call(
                lambda: retry_with_backoff(read_aht, config=read_config),
                default=None
            )
            if result:
                ambient_temp, humidity = result

        # Light sensor with retry
        light = None
        if self._light_sensor:
            from ..error_recovery import retry_with_backoff, RetryConfig, safe_call
            read_config = RetryConfig(max_attempts=2, initial_delay=0.1, max_delay=0.5)
            
            def read_light():
                return self._light_sensor.lux
            
            light = safe_call(
                lambda: retry_with_backoff(read_light, config=read_config),
                default=None
            )

        # BMP280 pressure/temperature sensor with retry
        pressure = None
        pressure_temp = None
        if self._bmp280:
            from ..error_recovery import retry_with_backoff, RetryConfig, safe_call
            read_config = RetryConfig(max_attempts=2, initial_delay=0.1, max_delay=0.5)
            
            def read_bmp():
                return (self._bmp280.pressure, self._bmp280.temperature)
            
            result = safe_call(
                lambda: retry_with_backoff(read_bmp, config=read_config),
                default=None
            )
            if result:
                pressure, pressure_temp = result
                self._last_pressure = pressure

        # System stats
        cpu_percent = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        # Voltage / throttle state
        throttle = self._read_throttle_status()

        # Neural Signals: Computational Proprioception
        # Lumen's "brain" IS the Pi's CPU. We map computational state directly to neural bands.
        # This is not a simulation - it is the actual measurement of the creature's cognitive substrate.
        
        eeg_bands = {}
        try:
            from ..computational_neural import get_computational_neural_state
            # Get the raw computational state
            neural = get_computational_neural_state(
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                cpu_temp=cpu_temp
            )
            
            # Map directly to EEG bands
            eeg_bands = {
                "delta": neural.delta,
                "theta": neural.theta,
                "alpha": neural.alpha,
                "beta": neural.beta,
                "gamma": neural.gamma,
            }
        except Exception as e:
            print(f"[PiSensors] Computational neural error: {e}", file=sys.stderr, flush=True)

        # Neural frequency bands come from computational proprioception (not physical EEG hardware)
        # No physical EEG hardware exists - neural signals are derived from environment + computation

        return SensorReadings(
            timestamp=now,
            cpu_temp_c=cpu_temp,
            ambient_temp_c=ambient_temp,
            humidity_pct=humidity,
            light_lux=light,
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            disk_percent=disk.percent,
            power_watts=None,  # Would need INA219 sensor
            throttle_bits=throttle.get("throttle_bits"),
            undervoltage_now=throttle.get("undervoltage_now"),
            throttled_now=throttle.get("throttled_now"),
            freq_capped_now=throttle.get("freq_capped_now"),
            undervoltage_occurred=throttle.get("undervoltage_occurred"),
            pressure_hpa=pressure,
            pressure_temp_c=pressure_temp,
            # EEG channel fields (Reserved/Legacy - always None, preserved for schema compatibility)
            eeg_tp9=None,
            eeg_af7=None,
            eeg_af8=None,
            eeg_tp10=None,
            eeg_aux1=None,
            eeg_aux2=None,
            eeg_aux3=None,
            eeg_aux4=None,
            # Frequency bands (Always from Computational Proprioception)
            eeg_delta_power=eeg_bands.get("delta"),
            eeg_theta_power=eeg_bands.get("theta"),
            eeg_alpha_power=eeg_bands.get("alpha"),
            eeg_beta_power=eeg_bands.get("beta"),
            eeg_gamma_power=eeg_bands.get("gamma"),
        )

    def available_sensors(self) -> list[str]:
        sensors = ["cpu_temp_c", "cpu_percent", "memory_percent", "disk_percent"]
        if self._aht:
            sensors.extend(["ambient_temp_c", "humidity_pct"])
        if self._light_sensor:
            sensors.append("light_lux")
        if self._bmp280:
            sensors.extend(["pressure_hpa", "pressure_temp_c"])
        
        # Neural sensors (Computational Proprioception)
        # Frequency bands derived from environment + computation (not physical EEG hardware)
        sensors.extend([
            "eeg_delta_power", "eeg_theta_power", "eeg_alpha_power",
            "eeg_beta_power", "eeg_gamma_power"
        ])
        
        # Note: EEG channel fields (eeg_tp9, etc.) exist in schema for compatibility
        # but are always None - no physical EEG hardware exists
            
        return sensors

    def is_pi(self) -> bool:
        return True
