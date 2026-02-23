# Anima Docs Index

**For AI agents working on this codebase.**

## 🛑 START HERE

**New to Lumen?** → **[Getting Started Simple](guides/GETTING_STARTED_SIMPLE.md)** ← Start here!

**For developers:**
- **Check docs before coding.** Most issues are already documented.

| Problem | Doc |
|---------|-----|
| Display frozen / server unresponsive | `ssh lumen.local 'sudo systemctl restart anima'` |
| Code changes not working | `operations/QUICK_START_AGENTS.md` (Code Gotchas) |
| How to deploy | See "Deploy Changes" below or `../DEPLOYMENT.md` |
| Architecture questions | `operations/BROKER_ARCHITECTURE.md` |
| Web dashboard / Control Center | `CONTROL_CENTER.md` |

---

## Quick Orientation

- **Anima** = Pi creature with real sensors, identity, and feelings
- **Lumen** = The creature's name (ID: `49e14444-b59e-48f1-83b8-b36a988c9975`)
- **UNITARES** = Governance system that monitors agent health (separate repo)

## Before You Code

1. **Read** `operations/AGENT_COORDINATION.md` - Multi-agent protocol
2. **Check** `operations/PI_ACCESS.md` - SSH access details
3. **Understand** the anima model (warmth, clarity, stability, presence) and computational neural bands
4. **Check Knowledge Graph** - Component relationships (if available)

## Key Concepts

| Doc | What it explains |
|-----|------------------|
| `LUMEN_EXPRESSION_PHILOSOPHY.md` | **Core:** How Lumen's expression should emerge authentically |
| `features/CONFIGURATION_GUIDE.md` | Nervous system calibration and config |

**Key source files for understanding the system:**
| File | What it does |
|------|--------------|
| `src/anima_mcp/server.py` | Main loop, lifecycle, REST API (~3,400 lines) |
| `src/anima_mcp/tool_registry.py` | Tool definitions, HANDLERS dict, FastMCP setup |
| `src/anima_mcp/handlers/` | 6 handler modules (system, state, knowledge, display, comms, workflows) |
| `src/anima_mcp/health.py` | Subsystem health monitoring (9 subsystems, per-subsystem stale thresholds) |
| `src/anima_mcp/anima.py` | Anima calculation (warmth, clarity, stability, presence) |
| `src/anima_mcp/computational_neural.py` | Neural bands from Pi hardware (delta/theta/alpha/beta/gamma) + drawing phase modulation |
| `src/anima_mcp/eisv_mapper.py` | EISV mapping for UNITARES governance |
| `src/anima_mcp/display/screens.py` | Display screens, drawing engine (CanvasState, DrawingEISV, DrawingIntent) |
| `src/anima_mcp/display/art_era.py` | Art era protocol — EraState base class + ArtEra interface |
| `src/anima_mcp/display/eras/` | Pluggable art era modules (gestural, pointillist, field, geometric) |

**Archived concepts** (in `archive/2026-02/`): ADAPTIVE_LEARNING.md, ERROR_RECOVERY.md, GAP_HANDLING.md

## Theory

**Deep theoretical foundations** - for researchers and those extending the architecture.

| Doc | What it explains |
|-----|------------------|
| `theory/README.md` | **Index:** Overview + implementation status |
| `theory/TRAJECTORY_IDENTITY_PAPER.md` | **Core Paper v0.8:** Identity as trajectory signature (publication ready) |
| `theory/lumen_eisv_art_paper.md` | **Outline:** Embodied, self-governed art-producing agents (Lumen + EISV) |
| `theory/CODE_THEORY_MAP.md` | How existing code maps to trajectory framework |
| `theory/IMPLEMENTATION_COMPLETE.md` | Implementation completion notes |

**Key insight:** Identity is not a UUID, it's a dynamical invariant - the pattern that persists across time.

**Lumen's identity status:** Check current awakenings via `get_identity` tool.

## Architecture

| Doc | What it explains |
|-----|------------------|
| `architecture/HARDWARE_BROKER_PATTERN.md` | **Implemented:** Simultaneous execution via shared memory (Redis/File) |

## Operations

| Doc | When you need it |
|-----|------------------|
| `operations/BROKER_ARCHITECTURE.md` | **Current:** Body/Mind separation via systemd services |
| `operations/PI_ACCESS.md` | SSH/rsync to Pi (port 22, user unitares-anima) |
| `operations/PI_DEPLOYMENT.md` | Complete deployment guide |
| `operations/QUICK_START_AGENTS.md` | Code gotchas and agent coordination |
| `operations/QUICK_START_PI.md` | Quick Pi setup reference |
| `operations/REFLASH_RECOVERY.md` | Post-reflash restore (broker+anima, anima.env, DB corruption) |
| `operations/RESILIENCE_ANALYSIS.md` | Gaps, bottlenecks, bugs, resilience opportunities |
| `operations/SECRETS_AND_ENV.md` | API keys & OAuth — GROQ_API_KEY, UNITARES_AUTH, ANIMA_OAUTH_* (never in git) |
| `operations/NGROK_ALTERNATIVES_TAILSCALE.md` | Tailscale when ngrok hits limits |

**Network access:**
- **Tailscale** (recommended): Direct Pi access via 100.79.215.83
- **Local**: lumen.local or 192.168.1.165
- **ngrok** (legacy): See `archive/2026-02/NGROK_*.md`

## Features

| Doc | Component |
|-----|-----------|
| `features/LED_*.md` | DotStar LED system |
| `features/BRAIN_HAT_*.md` | BrainCraft HAT sensors |
| `features/UNIFIED_WORKFLOWS.md` | UNITARES bridge |

## Common Mistakes

- SSH: port **22**, user **unitares-anima**, key `~/.ssh/id_ed25519_pi`
- Handler code lives in `handlers/` — check there before editing `server.py`
- Anima dataclass requires `readings` field - don't construct without it
- Color constants in `screens.py` are **local to each function** - grep entire function after changes
- Display frozen? `ssh lumen.local 'sudo systemctl restart anima'`
- Use `lumen_qa` tool for Q&A (list questions or answer them)

**See `operations/QUICK_START_AGENTS.md`** for detailed gotchas with code examples.

## Deploy Changes

**Preferred method (via git + MCP tool):**
```bash
# From Mac, in anima-mcp project:
git add <files> && git commit -m "message" && git push

# Then deploy to Pi via MCP:
mcp__anima__git_pull(restart=true)
```

**Alternative (direct rsync):**
```bash
rsync -avz -e "ssh -i ~/.ssh/id_ed25519_pi" \
  --exclude='.venv' --exclude='*.db' --exclude='__pycache__' --exclude='.git' \
  /Users/cirwel/projects/anima-mcp/ \
  unitares-anima@lumen.local:/home/unitares-anima/anima-mcp/

ssh lumen.local 'sudo systemctl restart anima.service'
```

## Archive

Old debugging docs in `archive/` - kept for history but likely stale.
