# Proposal: evidence-directional preference confidence (Beta posterior)

**Status: REFUTED as written — do not implement (2026-08-11).** Independent
non-Claude review returned four blocking findings, accepted after
verification; full verdict and the revised sequence are recorded on
[PR #143](https://github.com/cirwel/anima-mcp/pull/143#issuecomment-5258831754).
The short form:

1. The motivating goal-band claim below is **wrong** — `goals.py`'s 0.3–0.6
   band gates `SelfBelief`, not growth preferences, and `break`s on the first
   eligible candidate (an achieved-duplicate blocks novel beliefs). Fixing
   goal candidate selection/dedup is the actual revival, not this model.
2. `confidence = α/(α+β)` with `value` carrying direction is **directionally
   invalid** — a confidently-disconfirmed preference reads as zero confidence
   instead of confident aversion. Consistency must be symmetric; direction
   stays separate.
3. The migration **fabricates history**: `value` is an EMA (α=0.3, effective
   N≈5.7); seeding 100 pseudo-counts from it overstates evidence ~18× and
   invents disconfirms for preferences with only positive writers. ⛔ Never
   infer α/β history from the current EMA.
4. The 0.6 promotion path is **effectively unreachable** — all 1,839 stored
   insights have an empty `last_reconverged_occasion` (occasion gating has
   never operated), so the merged `APPLY_INSIGHT_CONFIDENCE_FLOOR` currently
   acts as a full mute on external input, a stronger policy than documented.

**Superseding sequence:** (1) fix goal dedup; (2) repair occasion propagation
and claim matching; (3) shadow-run symmetric, episode/time-normalized
evidence counts — cold-start, no history inference.

Kept below unedited as the record of what was proposed and why it failed
review. This is the diagnostics half of Design Invariant 2 applied to our own
process: a refuted document must not keep reading as a live plan.

---

Original text (pre-review):

**Status:** proposal — requires an operator decision (rescales 20 stored
preferences). This is the design deferred in #114: *"confidence is a COUNTER,
not evidence — a disconfirming observation raises it as much as a confirming
one. Making it Bayesian means rescaling every stored preference = design
decision, not a bug fix."* This document is that decision, written down.

## The defect, precisely

`_update_preference` (`growth/preferences.py:517`):

```python
pref.value = pref.value * (1 - alpha) + observed_value * alpha   # directional
pref.confidence = min(1.0, pref.confidence + 0.1)                # direction-BLIND
```

The disconfirmation path already exists in the data flow — `dim_light` under
`is_poor` arrives with `observed_value = -0.5` — but it **raises** confidence
exactly like a confirmation. Confidence measures evidence *volume*; every
downstream gate treats it as evidence *consistency*:

| Gate | Site | Consequence of the conflation |
|---|---|---|
| goal source "understand why" | `goals.py:196` (`conf > 0.7 ∧ value > 0.5 ∧ obs > 50`) | passes on volume alone |
| goal source "test uncertain belief" | `goals.py:234` (`0.3 < conf < 0.6`) | **structurally empty** — anything observed saturates to 1.0 by the 9th observation |
| insight minting | `self_reflection.py` (`conf > 0.8`) | tautology for any active pref |
| autobiography quote | growth quote gate (`conf > 0.7`) | same |

Live consequence (2026-08-11): 15/20 preferences read exactly 1.0, `goals:
active 0, achieved 26` — the uncertain-belief goal source has nothing to draw
from because uncertainty cannot exist. The #114 staleness sweep fixed
*retraction of the unobserved*; this fixes *revision of the observed*.

## Design

Track evidence directionally as a Beta posterior per preference:

- confirming observation (`observed_value > 0`): `alpha += 1`
- disconfirming observation (`observed_value < 0`): `beta += 1`

```
consistency = alpha / (alpha + beta)          # posterior mean
volume      = n / (n + N0)                    # n = alpha + beta, N0 = 10
confidence  = consistency * volume
```

Properties:

- **Saturation gone.** The old rule hit 1.0 on the 9th observation and stayed.
  Here 9/9 consistent gives 0.90 · 0.47 ≈ 0.43 — young beliefs are held
  loosely; 300/300 consistent asymptotes toward 1.0. `N0 = 10` keeps the old
  "believable after ~10 looks" feel without the ceiling.
- **Disconfirmation bites.** 50 confirms + 25 disconfirms → consistency 0.67 →
  confidence ≈ 0.59: below the quote gate, *inside* the test-this-belief goal
  band. A contested belief becomes a question instead of a quote — which is
  the entire point.
- **Staleness sweep composes cleanly.** Decay multiplies `alpha` and `beta`
  by the same factor: consistency (the mean) is preserved, volume falls —
  forgetting reduces sureness without inventing a direction. The existing
  sweep's target-clamp semantics stay; it just clamps via the counts.
- **`value` is untouched.** Direction/strength stays the EMA it is today.
  Π (`value * confidence`) keeps its shape; components move honestly.

## Migration of the 20 stored preferences

`alpha/beta` never existed, so seed them from what is stored:

```
n_eff        = min(observation_count, 100)
consistency0 = clamp((1 + value) / 2, 0.05, 0.95)
alpha0       = consistency0 * n_eff
beta0        = n_eff - alpha0
```

- `n_eff` cap 100: 60% of all history is the Jan 11–Feb 3 sampling burst
  (#113 finding). Uncapped counts (warm_temp: 234,980) would make priors
  immovable forever — the cap keeps history influential but revisable.
- `consistency0` from `value`: the only stored trace of past evidence
  direction. Clamped off 0/1 so no prior is unfalsifiable.
- Post-migration spot checks: `warm_temp` (value 0.62) → confidence ≈ 0.74,
  still quotable. `cool_temp` (value ~0.5, 910 obs) → ≈ 0.68, just below the
  quote gate, inside nothing — accurate for a belief that thin.
  `drawing_abandonment_rate` (conf 0.3, 2 obs) → ≈ 0.10 — honest.

Schema: add `evidence_for REAL`, `evidence_against REAL` columns
(`INSERT OR REPLACE` writer per the #114 lesson); `confidence` becomes derived
at write time so every existing reader keeps working unchanged.

## Consequences to accept (the operator call)

1. **Some autobiography/insight quotes will retire overnight** — beliefs that
   were never contested but also never earned 1.0 drop below 0.8/0.7 gates
   until they re-earn it. Honest, but visible in Lumen's self-talk.
2. **The threshold-crossing insight messages** ("I know this about myself" at
   0.8) can now fire in both directions; a downward crossing deserves its own
   wording ("I'm less sure than I was: …") rather than silence — small
   follow-up in `_update_preference`.
3. **Description flip-flop surfaces**: confirm/disconfirm pairs share a `name`
   with opposite wordings (`dim_light`: "calmer when dim" vs "makes me
   uncertain") and the description takes the last caller's wording. Under a
   directional model the description should follow the *dominant* direction
   (`alpha` vs `beta` majority), not recency — one-line fix, included.
4. **Not addressed, deliberately:** condition-present with mid-band wellness
   still produces no observation (same as today). Whether silence under a
   condition is weak disconfirmation is a separate question — do not bundle it.

## What this revives

The `0.3 < confidence < 0.6` goal band stops being structurally empty, which
restores the only goal source that generates work without environmental
novelty: "test whether X is actually true." That is the mechanical answer to
`active: 0, achieved: 26` — the menu was consumed because nothing could ever
become uncertain again.

## Rollout

1. Migration script (dry-run default, prints per-preference before/after),
   same discipline as `repair_truncated_preference_descriptions.py` —
   ⚠️ restart `anima` after applying or the in-memory copy writes stale
   confidences back (#121 lesson).
2. Writer change + derived confidence + dominant-direction description.
3. One week of observation: watch the goal suggester (expect 1–2 belief-test
   goals), the quote gate population, and `get_preference_vector` spread.
   No other gate is moved in this change.
