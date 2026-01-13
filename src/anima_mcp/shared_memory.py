"""
Shared Memory Client for Anima Hardware Broker.

Implements a shared memory layer for data exchange between Broker and MCP.
Supports two backends:
1. Redis (Preferred): Fast, atomic, supports Pub/Sub (future proofing).
2. File (Fallback): JSON files in /dev/shm (RAM disk).

Usage:
    client = SharedMemoryClient(mode="write", backend="redis")
    client.write(data)
"""

import json
import os
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

# Default path for shared memory file (fallback)
SHM_DIR = Path("/dev/shm") if Path("/dev/shm").exists() else Path("/tmp")
SHM_FILE = SHM_DIR / "anima_state.json"

# Redis Config
REDIS_HOST = os.environ.get("ANIMA_REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("ANIMA_REDIS_PORT", 6379))
REDIS_KEY = "anima:state"

class SharedMemoryClient:
    """
    Client for reading/writing anima state to shared memory.
    """
    
    def __init__(self, mode: str = "read", backend: str = "auto", filepath: Path = SHM_FILE):
        """
        Initialize shared memory client.
        
        Args:
            mode: "read" or "write"
            backend: "redis", "file", or "auto" (tries Redis, falls back to file)
            filepath: Path to shared memory file (for file backend)
        """
        self.mode = mode
        self.filepath = filepath
        self._redis_client = None
        
        # Determine backend
        if backend == "auto":
            self.backend = "redis" if HAS_REDIS and self._check_redis() else "file"
        else:
            self.backend = backend

        if self.backend == "redis" and not HAS_REDIS:
            print("[SharedMemory] Redis requested but 'redis' package not installed. Falling back to file.")
            self.backend = "file"

        # Initialize backend
        if self.backend == "redis":
            try:
                self._redis_client = redis.Redis(
                    host=REDIS_HOST, 
                    port=REDIS_PORT, 
                    decode_responses=True,
                    socket_connect_timeout=1
                )
                self._redis_client.ping() # Test connection
            except Exception as e:
                print(f"[SharedMemory] Redis connection failed: {e}. Falling back to file.")
                self.backend = "file"
                self._ensure_file_dir()
        else:
            self._ensure_file_dir()
            
        print(f"[SharedMemory] Initialized with backend: {self.backend}")

    def _check_redis(self) -> bool:
        """Check if Redis server is reachable."""
        try:
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, socket_connect_timeout=0.5)
            return r.ping()
        except:
            return False

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

        if self.backend == "redis" and self._redis_client:
            try:
                self._redis_client.set(REDIS_KEY, json.dumps(envelope))
                return True
            except Exception as e:
                print(f"[SharedMemory] Redis write error: {e}")
                return False
        else:
            return self._write_file(envelope)

    def _write_file(self, envelope: Dict[str, Any]) -> bool:
        """Write to file implementation."""
        try:
            temp_path = self.filepath.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                json.dump(envelope, f)
                f.flush()
                os.fsync(f.fileno())
            temp_path.replace(self.filepath)
            return True
        except Exception as e:
            print(f"[SharedMemory] File write error: {e}")
            return False

    def read(self) -> Optional[Dict[str, Any]]:
        """Read data from shared memory."""
        if self.backend == "redis" and self._redis_client:
            try:
                data_str = self._redis_client.get(REDIS_KEY)
                if data_str:
                    envelope = json.loads(str(data_str))
                    return envelope.get("data")
                return None
            except Exception as e:
                print(f"[SharedMemory] Redis read error: {e}")
                # Optional: Fallback to file reading? For now, just fail.
                return None
        else:
            return self._read_file()

    def _read_file(self) -> Optional[Dict[str, Any]]:
        """Read from file implementation."""
        try:
            if not self.filepath.exists():
                return None
            with open(self.filepath, "r") as f:
                envelope = json.load(f)
            return envelope.get("data")
        except (json.JSONDecodeError, Exception) as e:
            print(f"[SharedMemory] File read error: {e}")
            return None

    def clear(self):
        """Clear shared memory."""
        if self.mode == "write":
            if self.backend == "redis" and self._redis_client:
                try:
                    self._redis_client.delete(REDIS_KEY)
                except:
                    pass
            
            if self.filepath.exists():
                try:
                    self.filepath.unlink()
                except:
                    pass
