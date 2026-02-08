# Anima MCP - Agent Instructions

## Architecture

Two processes run together on the Pi:

```
anima-creature              anima --sse
(hardware broker)           (MCP server)
     |                           |
     | writes to                 | reads from
     +---> shared memory <-------+
           /dev/shm
```

- **`stable_creature.py`** (`src/anima_mcp/`) — systemd service, owns I2C sensors, runs learning systems
- **`server.py`** (`src/anima_mcp/`) — MCP server, serves tools to agents, reads shared memory

Both are proper package modules with relative imports.

### Entry Points (pyproject.toml)

| Command | Module | Role |
|---------|--------|------|
| `anima` | `anima_mcp.server:main` | MCP server |
| `anima-creature` | `anima_mcp.stable_creature:main` | Hardware broker |

A backward-compatible wrapper exists at `stable_creature.py` (project root) for the Pi's
current systemd service. Once the service is updated to use `anima-creature`, the wrapper
can be removed.

### Learning modules

These modules are imported by `stable_creature.py`, not by `server.py`.
They are actively running in the hardware broker loop:

| Module | Purpose |
|--------|---------|
| `adaptive_prediction.py` | Temporal pattern learning |
| `memory_retrieval.py` | Context-aware memory search |
| `agency.py` | TD-learning action selection |
| `preferences.py` | Preference evolution |
| `self_model.py` | Self-knowledge accumulation |

**Do NOT delete these files based on import analysis of server.py alone.**

### server_integrated.py

Alternative entry point that wraps `server.py` with a `check_governance` MCP tool.
Currently orphaned — governance integration went into server.py and stable_creature.py directly.

## Git Commit Conventions

- Do NOT include Co-Authored-By lines in commit messages

## Testing

```bash
python3 -m pytest tests/ -x -q
```

## Deploying to Pi

```bash
git push
# Then from any MCP client:
mcp__anima__git_pull(restart=true)
```
