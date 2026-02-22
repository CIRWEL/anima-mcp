"""
Shared Memory Client for Anima Hardware Broker.

Implements a shared memory layer for data exchange between Broker and MCP.
Uses JSON files in /dev/shm (RAM disk) for fast, atomic data exchange.

Usage:
    client = SharedMemoryClient(mode="write", backend="file")
    client.write(data)
"""

import fcntl
import json
import sys
import os
import time
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

# Default path for shared memory file
SHM_DIR = Path("/dev/shm") if Path("/dev/shm").exists() else Path("/tmp")
SHM_FILE = SHM_DIR / "anima_state.json"

class SharedMemoryClient:
    """
    Client for reading/writing anima state to shared memory.
    """

    def __init__(self, mode: str = "read", backend: str = "file", filepath: Path = SHM_FILE):
        """
        Initialize shared memory client.

        Args:
            mode: "read" or "write"
            backend: "file" (kept for API compatibility)
            filepath: Path to shared memory file
        """
        self.mode = mode
        self.filepath = filepath
        self.backend = "file"
        self._ensure_file_dir()
        print(f"[SharedMemory] Initialized with backend: {self.backend}", file=sys.stderr, flush=True)

    def _ensure_file_dir(self):
        """Ensure directory exists for file backend."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

    def write(self, data: Dict[str, Any]) -> bool:
        """Write data to shared memory."""
        if self.mode != "write":
            raise PermissionError("Client initialized in read-only mode")

        envelope = {
            "updated_at": datetime.now().isoformat(),
            "pid": os.getpid(),
            "data": data
        }

        return self._write_file(envelope)

    def _write_file(self, envelope: Dict[str, Any]) -> bool:
        """Write to file implementation with file locking."""
        lock_path = self.filepath.with_suffix(".lock")
        try:
            # Use "a" mode to avoid truncation race when multiple processes open lock file
            with open(lock_path, "a") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)  # Exclusive lock
                try:
                    temp_path = self.filepath.with_suffix(".tmp")
                    with open(temp_path, "w") as f:
                        json.dump(envelope, f)
                        f.flush()
                        os.fsync(f.fileno())
                    temp_path.replace(self.filepath)
                    return True
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except Exception as e:
            print(f"[SharedMemory] File write error: {e}", file=sys.stderr, flush=True)
            return False

    def read(self) -> Optional[Dict[str, Any]]:
        """Read data from shared memory (non-blocking, safe for concurrent access)."""
        return self._read_file()

    def _read_file(self, retries: int = 3) -> Optional[Dict[str, Any]]:
        """Read from file implementation with non-blocking file locking and retry logic."""
        lock_path = self.filepath.with_suffix(".lock")
        last_error = None
        error_count = 0

        for attempt in range(retries):
            try:
                if not self.filepath.exists():
                    return None

                # Use "a" mode to avoid truncation race when multiple processes open lock file
                # Try non-blocking lock first (LOCK_SH | LOCK_NB)
                with open(lock_path, "a") as lock_file:
                    try:
                        # Non-blocking shared lock - don't wait if locked
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                    except BlockingIOError:
                        # Lock is held - wait briefly then retry (for first attempt only)
                        if attempt == 0:
                            time.sleep(0.01)  # 10ms wait
                            continue
                        else:
                            # After first retry, return None rather than blocking
                            return None

                    try:
                        with open(self.filepath, "r") as f:
                            envelope = json.load(f)
                        return envelope.get("data")
                    finally:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

            except json.JSONDecodeError as e:
                last_error = e
                error_count += 1
                # JSON corruption - wait with exponential backoff
                # Broker writes ~every 200ms, so backoff: 50ms, 100ms, 150ms, 200ms
                if attempt < retries - 1:
                    time.sleep(0.05 * (attempt + 1))
                continue
            except Exception as e:
                last_error = e
                error_count += 1
                break

        # Only log persistent failures (>2 retries), not transient single-attempt errors
        if last_error and error_count > 2:
            print(f"[SharedMemory] File read error after {error_count} attempts: {last_error}", file=sys.stderr, flush=True)
        return None

    def clear(self):
        """Clear shared memory."""
        if self.mode == "write":
            if self.filepath.exists():
                try:
                    self.filepath.unlink()
                except OSError:
                    pass
