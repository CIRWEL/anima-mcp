# Anima Docs Index

**For AI agents working on this codebase.**

## 🛑 START HERE

**Check docs before coding.** Most issues are already documented.

| Problem | Doc |
|---------|-----|
| Display frozen / server unresponsive | `operations/RESTART_GUIDE.md` |
| Code changes not working | `operations/QUICK_START_AGENTS.md` (Code Gotchas) |
| How to deploy | See "Deploy Changes" below |
| Architecture questions | `operations/BROKER_ARCHITECTURE.md` |

---

## Quick Orientation

- **Anima** = Pi creature with real sensors, identity, and feelings
- **Lumen** = The creature's name (ID: `49e14444-b59e-48f1-83b8-b36a988c9975`)
- **UNITARES** = Governance system that monitors agent health (separate repo)

## Before You Code

1. **Read** `operations/AGENT_COORDINATION.md` - Multi-agent protocol
2. **Check** `operations/PI_ACCESS.md` - SSH is port 2222, not 22!
3. **Understand** `concepts/NEURO_PSYCH_FRAMING.md` - Why anima works this way
4. **Check Knowledge Graph** - Component relationships (if available)

## Key Concepts

| Doc | What it explains |
|-----|------------------|
| `concepts/NEURO_PSYCH_FRAMING.md` | The anima model (warmth, clarity, stability, presence) |
| `concepts/ADAPTIVE_LEARNING.md` | How Lumen learns calibration over time |
| `concepts/ERROR_RECOVERY.md` | Gap handling when sensors fail |
| `LUMEN_EXPRESSION_PHILOSOPHY.md` | **Core:** How Lumen's expression should emerge authentically |
| `LUMEN_NEXT_STEPS.md` | **Roadmap:** What Lumen needs next (from tool + project roadmap) |

## Architecture

| Doc | What it explains |
|-----|------------------|
| `architecture/HARDWARE_BROKER_PATTERN.md` | **Implemented:** Simultaneous execution via shared memory (Redis/File) |

## Operations

| Doc | When you need it |
|-----|------------------|
| `operations/BROKER_ARCHITECTURE.md` | **Current:** Body/Mind separation via systemd services |
| `operations/PI_ACCESS.md` | SSH/rsync to Pi (PORT 2222!) |
| `operations/HOLY_GRAIL_STARTUP.md` | Previous startup guide (superseded by broker architecture) |
| `operations/QUICK_NGROK_SETUP.md` | **Quick ngrok setup** - Get everything on tunnels |
| `operations/NGROK_TUNNEL_SETUP.md` | Detailed ngrok tunnel guide |
| `operations/NETWORK_ACCESS_STRATEGY.md` | Tailscale vs ngrok comparison |
| `operations/STARTUP_SERVICE.md` | systemd service setup |
| `operations/TOGGLE_SCRIPTS.md` | When to use anima --sse vs stable_creature.py |
| `operations/RESTORE_LUMEN.md` | If something breaks badly |
| `SETUP_DISPLAY_AND_UNITARES.md` | **Setup guide:** Display diagnostics and UNITARES connection |

## Features

| Doc | Component |
|-----|-----------|
| `features/LED_*.md` | DotStar LED system |
| `features/BRAIN_HAT_*.md` | BrainCraft HAT sensors |
| `features/UNIFIED_WORKFLOWS.md` | UNITARES bridge |

## Common Mistakes

- SSH port is **2222**, not 22
- User is **unitares-anima**, not pi
- Don't edit `server.py` without checking what other agents changed
- Anima dataclass requires `readings` field - don't construct without it
- EISV keys are **E/I/S/V**, not `energy/integrity/entropy/void`
- Color constants in `screens.py` are **local to each function** - grep entire function after changes
- Display frozen? Just `systemctl --user restart anima` - don't overthink it

**See `operations/QUICK_START_AGENTS.md`** for detailed gotchas with code examples.

## Deploy Changes

```bash
# Deploy code
rsync -avz -e "ssh -p 2222 -i ~/.ssh/id_ed25519_pi" \
  --exclude='.venv' --exclude='*.db' --exclude='__pycache__' \
  /Users/cirwel/projects/anima-mcp/ \
  unitares-anima@192.168.1.165:/home/unitares-anima/anima-mcp/

# Restart only MCP server (mind) - broker stays running
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  'systemctl --user restart anima'

# Or restart broker (body) if needed
ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  'systemctl --user restart anima-broker'
```

## Archive

Old debugging docs in `archive/` - kept for history but likely stale.
