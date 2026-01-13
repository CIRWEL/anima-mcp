"""
Error Recovery System - Robust handling of transient and permanent failures.

Provides:
- Retry logic with exponential backoff
- Circuit breaker pattern for persistent failures
- Error classification (transient vs permanent)
- Specific exception types for different failure modes
"""

import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Callable, TypeVar, Any
from enum import Enum
from dataclasses import dataclass, field


class ErrorType(Enum):
    """Classification of error types."""
    TRANSIENT = "transient"  # Temporary, should retry
    PERMANENT = "permanent"  # Persistent, don't retry
    HARDWARE = "hardware"    # Hardware failure, may recover
    NETWORK = "network"      # Network issue, transient
    CONFIG = "config"        # Configuration error, permanent


@dataclass
class RetryConfig:
    """Configuration for retry logic."""
    max_attempts: int = 3
    initial_delay: float = 0.1  # seconds
    max_delay: float = 5.0  # seconds
    exponential_base: float = 2.0
    jitter: bool = True  # Add randomness to prevent thundering herd


@dataclass
class CircuitBreakerState:
    """State for circuit breaker pattern."""
    failures: int = 0
    last_failure_time: Optional[datetime] = None
    state: str = "closed"  # closed, open, half_open
    failure_threshold: int = 5
    timeout: timedelta = field(default_factory=lambda: timedelta(seconds=60))
    success_threshold: int = 2  # Successes needed to close circuit


T = TypeVar('T')


class TransientError(Exception):
    """Transient error that should be retried."""
    pass


class PermanentError(Exception):
    """Permanent error that should not be retried."""
    pass


class HardwareError(Exception):
    """Hardware-related error."""
    pass


class RetryableError(Exception):
    """Base class for errors that can be retried."""
    error_type: ErrorType = ErrorType.TRANSIENT


def classify_error(error: Exception) -> ErrorType:
    """
    Classify an exception into an error type.
    
    Args:
        error: The exception to classify
    
    Returns:
        ErrorType classification
    """
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()
    
    # Hardware errors
    if any(x in error_str for x in ['i2c', 'spi', 'gpio', 'device', 'sensor', 'hardware']):
        return ErrorType.HARDWARE
    
    # Network errors
    if any(x in error_str for x in ['network', 'connection', 'timeout', 'unreachable']):
        return ErrorType.NETWORK
    
    # Config errors
    if any(x in error_str for x in ['config', 'invalid', 'missing', 'not found']):
        return ErrorType.CONFIG
    
    # Default to transient for unknown errors
    return ErrorType.TRANSIENT


def retry_with_backoff(
    func: Callable[[], T],
    config: Optional[RetryConfig] = None,
    error_filter: Optional[Callable[[Exception], bool]] = None
) -> T:
    """
    Retry a function with exponential backoff.
    
    Args:
        func: Function to retry (no arguments)
        config: Retry configuration
        error_filter: Optional function to filter which errors to retry
    
    Returns:
        Function result
    
    Raises:
        Last exception if all retries fail
    """
    if config is None:
        config = RetryConfig()
    
    last_error = None
    
    for attempt in range(config.max_attempts):
        try:
            return func()
        except Exception as e:
            last_error = e
            
            # Check if we should retry this error
            if error_filter and not error_filter(e):
                raise
            
            # Check error type
            error_type = classify_error(e)
            if error_type == ErrorType.PERMANENT or error_type == ErrorType.CONFIG:
                raise
            
            # Don't retry on last attempt
            if attempt == config.max_attempts - 1:
                break
            
            # Calculate delay with exponential backoff
            delay = min(
                config.initial_delay * (config.exponential_base ** attempt),
                config.max_delay
            )
            
            # Add jitter to prevent thundering herd
            if config.jitter:
                import random
                delay = delay * (0.5 + random.random() * 0.5)
            
            time.sleep(delay)
    
    # All retries failed
    raise last_error


async def retry_with_backoff_async(
    func: Callable[[], T],
    config: Optional[RetryConfig] = None,
    error_filter: Optional[Callable[[Exception], bool]] = None
) -> T:
    """
    Retry an async function with exponential backoff.
    
    Args:
        func: Async function to retry (no arguments)
        config: Retry configuration
        error_filter: Optional function to filter which errors to retry
    
    Returns:
        Function result
    
    Raises:
        Last exception if all retries fail
    """
    if config is None:
        config = RetryConfig()
    
    last_error = None
    
    for attempt in range(config.max_attempts):
        try:
            return await func()
        except Exception as e:
            last_error = e
            
            # Check if we should retry this error
            if error_filter and not error_filter(e):
                raise
            
            # Check error type
            error_type = classify_error(e)
            if error_type == ErrorType.PERMANENT or error_type == ErrorType.CONFIG:
                raise
            
            # Don't retry on last attempt
            if attempt == config.max_attempts - 1:
                break
            
            # Calculate delay with exponential backoff
            delay = min(
                config.initial_delay * (config.exponential_base ** attempt),
                config.max_delay
            )
            
            # Add jitter to prevent thundering herd
            if config.jitter:
                import random
                delay = delay * (0.5 + random.random() * 0.5)
            
            await asyncio.sleep(delay)
    
    # All retries failed
    raise last_error


class CircuitBreaker:
    """
    Circuit breaker pattern for handling persistent failures.
    
    States:
    - closed: Normal operation, requests pass through
    - open: Too many failures, requests fail immediately
    - half_open: Testing if service recovered, limited requests allowed
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: timedelta = timedelta(seconds=60),
        success_threshold: int = 2
    ):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Failures needed to open circuit
            timeout: Time before attempting half-open
            success_threshold: Successes needed to close circuit
        """
        self.state = CircuitBreakerState(
            failure_threshold=failure_threshold,
            timeout=timeout,
            success_threshold=success_threshold
        )
    
    def call(self, func: Callable[[], T]) -> T:
        """
        Execute function through circuit breaker.
        
        Args:
            func: Function to execute
        
        Returns:
            Function result
        
        Raises:
            Exception if circuit is open or function fails
        """
        # Check circuit state
        if self.state.state == "open":
            # Check if timeout has passed
            if (self.state.last_failure_time and 
                datetime.now() - self.state.last_failure_time > self.state.timeout):
                self.state.state = "half_open"
                self.state.failures = 0
            else:
                raise Exception("Circuit breaker is open")
        
        # Try to execute
        try:
            result = func()
            
            # Success - update state
            if self.state.state == "half_open":
                # Count successes in half-open state
                # (simplified - would need success counter in real implementation)
                self.state.state = "closed"
                self.state.failures = 0
            
            return result
            
        except Exception as e:
            # Failure - update state
            self.state.failures += 1
            self.state.last_failure_time = datetime.now()
            
            if self.state.failures >= self.state.failure_threshold:
                self.state.state = "open"
            
            raise
    
    def reset(self):
        """Reset circuit breaker to closed state."""
        self.state.state = "closed"
        self.state.failures = 0
        self.state.last_failure_time = None
    
    def is_open(self) -> bool:
        """Check if circuit breaker is open."""
        return self.state.state == "open"


def safe_call(
    func: Callable[[], T],
    default: Optional[T] = None,
    log_error: bool = True
) -> Optional[T]:
    """
    Safely call a function, returning default on error.
    
    Args:
        func: Function to call
        default: Value to return on error
        log_error: If True, log errors to stderr
    
    Returns:
        Function result or default
    """
    try:
        return func()
    except Exception as e:
        if log_error:
            import sys
            import traceback
            print(f"[SafeCall] Error: {e}", file=sys.stderr, flush=True)
            # Print traceback for display errors to help debug
            if "display" in str(e).lower() or "render" in str(e).lower():
                traceback.print_exc(file=sys.stderr)
        return default


async def safe_call_async(
    func: Callable[[], T],
    default: Optional[T] = None,
    log_error: bool = True
) -> Optional[T]:
    """
    Safely call an async function, returning default on error.
    
    Args:
        func: Async function to call
        default: Value to return on error
        log_error: If True, log errors to stderr
    
    Returns:
        Function result or default
    """
    try:
        return await func()
    except Exception as e:
        if log_error:
            import sys
            print(f"[SafeCall] Error: {e}", file=sys.stderr, flush=True)
        return default
