# Error Recovery System

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## Overview

Robust error handling system with retry logic, exponential backoff, and circuit breaker patterns. Handles transient failures gracefully while preventing cascading failures.

---

## Features

### 1. Retry Logic with Exponential Backoff

Automatically retries failed operations with increasing delays:

```python
from anima_mcp.error_recovery import retry_with_backoff, RetryConfig

config = RetryConfig(
    max_attempts=3,
    initial_delay=0.1,  # seconds
    max_delay=5.0,
    exponential_base=2.0,
    jitter=True  # Add randomness
)

result = retry_with_backoff(lambda: sensor.read(), config=config)
```

**How it works:**
- Attempt 1: Immediate
- Attempt 2: 0.1s delay
- Attempt 3: 0.2s delay (with jitter)
- Max delay capped at 5.0s

### 2. Error Classification

Automatically classifies errors:

- **TRANSIENT** - Temporary, should retry (default)
- **PERMANENT** - Persistent, don't retry
- **HARDWARE** - Hardware failure (I2C, SPI, GPIO)
- **NETWORK** - Network issues
- **CONFIG** - Configuration errors

```python
from anima_mcp.error_recovery import classify_error

error_type = classify_error(exception)
# Returns: ErrorType.TRANSIENT, ErrorType.HARDWARE, etc.
```

### 3. Circuit Breaker Pattern

Prevents cascading failures by "opening" circuit after too many failures:

```python
from anima_mcp.error_recovery import CircuitBreaker

breaker = CircuitBreaker(
    failure_threshold=5,  # Open after 5 failures
    timeout=timedelta(seconds=60),  # Try again after 60s
    success_threshold=2  # Need 2 successes to close
)

result = breaker.call(lambda: sensor.read())
```

**States:**
- **Closed**: Normal operation
- **Open**: Too many failures, requests fail immediately
- **Half-open**: Testing if service recovered

### 4. Safe Call Wrappers

Convenient wrappers that return defaults on error:

```python
from anima_mcp.error_recovery import safe_call, safe_call_async

# Sync
result = safe_call(lambda: risky_operation(), default=None)

# Async
result = await safe_call_async(lambda: async_operation(), default=None)
```

---

## Usage in Codebase

### Sensor Initialization

**Before:**
```python
try:
    self._aht = adafruit_ahtx0.AHTx0(self._i2c)
except Exception as e:
    print(f"AHT20 not available: {e}")
    self._aht = None
```

**After:**
```python
from ..error_recovery import retry_with_backoff, RetryConfig, safe_call

init_config = RetryConfig(max_attempts=3, initial_delay=0.5, max_delay=2.0)

def init_aht():
    import adafruit_ahtx0
    return adafruit_ahtx0.AHTx0(self._i2c)

self._aht = safe_call(
    lambda: retry_with_backoff(init_aht, config=init_config),
    default=None
)
```

### Sensor Reads

**Before:**
```python
try:
    ambient_temp = self._aht.temperature
except Exception:
    pass
```

**After:**
```python
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
```

### Display Loop

**Before:**
```python
except Exception as e:
    print(f"[Display] Update error: {e}")
    await asyncio.sleep(5.0)  # Fixed delay
```

**After:**
```python
consecutive_errors = 0
max_delay = 30.0

try:
    # ... operations ...
    consecutive_errors = 0  # Reset on success
except Exception as e:
    consecutive_errors += 1
    # Exponential backoff
    delay = min(base_delay * (2 ** min(consecutive_errors // 3, 4)), max_delay)
    await asyncio.sleep(delay)
```

### LED Updates

**Before:**
```python
try:
    self._dots[0] = color
    self._dots.show()
except Exception as e:
    print(f"Error: {e}")
```

**After:**
```python
from ..error_recovery import retry_with_backoff, RetryConfig, safe_call

retry_config = RetryConfig(max_attempts=2, initial_delay=0.1, max_delay=0.5)

def set_leds():
    self._dots[0] = color
    self._dots.show()

safe_call(
    lambda: retry_with_backoff(set_leds, config=retry_config),
    default=None,
    log_error=True
)
```

---

## Configuration

### RetryConfig

```python
@dataclass
class RetryConfig:
    max_attempts: int = 3          # Max retry attempts
    initial_delay: float = 0.1      # Initial delay (seconds)
    max_delay: float = 5.0          # Max delay cap (seconds)
    exponential_base: float = 2.0   # Backoff multiplier
    jitter: bool = True            # Add randomness
```

### CircuitBreaker

```python
CircuitBreaker(
    failure_threshold: int = 5,                    # Failures to open
    timeout: timedelta = timedelta(seconds=60),    # Time before retry
    success_threshold: int = 2                     # Successes to close
)
```

---

## Error Types

### Transient Errors (Retry)

- I2C bus errors (temporary)
- Sensor read timeouts
- Network hiccups
- Hardware initialization failures (first attempt)

### Permanent Errors (Don't Retry)

- Configuration errors
- Missing dependencies
- Invalid parameters
- Hardware not present

### Hardware Errors (Retry with Care)

- I2C/SPI communication failures
- GPIO pin errors
- Sensor initialization failures

---

## Benefits

### 1. Resilience

- **Handles transient failures** - Retries automatically
- **Prevents cascading failures** - Circuit breaker pattern
- **Graceful degradation** - Continues operating with partial failures

### 2. Performance

- **Exponential backoff** - Reduces load on failing systems
- **Jitter** - Prevents thundering herd problem
- **Early exit** - Permanent errors fail fast

### 3. Observability

- **Error classification** - Understand failure types
- **Logging** - Track retry attempts and failures
- **Metrics** - Can track failure rates (future)

---

## Examples

### Sensor Read with Retry

```python
from anima_mcp.error_recovery import retry_with_backoff, RetryConfig, safe_call

def read_sensor():
    return sensor.temperature

config = RetryConfig(max_attempts=3, initial_delay=0.2)
temp = safe_call(
    lambda: retry_with_backoff(read_sensor, config=config),
    default=None
)
```

### Display Update with Exponential Backoff

```python
consecutive_errors = 0
base_delay = 2.0
max_delay = 30.0

while True:
    try:
        update_display()
        consecutive_errors = 0
        await asyncio.sleep(base_delay)
    except Exception as e:
        consecutive_errors += 1
        delay = min(base_delay * (2 ** min(consecutive_errors // 3, 4)), max_delay)
        await asyncio.sleep(delay)
```

### Circuit Breaker for Critical Operations

```python
from anima_mcp.error_recovery import CircuitBreaker

breaker = CircuitBreaker(failure_threshold=5, timeout=timedelta(seconds=60))

try:
    result = breaker.call(lambda: critical_operation())
except Exception:
    # Circuit is open or operation failed
    use_fallback()
```

---

## Related

- **`CODEBASE_REVIEW.md`** - Original recommendations
- **`error_recovery.py`** - Implementation
- **`sensors/pi.py`** - Sensor error handling
- **`server.py`** - Display loop error handling
- **`display/leds.py`** - LED error handling

---

**Robust error handling makes Lumen resilient to hardware glitches, network hiccups, and temporary failures.**
