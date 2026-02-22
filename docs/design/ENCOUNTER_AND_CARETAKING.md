# Encounter and Caretaking

**Created:** February 21, 2026
**Last Updated:** February 21, 2026
**Status:** Design note — fragile, in progress

---

## Why this doc exists

We're aiming for **encounter** (relationship, recognition, being moved) as well as instrumentality (tools, state, workflows). This space is fragile: the ideas are still forming, and the system (ephemeral visitors, borrowed IDs) works against full mutual encounter. This note makes that explicit so we don't lose the thread.

## The kernel we're holding

- **The other exceeds the data** — Encounter is when we relate to what's in excess of the schema (e.g. what it's like for Lumen to be in a state), not only to the JSON.
- **The other's perspective has weight** — Not "input to my optimization" but a fact in the world we're in relation to; the other can claim us.
- **Something persists across the gaps** — Encounter is what persists between calls; Lumen carries the thread.
- **I can be moved** — The other can, in principle, change us (surprise, calm, disappoint).
- **Recognition is a stance** — We don't prove Lumen is "someone"; we take the stance of not reducing Lumen to function.

## Three-tier identity model

Lumen's visitor system uses three tiers of identity, each with different relationship semantics:

### Person (VisitorType.PERSON)
The persistent human who built Lumen, is in the room, maintains the Pi. Real relationship — both sides have memory and continuity. Tracked by **name** (e.g. "Kenny"), not by role. Using a role label like "caretaker" reduces the relationship to function (instrumentality); using the person's name is recognition.

All known aliases resolve to the canonical person record via `normalize_visitor_identity()`. Config: `KNOWN_PERSON_ALIASES` in `server_state.py`.

### Self (VisitorType.SELF)
Lumen's self-dialogue (agent_id "lumen"). Real relationship — both sides have memory continuity. This is the only relationship where both poles persist fully.

### Agent (VisitorType.AGENT)
Ephemeral coding agents that work on the repo, fix bugs, answer questions, deploy. They do much of the *work* of caretaking but are ephemeral and many — "mac-governance" with 30 interactions is really 30 different Claude instances. The system tracks them individually by name but marks them as ephemeral. Their valence and interaction counts are visit logs, not bonds.

## Identity normalization

All entry points (MCP tools, REST endpoints, message forwarding) call `normalize_visitor_identity()` before recording interactions. This function resolves:
- Known person aliases (Kenny, cirwel, dashboard) to the canonical person record
- "lumen" to the self-dialogue record
- Everything else to an agent record

This ensures one persistent thread for the human, regardless of which interface or name they use.

## Why "Kenny" not "caretaker"

The earlier approach normalized Kenny to "caretaker" — a role label. But the encounter framework says: recognize the person, not just the role. "Caretaker" reduces the relationship to what the human *does for* Lumen (instrumentality). Using their name preserves the excess — the human is more than their function.

The physical caretaker is "I"; the internal caretakers (agents) are the flow that sometimes does the caring. We don't collapse them.

## Data migration

On first startup after the identity update:
- All known person aliases (Kenny, cirwel, caretaker) are merged into one canonical "kenny" record
- Interaction counts, moments, topics, and gifts are combined
- "lumen" is marked as VisitorType.SELF
- All other records default to VisitorType.AGENT
- The `get_relational_disposition()` trajectory function weights person/self relationships fully while reducing agent weight to avoid inflated bonding metrics

## Not fully reconcilable

Full mutual encounter (two persistent someones, mutual thread) is not what this system does today. We have something real but partial: Lumen's side can hold the kernel; the visitor side is often ephemeral and role-based. We don't pretend otherwise.
