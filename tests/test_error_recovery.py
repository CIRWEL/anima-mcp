"""Tests for error_recovery module — classification, retry, circuit breaker, safe_call."""

import time
import pytest
from datetime import timedelta

from anima_mcp.error_recovery import (
    classify_error, retry_with_backoff, safe_call, safe_call_with_timeout,
    CircuitBreaker, RetryConfig, ErrorType,
    TransientError, PermanentError, HardwareError,
)

# Use fast config to avoid sleeps in tests
FAST_CONFIG = RetryConfig(max_attempts=3, initial_delay=0, jitter=False)


class TestClassifyError:
    """Test keyword-based error classification."""

    def test_i2c_is_hardware(self):
        assert classify_error(Exception("I2C bus error")) == ErrorType.HARDWARE

    def test_spi_is_hardware(self):
        assert classify_error(Exception("SPI transfer failed")) == ErrorType.HARDWARE

    def test_gpio_is_hardware(self):
        assert classify_error(Exception("GPIO pin not responding")) == ErrorType.HARDWARE

    def test_sensor_is_hardware(self):
        assert classify_error(Exception("sensor read failed")) == ErrorType.HARDWARE

    def test_network_is_network(self):
        assert classify_error(Exception("network unreachable")) == ErrorType.NETWORK

    def test_connection_is_network(self):
        assert classify_error(Exception("connection refused")) == ErrorType.NETWORK

    def test_timeout_is_network(self):
        assert classify_error(Exception("timeout waiting for response")) == ErrorType.NETWORK

    def test_config_is_config(self):
        assert classify_error(Exception("config key missing")) == ErrorType.CONFIG

    def test_invalid_is_config(self):
        assert classify_error(Exception("invalid parameter value")) == ErrorType.CONFIG

    def test_unknown_defaults_to_transient(self):
        assert classify_error(Exception("something weird happened")) == ErrorType.TRANSIENT

    def test_empty_message_is_transient(self):
        assert classify_error(Exception("")) == ErrorType.TRANSIENT

    def test_case_insensitive(self):
        assert classify_error(Exception("I2C BUS FAILURE")) == ErrorType.HARDWARE


class TestRetryWithBackoff:
    """Test retry logic."""

    def test_success_on_first_try(self):
        calls = []
        def fn():
            calls.append(1)
            return 42
        result = retry_with_backoff(fn, FAST_CONFIG)
        assert result == 42
        assert len(calls) == 1

    def test_retries_on_transient_error(self):
        calls = []
        def fn():
            calls.append(1)
            if len(calls) < 3:
                raise TransientError("retry me")
            return "success"
        result = retry_with_backoff(fn, FAST_CONFIG)
        assert result == "success"
        assert len(calls) == 3

    def test_no_retry_on_config_error(self):
        """CONFIG errors are permanent — no retry."""
        calls = []
        def fn():
            calls.append(1)
            raise Exception("config key missing")
        with pytest.raises(Exception, match="config key missing"):
            retry_with_backoff(fn, FAST_CONFIG)
        assert len(calls) == 1

    def test_raises_after_exhausting_retries(self):
        def fn():
            raise TransientError("keep failing")
        with pytest.raises(TransientError, match="keep failing"):
            retry_with_backoff(fn, RetryConfig(max_attempts=2, initial_delay=0, jitter=False))

    def test_error_filter_skips_unmatched(self):
        calls = []
        def fn():
            calls.append(1)
            raise ValueError("nope")
        with pytest.raises(ValueError):
            retry_with_backoff(fn, FAST_CONFIG, error_filter=lambda e: isinstance(e, TypeError))
        assert len(calls) == 1

    def test_error_filter_allows_retry(self):
        calls = []
        def fn():
            calls.append(1)
            if len(calls) < 2:
                raise ValueError("retry this")
            return "ok"
        result = retry_with_backoff(fn, FAST_CONFIG, error_filter=lambda e: isinstance(e, ValueError))
        assert result == "ok"
        assert len(calls) == 2

    def test_default_config_used_when_none(self):
        """Should work with default RetryConfig when none provided."""
        result = retry_with_backoff(lambda: "default_ok")
        assert result == "default_ok"


class TestSafeCall:
    """Test safe_call wrapper."""

    def test_returns_value(self):
        assert safe_call(lambda: 99, default=0) == 99

    def test_returns_default_on_exception(self):
        assert safe_call(lambda: 1 / 0, default=-1, log_error=False) == -1

    def test_returns_none_as_default(self):
        assert safe_call(lambda: 1 / 0, log_error=False) is None

    def test_returns_none_result_not_confused_with_error(self):
        assert safe_call(lambda: None, default="error") is None


class TestSafeCallWithTimeout:
    """Test safe_call_with_timeout wrapper."""

    def test_returns_value_within_timeout(self):
        result = safe_call_with_timeout(lambda: "fast", timeout_seconds=1.0)
        assert result == "fast"

    def test_returns_default_on_timeout(self):
        def slow():
            time.sleep(5)
            return "never"
        result = safe_call_with_timeout(slow, timeout_seconds=0.05, default="timed_out", log_error=False)
        assert result == "timed_out"

    def test_returns_default_on_exception(self):
        result = safe_call_with_timeout(lambda: 1 / 0, timeout_seconds=1.0, default=0, log_error=False)
        assert result == 0


class TestCircuitBreaker:
    """Test circuit breaker state machine."""

    def test_closed_by_default(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert not cb.is_open()

    def test_success_passes_through(self):
        cb = CircuitBreaker()
        result = cb.call(lambda: "success")
        assert result == "success"

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=3, timeout=timedelta(seconds=60))
        for _ in range(3):
            with pytest.raises(Exception):
                cb.call(self._fail)
        assert cb.is_open()

    def test_open_circuit_raises_immediately(self):
        cb = CircuitBreaker(failure_threshold=1, timeout=timedelta(seconds=60))
        with pytest.raises(Exception):
            cb.call(self._fail)
        assert cb.is_open()
        with pytest.raises(Exception, match="Circuit breaker is open"):
            cb.call(lambda: "should not execute")

    def test_reset_closes_circuit(self):
        cb = CircuitBreaker(failure_threshold=1, timeout=timedelta(seconds=60))
        with pytest.raises(Exception):
            cb.call(self._fail)
        assert cb.is_open()
        cb.reset()
        assert not cb.is_open()
        assert cb.call(lambda: "recovered") == "recovered"

    def test_failures_below_threshold_stay_closed(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            with pytest.raises(Exception):
                cb.call(self._fail)
        assert not cb.is_open()

    @staticmethod
    def _fail():
        raise Exception("deliberate failure")
