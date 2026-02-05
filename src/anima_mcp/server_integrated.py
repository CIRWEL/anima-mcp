"""
Anima MCP server with UNITARES governance integration.

Extends base anima server with governance check-in capability.
Creature can check in with UNITARES governance system for proprioceptive feedback.

Usage:
    # With UNITARES integration
    anima --unitares http://127.0.0.1:8767/mcp/
    
    # Local governance only (fallback)
    anima
"""

import os
import json
from typing import Optional
from mcp.types import Tool, TextContent

from .server import (
    create_server as create_base_server,
    TOOLS as BASE_TOOLS,
    HANDLERS as BASE_HANDLERS,
    _get_store,
    _get_sensors,
    _anima_id
)
from .anima import sense_self
from .unitares_bridge import UnitaresBridge


# Global bridge instance
_bridge: Optional[UnitaresBridge] = None


def _get_bridge() -> Optional[UnitaresBridge]:
    """Get or create UNITARES bridge."""
    global _bridge
    if _bridge is None:
        unitares_url = os.environ.get("UNITARES_URL")
        if unitares_url:
            _bridge = UnitaresBridge(unitares_url=unitares_url)
            # Set agent ID from anima identity if available
            try:
                store = _get_store()
                identity = store.get_identity()
                _bridge.set_agent_id(identity.creature_id)
                _bridge.set_session_id(f"anima-{identity.creature_id[:8]}")
            except Exception:
                pass
    return _bridge


async def handle_check_governance(arguments: dict) -> list[TextContent]:
    """
    Check in with UNITARES governance system.
    
    Returns governance decision: PROCEED/PAUSE with proprioceptive margin.
    Includes EISV metrics and current anima state.
    """
    store = _get_store()
    sensors = _get_sensors()
    
    # Read current state
    readings = sensors.read()
    anima = sense_self(readings)
    
    # Get neural/physical weights from arguments or environment
    neural_weight = float(arguments.get("neural_weight", os.environ.get("ANIMA_NEURAL_WEIGHT", "0.3")))
    physical_weight = float(arguments.get("physical_weight", os.environ.get("ANIMA_PHYSICAL_WEIGHT", "0.7")))
    
    # Check in with governance
    bridge = _get_bridge()
    if bridge:
        try:
            decision = await bridge.check_in(anima, readings, neural_weight, physical_weight)
        except Exception as e:
            # Fallback to local governance on error
            from .unitares_bridge import UnitaresBridge
            local_bridge = UnitaresBridge(unitares_url=None)
            decision = await local_bridge.check_in(anima, readings, neural_weight, physical_weight)
            decision["error"] = str(e)
    else:
        # Use local governance
        from .unitares_bridge import UnitaresBridge
        local_bridge = UnitaresBridge(unitares_url=None)
        decision = await local_bridge.check_in(anima, readings, neural_weight, physical_weight)
    
    # Build comprehensive response
    identity = store.get_identity()
    feeling = anima.feeling()
    
    result = {
        "governance": {
            "action": decision["action"],
            "margin": decision["margin"],
            "reason": decision["reason"],
            "source": decision["source"],
            "nearest_edge": decision.get("nearest_edge"),
        },
        "eisv": decision["eisv"],
        "anima": {
            "warmth": anima.warmth,
            "clarity": anima.clarity,
            "stability": anima.stability,
            "presence": anima.presence,
            "mood": feeling.get("mood"),
            "feeling": feeling,
        },
        "identity": {
            "name": identity.name,
            "id": identity.creature_id[:8] + "...",
        },
        "neural": {},
        "timestamp": readings.timestamp.isoformat(),
    }
    
    # Add error if present
    if "error" in decision:
        result["governance"]["error"] = decision["error"]
    
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# Extended tool registry
INTEGRATED_TOOLS = BASE_TOOLS + [
    Tool(
        name="check_governance",
        description="Check in with UNITARES governance system. Returns PROCEED/PAUSE decision with proprioceptive margin, EISV metrics, and current anima state. Optional: neural_weight (0-1, default 0.3) and physical_weight (0-1, default 0.7) to adjust EISV mapping.",
        inputSchema={
            "type": "object",
            "properties": {
                "neural_weight": {
                    "type": "number",
                    "description": "Weight for neural signals in EISV mapping (0-1, default 0.3)",
                    "minimum": 0,
                    "maximum": 1
                },
                "physical_weight": {
                    "type": "number",
                    "description": "Weight for physical signals in EISV mapping (0-1, default 0.7)",
                    "minimum": 0,
                    "maximum": 1
                }
            },
            "required": []
        }
    ),
]

INTEGRATED_HANDLERS = {**BASE_HANDLERS, "check_governance": handle_check_governance}


def create_integrated_server(unitares_url: Optional[str] = None) -> type:
    """
    Create anima server with UNITARES governance integration.
    
    Args:
        unitares_url: Optional URL to UNITARES server (e.g., "http://127.0.0.1:8767/mcp/")
                     If None, will check UNITARES_URL environment variable
                     Falls back to local governance if unavailable
    
    Returns:
        Server instance with integrated tools
    """
    global _bridge
    
    # Initialize bridge if URL provided
    if unitares_url:
        _bridge = UnitaresBridge(unitares_url=unitares_url)
    elif os.environ.get("UNITARES_URL"):
        _bridge = UnitaresBridge(unitares_url=os.environ.get("UNITARES_URL"))
    
    # Create base server
    server = create_base_server()
    
    # Override list_tools to include governance tool
    original_list_tools = server.list_tools
    
    @server.list_tools()
    async def list_tools():
        tools = await original_list_tools()
        # Add governance tool if not already present
        tool_names = {tool.name for tool in tools}
        if "check_governance" not in tool_names:
            tools.append(INTEGRATED_TOOLS[-1])  # Last tool is check_governance
        return tools
    
    # Override call_tool to handle governance
    original_call_tool = server.call_tool
    
    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None):
        if name == "check_governance":
            return await handle_check_governance(arguments or {})
        # Delegate to base server for other tools
        return await original_call_tool(name, arguments)
    
    return server


# Re-export main functions for compatibility
def wake(db_path: str = "anima.db", anima_id: str | None = None):
    """Wake up creature. Re-exported from base server."""
    from .server import wake as base_wake
    base_wake(db_path, anima_id)
    
    # Initialize bridge with agent ID if available
    bridge = _get_bridge()
    if bridge:
        try:
            store = _get_store()
            identity = store.get_identity()
            bridge.set_agent_id(identity.creature_id)
            bridge.set_session_id(f"anima-{identity.creature_id[:8]}")
        except Exception:
            pass


def sleep():
    """Go to sleep. Re-exported from base server."""
    from .server import sleep as base_sleep
    base_sleep()


async def run_stdio_server():
    """Run integrated server over stdio."""
    server = create_integrated_server()
    
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run_sse_server(host: str = "127.0.0.1", port: int = 8765):
    """Run integrated server over SSE (network)."""
    try:
        from starlette.applications import Starlette
        from starlette.routing import Route
        from mcp.server.sse import SseServerTransport
        import uvicorn
    except ImportError:
        print("SSE dependencies not installed. Run: pip install anima-mcp[sse]")
        raise SystemExit(1)

    server = create_integrated_server()
    sse = SseServerTransport("/messages")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0], streams[1], server.create_initialization_options()
            )

    async def handle_messages(request):
        await sse.handle_post_message(request.scope, request.receive, request._send)

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=handle_messages, methods=["POST"]),
        ]
    )

    import signal
    def shutdown_handler(sig, frame):
        print("\nShutting down...")
        sleep()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    print(f"Anima MCP Server (with UNITARES) running at http://{host}:{port}")
    print(f"  Connect with: http://{host}:{port}/sse")
    if _get_bridge():
        print(f"  UNITARES: {_get_bridge()._url}")
    else:
        print(f"  UNITARES: Not configured (using local governance)")
    uvicorn.run(app, host=host, port=port, log_level="warning")


def main():
    """Entry point for integrated server."""
    import argparse
    import asyncio
    
    parser = argparse.ArgumentParser(description="Anima MCP Server with UNITARES Governance")
    parser.add_argument(
        "--unitares",
        type=str,
        default=None,
        help="URL to UNITARES governance server (e.g., http://127.0.0.1:8767/mcp/)"
    )
    parser.add_argument(
        "--db",
        type=str,
        default="anima.db",
        help="Path to SQLite database"
    )
    parser.add_argument(
        "--id",
        type=str,
        default=None,
        help="Creature UUID (auto-generated if not provided)"
    )
    parser.add_argument(
        "--sse",
        action="store_true",
        help="Run SSE server instead of stdio"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for SSE server (default: 8765)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host for SSE server (default: 127.0.0.1)"
    )
    
    args = parser.parse_args()
    
    # Set environment variable if URL provided
    if args.unitares:
        os.environ["UNITARES_URL"] = args.unitares
    
    # Wake up
    wake(args.db, args.id)
    
    try:
        if args.sse:
            # Run SSE server (synchronous)
            run_sse_server(host=args.host, port=args.port)
        else:
            # Run stdio server (async)
            asyncio.run(run_stdio_server())
    finally:
        sleep()


if __name__ == "__main__":
    main()

