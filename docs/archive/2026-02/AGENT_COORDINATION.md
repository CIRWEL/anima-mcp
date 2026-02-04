# Agent Coordination Guide

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## Philosophy

**Different models catch different things** - it's a gamble, but valuable.

**Strategy**: **Claude + Cursor (Composer) + Gemini (selective)** for anima-mcp:
- ✅ Multiple perspectives (catch different issues)
- ✅ Selective use of Gemini (reviews, not daily dev)
- ✅ Manual coordination (doing best to orchestrate)

---

## Active Agents

### 1. Claude (via UNITARES/SSE)
- **Focus**: Server-side work, governance integration, MCP connections
- **Access**: Via MCP/SSE connection
- **Strengths**: Deep reasoning, architecture, network debugging

### 2. Cursor/Composer (me)
- **Focus**: Code development, implementation, debugging, deployment
- **Access**: Direct file access, terminal
- **Strengths**: Code navigation, quick fixes, deployment

### 3. Gemini (Selective)
- **Focus**: Code reviews, architecture critiques, edge case analysis
- **Access**: Manual/on-demand
- **Strengths**: Fresh perspective, different reasoning style
- **Usage**: Review-only, not daily development

---

## Coordination Practices

### 1. Check Before Starting

**Before making changes:**
- ✅ Check recent git history / file timestamps
- ✅ Read relevant docs (`docs/` directory)
- ✅ Check knowledge graph if available
- ✅ Review related code for context
- ✅ **Check what's running** - Verify which script (`anima --sse` or `stable_creature.py`) is active
- ✅ **Toggle automatically** - Switch scripts if needed for the task (see `docs/operations/TOGGLE_SCRIPTS.md`)

### 2. Communication

**When working on something:**
- Add TODO comments with agent name: `# TODO(Composer): Fix LED transitions`
- Update docs if changing behavior
- Leave notes in code for next agent

**Example:**
```python
# NOTE(Composer): Fixed ASGI double-response error
# See docs/DIAGNOSIS_REBOOT_LOOP.md for details
async def handle_sse(request):
    # ...
```

### 3. Documentation First

**Agents sometimes skip docs** - enforce checking:

- ✅ Read `docs/` before implementing features
- ✅ Check `README.md` for project overview
- ✅ Review `CODEBASE_REVIEW.md` for architecture
- ✅ Consult `CONFIGURATION_GUIDE.md` for config changes

**Checklist:**
```
[ ] Read relevant docs
[ ] Check existing implementations
[ ] Review related code
[ ] Update docs if changing behavior
```

### 4. Knowledge Graph

**If KG exists:**
- Query before making changes
- Update KG after significant changes
- Use KG to understand relationships

---

## Work Boundaries

### Claude's Domain
- Server architecture
- Governance integration
- Complex refactoring
- Design decisions

### Composer's Domain
- Bug fixes
- Feature implementation
- Code deployment
- Diagnostics/debugging
- Documentation updates
- **Script management** - Automatically toggle between `anima --sse` and `stable_creature.py` based on task

### Gemini's Domain (Selective)
- Code reviews before merging
- Architecture critiques
- Edge case analysis
- Documentation review
- **Not for**: Daily implementation (coordination overhead)

### Shared Domain
- Configuration changes (coordinate)
- API changes (discuss first)
- Database schema (coordinate)

---

## Conflict Prevention

### 1. Sequential Work
- One agent per feature/task
- Complete before switching
- Clear handoff

### 2. Version Control
- Commit frequently
- Clear commit messages
- Review before merging

### 3. Communication
- Comment in code
- Update docs
- Leave notes

---

## Documentation Checklist

**Before implementing:**
- [ ] Read `README.md`
- [ ] Check `docs/CODEBASE_REVIEW.md`
- [ ] Review relevant feature docs
- [ ] Check `docs/CONFIGURATION_GUIDE.md` if config-related

**After implementing:**
- [ ] Update `README.md` if needed
- [ ] Update/create feature docs
- [ ] Add examples if new feature
- [ ] Update `docs/CODEBASE_REVIEW.md` if architecture changed

---

## Examples

### Good Coordination

**Composer:**
```python
# TODO(Composer): Implement LED pulsing
# See docs/LED_DISPLAY.md for requirements
# Claude: Please review after implementation
```

**Claude:**
```python
# Reviewed by Claude - looks good
# Suggestion: Add threshold config (done)
```

### Poor Coordination

**Composer:**
```python
# Changed this
def update_leds():
    # ...
```

**Claude:**
```python
# Also changed this (conflict!)
def update_leds():
    # Different implementation
```

---

## Knowledge Graph Usage

**If KG available:**

1. **Before changes:**
   ```python
   # Query KG for related components
   # Check dependencies
   # Understand relationships
   ```

2. **After changes:**
   ```python
   # Update KG with new relationships
   # Document new patterns
   # Link to docs
   ```

---

## Best Practices

### 1. Documentation First
- Always check docs before coding
- Update docs with code changes
- Keep docs in sync

### 2. Clear Communication
- Use comments for coordination
- Document decisions
- Explain "why" not just "what"

### 3. Incremental Changes
- Small, focused changes
- Test after each change
- Commit frequently

### 4. Respect Existing Patterns
- Follow codebase conventions
- Use existing abstractions
- Don't reinvent wheels

---

## Tools

### For Composer
- Direct file access
- Terminal commands
- Code search/navigation
- Deployment scripts

### For Claude
- MCP tools
- SSE connection
- Code review
- Architecture guidance

---

## Related

- **`CODEBASE_REVIEW.md`** - Architecture overview
- **`README.md`** - Project overview
- **Knowledge Graph** - Component relationships (if available)

---

**Good coordination = multiple perspectives without chaos.**
