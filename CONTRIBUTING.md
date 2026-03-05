# Contributing to Anima MCP

## Setup

```bash
git clone https://github.com/CIRWEL/anima-mcp.git
cd anima-mcp

# On Mac (mock sensors):
pip install -e .

# On Raspberry Pi (real sensors):
pip install -e ".[pi]"
```

## Running Tests

```bash
python3 -m pytest tests/ -x -q
```

Tests use mock sensors and run on any platform. No Pi hardware needed.

## Running Locally

```bash
# MCP server (mock sensors on Mac)
anima --http --host 0.0.0.0 --port 8766

# Hardware broker (Pi only, separate terminal)
anima-creature
```

## Code Style

- Python 3.11+, asyncio
- MCP server in `anima_mcp/server.py`, handlers in `anima_mcp/handlers/`
- Tool definitions in `anima_mcp/tool_registry.py`
- Display/drawing code in `anima_mcp/display/`
- Art eras are pluggable modules in `anima_mcp/display/eras/`

## Pull Requests

1. Create a branch from `main`
2. Make your changes
3. Run the test suite — it must pass
4. Open a PR with a clear description of what and why

## Deploying to Pi

After merge:

```bash
git push
# Then via any MCP client:
mcp__anima__git_pull(restart=true)
```
