"""
UNITARES Cognitive Integration - Dialectic and Knowledge Graph operations.

Bridges Lumen's cognitive inference to UNITARES for:
1. Dialectic review sessions - structured reasoning with governance
2. Knowledge graph queries - search shared knowledge
3. Knowledge graph maintenance - store, update, cleanup

Uses MCP JSON-RPC protocol to call UNITARES tools.
"""

import os
import asyncio
import json
from typing import Optional, Dict, Any, List
from datetime import datetime


class UnitaresCognitive:
    """
    UNITARES MCP client for cognitive operations.

    Handles dialectic sessions and knowledge graph operations.
    """

    def __init__(self, unitares_url: Optional[str] = None):
        """
        Initialize with UNITARES URL.

        Args:
            unitares_url: UNITARES MCP endpoint (or from UNITARES_URL env)
        """
        self._url = unitares_url or os.environ.get("UNITARES_URL")
        self._agent_id = os.environ.get("ANIMA_ID")
        self._session_id: Optional[str] = None

        if self._agent_id:
            self._session_id = f"anima-{self._agent_id[:8]}"

    @property
    def enabled(self) -> bool:
        """Check if UNITARES is configured."""
        return bool(self._url)

    def set_agent_id(self, agent_id: str):
        """Set the agent ID for requests."""
        self._agent_id = agent_id
        self._session_id = f"anima-{agent_id[:8]}"

    def _get_mcp_url(self) -> str:
        """Get the MCP endpoint URL."""
        if not self._url:
            raise ValueError("UNITARES_URL not configured")

        if '/mcp' in self._url:
            return self._url
        elif '/sse' in self._url:
            return self._url.replace('/sse', '/mcp')
        else:
            return f"{self._url}/mcp"

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for MCP requests."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._agent_id:
            headers["X-Agent-Id"] = self._agent_id
        if self._session_id:
            headers["X-Session-ID"] = self._session_id
        return headers

    async def _call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: float = 10.0
    ) -> Optional[Dict[str, Any]]:
        """
        Call a UNITARES MCP tool.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            timeout: Request timeout in seconds

        Returns:
            Tool result or None if failed
        """
        if not self.enabled:
            return None

        try:
            import aiohttp
        except ImportError:
            print("[UnitaresCognitive] aiohttp not installed", flush=True)
            return None

        # Inject client_session_id for stable identity binding across restarts
        if "client_session_id" not in arguments and self._agent_id:
            arguments["client_session_id"] = f"lumen-{self._agent_id}"

        mcp_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.post(
                    self._get_mcp_url(),
                    json=mcp_request,
                    headers=self._get_headers()
                ) as response:
                    if response.status == 200:
                        content_type = response.headers.get("Content-Type", "")

                        if "text/event-stream" in content_type:
                            # Parse SSE response
                            text = await response.text()
                            for line in text.split("\n"):
                                if line.startswith("data: "):
                                    try:
                                        data = json.loads(line[6:])
                                        if "result" in data:
                                            return data["result"]
                                    except json.JSONDecodeError:
                                        continue
                        else:
                            # Regular JSON response
                            data = await response.json()
                            if "result" in data:
                                return data["result"]

                    return None
        except asyncio.TimeoutError:
            print(f"[UnitaresCognitive] Timeout calling {tool_name}", flush=True)
            return None
        except Exception as e:
            print(f"[UnitaresCognitive] Error calling {tool_name}: {e}", flush=True)
            return None

    # ==================== Dialectic Operations ====================

    async def request_dialectic_review(
        self,
        thesis: str,
        context: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Request a dialectic review session from UNITARES.

        Args:
            thesis: The proposition to examine dialectically
            context: Optional background context
            tags: Optional categorization tags

        Returns:
            Session info with session_id for follow-up
        """
        arguments = {
            "summary": thesis,
            "tags": tags or ["dialectic", "lumen"],
        }

        if context:
            arguments["content"] = json.dumps({
                "context": context,
                "requested_at": datetime.now().isoformat(),
                "agent": self._agent_id
            })

        return await self._call_tool("request_dialectic_review", arguments)

    async def get_dialectic_session(
        self,
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get the state of a dialectic session.

        Args:
            session_id: The session to retrieve

        Returns:
            Session state including synthesis if complete
        """
        return await self._call_tool("get_dialectic_session", {
            "session_id": session_id
        })

    # ==================== Knowledge Graph Operations ====================

    async def store_knowledge(
        self,
        summary: str,
        discovery_type: str = "insight",
        tags: Optional[List[str]] = None,
        content: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Store knowledge in the UNITARES knowledge graph.

        Args:
            summary: The insight/knowledge to store
            discovery_type: Type (insight, observation, pattern, note)
            tags: Categorization tags
            content: Additional structured content

        Returns:
            Storage confirmation with entry_id
        """
        final_tags = ["lumen", "embodied"]
        if tags:
            final_tags.extend(tags)

        arguments = {
            "summary": summary,
            "discovery_type": discovery_type,
            "tags": final_tags,
        }

        if content:
            arguments["content"] = json.dumps({
                **content,
                "source": "lumen_cognitive",
                "timestamp": datetime.now().isoformat()
            })

        return await self._call_tool("store_knowledge_graph", arguments)

    async def search_knowledge(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        limit: int = 10
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Search the UNITARES knowledge graph.

        Args:
            query: Search query text
            tags: Optional tag filter
            limit: Maximum results to return

        Returns:
            List of matching knowledge entries
        """
        arguments = {
            "query": query,
            "limit": limit
        }

        if tags:
            arguments["tags"] = tags

        result = await self._call_tool("search_knowledge_graph", arguments)

        if result and isinstance(result, dict):
            return result.get("entries", [])

        return result if isinstance(result, list) else None

    async def get_knowledge(
        self,
        entry_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get a specific knowledge graph entry.

        Args:
            entry_id: The entry to retrieve

        Returns:
            Full knowledge entry
        """
        return await self._call_tool("get_knowledge_graph", {
            "entry_id": entry_id
        })

    async def list_knowledge(
        self,
        tags: Optional[List[str]] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Optional[List[Dict[str, Any]]]:
        """
        List knowledge graph entries.

        Args:
            tags: Optional tag filter
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of knowledge entries
        """
        arguments = {
            "limit": limit,
            "offset": offset
        }

        if tags:
            arguments["tags"] = tags

        result = await self._call_tool("list_knowledge_graph", arguments)

        if result and isinstance(result, dict):
            return result.get("entries", [])

        return result if isinstance(result, list) else None

    async def cleanup_knowledge(
        self,
        older_than_days: int = 30,
        dry_run: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Clean up old or duplicate knowledge entries.

        Args:
            older_than_days: Entries older than this may be cleaned
            dry_run: If True, only report what would be cleaned

        Returns:
            Cleanup report
        """
        return await self._call_tool("cleanup_knowledge_graph", {
            "older_than_days": older_than_days,
            "dry_run": dry_run
        })

    # ==================== Discovery Status ====================

    async def update_discovery_status(
        self,
        discovery_id: str,
        status: str,
        notes: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Update the status of a discovery/insight.

        Args:
            discovery_id: The discovery to update
            status: New status (pending, verified, deprecated, etc.)
            notes: Optional status notes

        Returns:
            Update confirmation
        """
        arguments = {
            "discovery_id": discovery_id,
            "status": status
        }

        if notes:
            arguments["notes"] = notes

        return await self._call_tool("update_discovery_status_graph", arguments)

    async def leave_note(
        self,
        note: str,
        tags: Optional[List[str]] = None,
        related_to: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Leave a note in the knowledge graph.

        Args:
            note: The note content
            tags: Categorization tags
            related_to: Optional entry_id this note relates to

        Returns:
            Note confirmation with entry_id
        """
        arguments = {
            "note": note,
            "tags": tags or ["lumen", "note"]
        }

        if related_to:
            arguments["related_to"] = related_to

        return await self._call_tool("leave_note", arguments)


# Singleton instance
_unitares_cognitive: Optional[UnitaresCognitive] = None


def get_unitares_cognitive(unitares_url: Optional[str] = None) -> UnitaresCognitive:
    """Get the UNITARES cognitive singleton."""
    global _unitares_cognitive
    if _unitares_cognitive is None:
        _unitares_cognitive = UnitaresCognitive(unitares_url)
    return _unitares_cognitive


# ==================== High-Level Cognitive Functions ====================

async def dialectic_review(
    thesis: str,
    context: Optional[str] = None,
    wait_for_result: bool = False,
    timeout: float = 30.0
) -> Optional[Dict[str, Any]]:
    """
    Request dialectic review from UNITARES with optional wait.

    Args:
        thesis: The proposition to examine
        context: Optional background
        wait_for_result: If True, poll until synthesis complete
        timeout: Max wait time in seconds

    Returns:
        Session result (may include synthesis if wait_for_result)
    """
    cognitive = get_unitares_cognitive()

    # Request the review
    result = await cognitive.request_dialectic_review(thesis, context)

    if not result or not wait_for_result:
        return result

    # Poll for completion
    session_id = result.get("session_id")
    if not session_id:
        return result

    start_time = asyncio.get_event_loop().time()

    while asyncio.get_event_loop().time() - start_time < timeout:
        await asyncio.sleep(2.0)  # Poll every 2 seconds

        session = await cognitive.get_dialectic_session(session_id)
        if session and session.get("status") == "complete":
            return session

    return result  # Return original result if timeout


async def search_shared_knowledge(
    query: str,
    include_local: bool = True
) -> List[Dict[str, Any]]:
    """
    Search both UNITARES and local knowledge.

    Args:
        query: Search query
        include_local: Also search local knowledge store

    Returns:
        Combined results from both sources
    """
    results = []

    # Search UNITARES
    cognitive = get_unitares_cognitive()
    if cognitive.enabled:
        unitares_results = await cognitive.search_knowledge(query)
        if unitares_results:
            for r in unitares_results:
                r["source"] = "unitares"
                results.append(r)

    # Search local knowledge
    if include_local:
        try:
            from .knowledge import get_relevant_insights
            local_insights = get_relevant_insights(query, limit=5)
            for insight in local_insights:
                results.append({
                    "summary": insight.text,
                    "source": "local",
                    "category": insight.category,
                    "confidence": insight.confidence,
                    "timestamp": insight.timestamp.isoformat() if insight.timestamp else None
                })
        except Exception:
            pass

    return results


async def share_synthesis(
    synthesis: Dict[str, Any],
    tags: Optional[List[str]] = None
) -> Optional[Dict[str, Any]]:
    """
    Share a dialectic synthesis to the knowledge graph.

    Args:
        synthesis: The synthesis result (from cognitive_inference)
        tags: Additional tags

    Returns:
        Storage confirmation
    """
    cognitive = get_unitares_cognitive()

    # Format the synthesis
    if "synthesis" in synthesis:
        summary = synthesis["synthesis"]
    elif "merged_insight" in synthesis:
        summary = synthesis["merged_insight"]
    elif "text" in synthesis:
        summary = synthesis["text"]
    else:
        return None

    final_tags = ["synthesis", "dialectic"]
    if tags:
        final_tags.extend(tags)

    return await cognitive.store_knowledge(
        summary=summary,
        discovery_type="insight",
        tags=final_tags,
        content={
            "full_synthesis": synthesis,
            "synthesis_type": "dialectic" if "thesis" in synthesis else "merged"
        }
    )
