"""
Bridge between anima-mcp and unitares-governance MCP server.

Enables creature to check in with UNITARES governance system via HTTP/SSE.
Provides fallback local governance if UNITARES server is unavailable.
"""

import asyncio
import json
import sys
from typing import Optional, Dict, Any, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from .identity.store import CreatureIdentity

from .eisv_mapper import (
    EISVMetrics,
    anima_to_eisv,
    estimate_complexity,
    generate_status_text
)
from .anima import Anima
from .sensors.base import SensorReadings


class UnitaresBridge:
    """
    Connect anima creature to UNITARES governance.

    Supports:
    - HTTP/SSE connection to UNITARES server
    - Fallback local governance if server unavailable
    - Automatic retry and error handling
    - Connection pooling (reuses single aiohttp session)
    """

    def __init__(
        self,
        unitares_url: Optional[str] = None,
        agent_id: Optional[str] = None,
        timeout: float = 5.0
    ):
        """
        Initialize bridge.

        Args:
            unitares_url: URL to UNITARES governance server (e.g., "http://127.0.0.1:8767/mcp/")
                         If None, will use local governance only
            agent_id: Agent ID for UNITARES (auto-generated if None)
            timeout: Request timeout in seconds
        """
        self._url = unitares_url
        self._agent_id = agent_id
        self._timeout = timeout
        self._session_id = None
        self._available = None  # None = not checked, True/False = checked
        self._last_availability_check = None  # Timestamp of last check
        self._availability_check_interval = 60.0  # Recheck every 60 seconds if unavailable
        self._http_session = None  # Reusable aiohttp session
        self._session_timeout = None  # Timeout config for session

    async def _get_session(self):
        """Get or create reusable HTTP session."""
        if self._http_session is None or self._http_session.closed:
            import aiohttp
            # Create session with connection pooling
            connector = aiohttp.TCPConnector(
                limit=5,  # Max 5 concurrent connections
                limit_per_host=3,  # Max 3 per host
                ttl_dns_cache=300,  # Cache DNS for 5 min
                keepalive_timeout=30,  # Keep connections alive
            )
            self._session_timeout = aiohttp.ClientTimeout(total=self._timeout)
            self._http_session = aiohttp.ClientSession(
                timeout=self._session_timeout,
                connector=connector
            )
        return self._http_session

    async def close(self):
        """Close the HTTP session. Call when done with bridge."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None
        
    async def check_availability(self) -> bool:
        """
        Check if UNITARES server is available.

        Returns:
            True if server is reachable and accessible, False otherwise
        """
        if self._url is None:
            self._available = False
            return False

        # Recheck periodically if previously unavailable (allows recovery)
        import time
        current_time = time.time()
        if self._available is False and self._last_availability_check is not None:
            time_since_check = current_time - self._last_availability_check
            if time_since_check < self._availability_check_interval:
                # Still within cooldown, return cached result
                return False
            # Cooldown expired, reset cache to recheck
            self._available = None
        
        # If already available, return immediately (no need to recheck)
        if self._available is True:
            return True

        try:
            # Try to connect to UNITARES server using shared session
            session = await self._get_session()

            # Try health check or list_tools endpoint
            health_url = self._url.replace('/sse', '/health') if '/sse' in self._url else f"{self._url}/health"
            try:
                import aiohttp
                async with session.get(health_url, timeout=aiohttp.ClientTimeout(total=self._timeout)) as response:
                    if response.status == 200:
                        self._available = True
                        self._last_availability_check = current_time
                        return True
                    elif response.status == 401:
                        # OAuth/auth required - not accessible from this client
                        print(f"[UnitaresBridge] UNITARES requires authentication (401) - using local governance", file=sys.stderr, flush=True)
                        self._available = False
                        self._last_availability_check = current_time
                        return False
            except Exception as e:
                # Network/timeout errors - will retry later
                pass

            # If health check fails, try MCP endpoint
            if '/mcp' in self._url:
                mcp_url = self._url
            elif '/sse' in self._url:
                mcp_url = self._url.replace('/sse', '/mcp')
            else:
                mcp_url = f"{self._url}/mcp"
            try:
                import aiohttp
                async with session.post(
                    mcp_url,
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream"
                    },
                    timeout=aiohttp.ClientTimeout(total=self._timeout)
                ) as response:
                    if response.status == 200:
                        self._available = True
                        self._last_availability_check = current_time
                        return True
                    elif response.status == 401:
                        # OAuth/auth required - not accessible from this client
                        print(f"[UnitaresBridge] UNITARES requires authentication (401) - using local governance", file=sys.stderr, flush=True)
                        self._available = False
                        self._last_availability_check = current_time
                        return False
            except Exception as e:
                # Network/timeout errors - will retry later
                pass

            # Both checks failed - mark unavailable but allow retry
            self._available = False
            self._last_availability_check = current_time
            return False

        except ImportError:
            # aiohttp not available
            self._available = False
            return False
        except Exception:
            self._available = False
            return False
    
    async def check_in(
        self,
        anima: Anima,
        readings: SensorReadings,
        neural_weight: float = 0.3,
        physical_weight: float = 0.7,
        identity: Optional['CreatureIdentity'] = None,
        is_first_check_in: bool = False
    ) -> Dict[str, Any]:
        """
        Check in with UNITARES governance.

        Maps anima state to EISV metrics and requests governance decision.

        Args:
            anima: Anima state
            readings: Sensor readings (physical + neural)
            neural_weight: Weight for neural signals in EISV mapping
            physical_weight: Weight for physical signals in EISV mapping
            identity: Optional CreatureIdentity for metadata sync
            is_first_check_in: If True, syncs identity metadata to UNITARES

        Returns:
            Governance decision dict with:
            - action: "proceed" | "pause" | "halt"
            - margin: "comfortable" | "tight" | "critical"
            - reason: Human-readable explanation
            - eisv: EISV metrics used
            - source: "unitares" | "local" (which governance system responded)
        """
        # Debug: Log what we received
        print(f"[UnitaresBridge] check_in called: is_first_check_in={is_first_check_in}, identity={identity is not None}", file=sys.stderr, flush=True)

        # Map anima to EISV first (always needed)
        eisv = anima_to_eisv(anima, readings, neural_weight, physical_weight)

        # Check if UNITARES is available BEFORE trying to sync
        unitares_available = await self.check_availability()

        # Sync identity metadata on first check-in (only if UNITARES is available)
        if is_first_check_in and identity and unitares_available:
            print(f"[UnitaresBridge] First check-in - syncing identity for {identity.name if hasattr(identity, 'name') else 'unknown'}...", file=sys.stderr, flush=True)
            try:
                await self.sync_identity_metadata(identity)
            except Exception as e:
                # Non-fatal - continue with governance check-in
                print(f"[UnitaresBridge] Identity sync exception: {e}", file=sys.stderr, flush=True)

        # Check if UNITARES is available
        if unitares_available:
            try:
                print(f"[UnitaresBridge] Calling UNITARES (agent_id={self._agent_id[:8] if self._agent_id else 'None'})", file=sys.stderr, flush=True)
                result = await self._call_unitares(anima, readings, eisv, identity=identity)
                print(f"[UnitaresBridge] UNITARES responded: {result.get('source', 'unknown')}", file=sys.stderr, flush=True)
                return result
            except Exception as e:
                # Fallback to local governance on error
                print(f"[UnitaresBridge] UNITARES error, falling back to local: {e}", file=sys.stderr, flush=True)
                return self._local_governance(anima, readings, eisv, error=str(e))
        else:
            # Use local governance
            print("[UnitaresBridge] UNITARES not available, using local governance", file=sys.stderr, flush=True)
            return self._local_governance(anima, readings, eisv)
    
    async def _call_unitares(
        self,
        anima: Anima,
        readings: SensorReadings,
        eisv: EISVMetrics,
        identity: Optional['CreatureIdentity'] = None
    ) -> Dict[str, Any]:
        """Call UNITARES governance via HTTP/SSE."""
        try:
            # Prepare MCP request
            complexity = estimate_complexity(anima, readings)
            status_text = generate_status_text(anima, readings, eisv)
            
            # Build sensor_data payload
            sensor_data = {
                "eisv": eisv.to_dict(),
                "anima": {
                    "warmth": anima.warmth,
                    "clarity": anima.clarity,
                    "stability": anima.stability,
                    "presence": anima.presence
                }
            }
            
            # Include identity metadata if available
            if identity:
                sensor_data["identity"] = {
                    "total_awakenings": identity.total_awakenings if hasattr(identity, 'total_awakenings') else 0,
                    "total_alive_seconds": identity.total_alive_seconds if hasattr(identity, 'total_alive_seconds') else 0.0,
                    "alive_ratio": identity.alive_ratio() if hasattr(identity, 'alive_ratio') else 0.0,
                    "age_seconds": identity.age_seconds() if hasattr(identity, 'age_seconds') else 0.0,
                }
            
            # Build arguments for process_agent_update
            update_arguments = {
                "complexity": complexity,
                "response_text": status_text,
                "parameters": [{"key": "sensor_data", "value": json.dumps(sensor_data)}]
            }

            # Add trajectory signature if available (enables lineage tracking in UNITARES)
            try:
                from .trajectory import compute_trajectory_signature
                from .anima_history import get_anima_history
                from .self_model import get_self_model
                # Note: growth_system is global _growth in server.py, we get it if available
                growth_system = None
                try:
                    from . import _growth
                    growth_system = _growth
                except (ImportError, AttributeError):
                    pass

                trajectory_sig = compute_trajectory_signature(
                    growth_system=growth_system,
                    self_model=get_self_model(),
                    anima_history=get_anima_history(),
                )
                if trajectory_sig and trajectory_sig.observation_count > 0:
                    sig_dict = trajectory_sig.to_dict()
                    # Add identity_confidence for UNITARES
                    sig_dict["identity_confidence"] = getattr(trajectory_sig, 'identity_confidence', 0.0)
                    update_arguments["trajectory_signature"] = sig_dict
                    print(f"[UnitaresBridge] Including trajectory (obs={trajectory_sig.observation_count}, conf={sig_dict.get('identity_confidence', 0):.2f})", file=sys.stderr, flush=True)
            except Exception as e:
                # Non-blocking - trajectory is optional enhancement
                print(f"[UnitaresBridge] Trajectory not available: {e}", file=sys.stderr, flush=True)

            # MCP JSON-RPC request
            mcp_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "process_agent_update",
                    "arguments": update_arguments
                }
            }
            
            # Determine endpoint URL
            if '/mcp' in self._url:
                mcp_url = self._url  # Already has /mcp
            elif '/sse' in self._url:
                mcp_url = self._url.replace('/sse', '/mcp')
            else:
                mcp_url = f"{self._url}/mcp"
            
            # Build headers with identity for proper UNITARES binding
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",  # Required by MCP SSE servers
                "X-Session-ID": self._session_id or "anima-creature"
            }
            # Add agent ID header if set (for proper identity binding in UNITARES)
            if self._agent_id:
                headers["X-Agent-Id"] = self._agent_id

            # Use shared session for connection pooling
            session = await self._get_session()
            async with session.post(
                mcp_url,
                json=mcp_request,
                headers=headers
            ) as response:
                if response.status == 200:
                    # Handle SSE response format (text/event-stream)
                    content_type = response.headers.get("Content-Type", "")
                    if "text/event-stream" in content_type:
                        # Parse SSE format: "event: message\ndata: {...}\n\n"
                        text = await response.text()
                        result = None
                        for line in text.split("\n"):
                            if line.startswith("data: "):
                                try:
                                    result = json.loads(line[6:])
                                    break
                                except json.JSONDecodeError:
                                    continue
                        if not result:
                            raise Exception("No valid JSON data in SSE response")
                    else:
                        result = await response.json()

                    # Parse MCP response
                    if "result" in result:
                        governance_result = result["result"]
                        # MCP wraps tool results in content[0]["text"] as JSON string
                        if "content" in governance_result and governance_result["content"]:
                            content = governance_result["content"][0]
                            if content.get("type") == "text" and content.get("text"):
                                try:
                                    governance_result = json.loads(content["text"])
                                except json.JSONDecodeError:
                                    pass  # Keep original if not JSON
                        # Log response structure to understand agent binding
                        print(f"[UnitaresBridge] Response keys: {list(governance_result.keys())}", file=sys.stderr, flush=True)
                        # Log agent binding info from UNITARES
                        bound_id = governance_result.get("resolved_agent_id") or governance_result.get("agent_signature", {}).get("agent_id")
                        print(f"[UnitaresBridge] Bound to agent: {bound_id[:8] if bound_id else 'not specified'}", file=sys.stderr, flush=True)

                        # Extract action and margin from UNITARES response
                        # UNITARES returns: {"action": "proceed", "margin": "comfortable", ...}
                        return {
                            "action": governance_result.get("action", "proceed"),
                            "margin": governance_result.get("margin", "comfortable"),
                            "reason": governance_result.get("reason", "Governance check completed"),
                            "eisv": eisv.to_dict(),
                            "source": "unitares",
                            "unitares_agent_id": bound_id,  # For display identification
                            "raw_response": governance_result
                        }
                    elif "error" in result:
                        raise Exception(f"MCP error: {result['error']}")
                else:
                    # HTTP error - fallback to local
                    error_text = await response.text()
                    raise Exception(f"HTTP {response.status}: {error_text}")
                        
        except ImportError:
            # aiohttp not available
            raise Exception("aiohttp not installed - cannot connect to UNITARES")
        except asyncio.TimeoutError:
            raise Exception("Timeout connecting to UNITARES server")
        except Exception as e:
            raise Exception(f"Error calling UNITARES: {e}")
    
    def _local_governance(
        self,
        anima: Anima,
        readings: SensorReadings,
        eisv: EISVMetrics,
        error: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Local governance decision (fallback if UNITARES unavailable).
        
        Uses simple thresholds based on EISV metrics.
        """
        # Compute signed margins (positive = within bounds, negative = crossed)
        # UNITARES thresholds (from governance_config.py):
        RISK_THRESHOLD = 0.60
        COHERENCE_THRESHOLD = 0.40
        VOID_THRESHOLD = 0.15

        # Signed margins: positive = room to threshold, negative = past threshold
        margins = {
            "risk": RISK_THRESHOLD - eisv.entropy,        # Higher entropy is worse
            "coherence": eisv.integrity - COHERENCE_THRESHOLD,  # Lower integrity is worse
            "void": VOID_THRESHOLD - eisv.void            # Higher void is worse
        }

        # Check if any threshold crossed
        crossed = {k: v for k, v in margins.items() if v < 0}
        valid = {k: v for k, v in margins.items() if v >= 0}

        if crossed:
            # At least one threshold crossed
            worst_edge = min(crossed.items(), key=lambda x: x[1])[0]
            distance_past = abs(crossed[worst_edge])

            # warning: just crossed (< 0.1 past), critical: deep past (>= 0.1)
            if distance_past >= 0.1:
                margin = "critical"
            else:
                margin = "warning"

            action = "pause"
            reason = f"Crossed {worst_edge} threshold by {distance_past:.2f}"
            nearest_edge = worst_edge
        else:
            # All within bounds - find nearest edge
            nearest_edge = min(valid.items(), key=lambda x: x[1])[0]
            distance_to = valid[nearest_edge]

            # comfortable: > 0.15 from edge, tight: <= 0.15
            if distance_to > 0.15:
                margin = "comfortable"
            else:
                margin = "tight"

            action = "proceed"
            reason = f"State healthy (margin: {margin})"
        
        if error:
            reason += f" [UNITARES unavailable: {error}]"
        
        return {
            "action": action,
            "margin": margin,
            "reason": reason,
            "eisv": eisv.to_dict(),
            "source": "local",
            "nearest_edge": nearest_edge
        }
    
    def set_agent_id(self, agent_id: str):
        """Set agent ID for UNITARES."""
        self._agent_id = agent_id
    
    def set_session_id(self, session_id: str):
        """Set session ID for UNITARES connection."""
        self._session_id = session_id
    
    async def sync_name(self, name: str) -> bool:
        """
        Sync Lumen's name to UNITARES label.
        
        Args:
            name: Lumen's chosen name
            
        Returns:
            True if synced successfully, False otherwise
        """
        if not self._url or not self._agent_id:
            return False
        
        try:
            # Call UNITARES identity tool to set label
            # Note: update_agent_metadata doesn't set label directly
            # We need to use identity(name=...) tool instead
            mcp_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "identity",
                    "arguments": {
                        "name": name
                    }
                }
            }

            mcp_url = self._url.replace('/sse', '/mcp') if '/sse' in self._url else f"{self._url}/mcp"
            headers = {
                "Content-Type": "application/json",
                "X-Session-ID": self._session_id or "anima-creature"
            }
            if self._agent_id:
                headers["X-Agent-Id"] = self._agent_id

            # Use shared session for connection pooling
            session = await self._get_session()
            async with session.post(mcp_url, json=mcp_request, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    return "result" in result and "error" not in result
            return False
        except Exception:
            # Non-fatal - name sync is optional
            return False
    
    async def sync_identity_metadata(self, identity: 'CreatureIdentity') -> bool:
        """
        Sync Lumen's identity metadata to UNITARES.
        
        Includes birth date, runtime metrics, and name history.
        Called on first check-in to ensure UNITARES has full context.
        
        Args:
            identity: CreatureIdentity object
            
        Returns:
            True if synced successfully, False otherwise
        """
        if not self._url or not self._agent_id:
            return False
        
        try:
            # Build metadata payload
            metadata = {
                "born_at": identity.born_at.isoformat() if hasattr(identity, 'born_at') else None,
                "total_awakenings": identity.total_awakenings if hasattr(identity, 'total_awakenings') else 0,
                "total_alive_seconds": identity.total_alive_seconds if hasattr(identity, 'total_alive_seconds') else 0.0,
                "alive_ratio": identity.alive_ratio() if hasattr(identity, 'alive_ratio') else 0.0,
                "name_history": identity.name_history if hasattr(identity, 'name_history') else [],
                "current_awakening_at": identity.current_awakening_at.isoformat() if hasattr(identity, 'current_awakening_at') and identity.current_awakening_at else None,
            }

            # Get creature name for labeling
            creature_name = identity.name if hasattr(identity, 'name') and identity.name else "Anima"
            creature_id = identity.creature_id if hasattr(identity, 'creature_id') else "unknown"

            # Call UNITARES update_agent_metadata tool - label ourselves!
            mcp_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "update_agent_metadata",
                    "arguments": {
                        # Don't pass agent_id - let session binding handle it
                        "purpose": f"{creature_name} - embodied digital creature (creature_id: {creature_id[:8]}...)",
                        "tags": [creature_name.lower(), "anima", "creature", "embodied", "autonomous"],
                        "preferences": metadata,
                        "notes": f"{creature_name} identity: creature_id={creature_id}, born={metadata.get('born_at')}, awakenings={metadata.get('total_awakenings')}"
                    }
                }
            }

            mcp_url = self._url.replace('/sse', '/mcp') if '/sse' in self._url else f"{self._url}/mcp"
            headers = {
                "Content-Type": "application/json",
                "X-Session-ID": self._session_id or "anima-creature",
                "Accept": "application/json, text/event-stream"
            }
            if self._agent_id:
                headers["X-Agent-Id"] = self._agent_id

            print(f"[UnitaresBridge] Syncing identity metadata for {creature_name}...", file=sys.stderr, flush=True)

            # Use shared session for connection pooling
            session = await self._get_session()
            async with session.post(mcp_url, json=mcp_request, headers=headers) as response:
                if response.status == 200:
                    # Handle SSE response format
                    content_type = response.headers.get("Content-Type", "")
                    if "text/event-stream" in content_type:
                        text = await response.text()
                        result = None
                        for line in text.split("\n"):
                            if line.startswith("data: "):
                                try:
                                    result = json.loads(line[6:])
                                    break
                                except json.JSONDecodeError:
                                    continue
                    else:
                        result = await response.json()

                    if result and "result" in result and "error" not in result:
                        print(f"[UnitaresBridge] Identity sync SUCCESS - {creature_name} labeled in UNITARES", file=sys.stderr, flush=True)
                        return True
                    else:
                        error = result.get('error', 'unknown') if result else 'no response'
                        print(f"[UnitaresBridge] Identity sync failed: {error}", file=sys.stderr, flush=True)
                else:
                    print(f"[UnitaresBridge] Identity sync HTTP error: {response.status}", file=sys.stderr, flush=True)
            return False
        except Exception as e:
            # Non-fatal - metadata sync is optional
            print(f"[UnitaresBridge] Identity sync error: {e}", file=sys.stderr, flush=True)
            return False


# Convenience function for common use case
async def check_governance(
    anima: Anima,
    readings: SensorReadings,
    unitares_url: Optional[str] = None,
    neural_weight: float = 0.3,
    physical_weight: float = 0.7
) -> Dict[str, Any]:
    """
    Convenience function to check governance.
    
    Args:
        anima: Anima state
        readings: Sensor readings
        unitares_url: Optional UNITARES server URL
        neural_weight: Weight for neural signals
        physical_weight: Weight for physical signals
    
    Returns:
        Governance decision dict
    """
    bridge = UnitaresBridge(unitares_url=unitares_url)
    return await bridge.check_in(anima, readings, neural_weight, physical_weight)

