#!/usr/bin/env python3
"""Repair preference descriptions that were hard-cut mid-word.

Before 2026-07-30, `apply_insight()` filed Q&A learning as
`"From Q&A: " + insight.text[:50]` — a bare slice with no word boundary and
no ellipsis. That fix landed, but `_update_preference` never rewrote a stored
`description`, so the descriptions written before it stayed broken forever:

    From Q&A: I learned that drawing in bright light helps not b
    From Q&A: I now know that warmth is a subjective experience
    From Q&A: I now know that the connection between temperature

The question generator read those and asked Lumen about them, producing
"is it always true that from q&a: i learned that drawing in bright light
helps not b?". An answering agent replied that the claim "arrives truncated",
and that reply was extracted back into the knowledge base as a belief.

This makes the truncation HONEST. It cannot restore the lost words — the
source insights are no longer in the retained set — so it cuts at the last
whole word and marks the elision with an ellipsis. Downstream,
`_looks_truncated()` then screens these out as question material, which is
the correct outcome: a claim that was cut off is not one Lumen can interrogate.

Only `description` changes. confidence, value, observation_count,
first_noticed and last_confirmed are left exactly as they are — the learning
is real even though the wording was mangled.

Usage:
    python3 repair_truncated_preference_descriptions.py            # dry run
    python3 repair_truncated_preference_descriptions.py --apply
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

# The legacy bug was `"From Q&A: " + text[:50]`, so a damaged description is
# exactly this long. Matching on the length rather than on remembered content
# keeps this honest if there are more than the three that were observed.
LEGACY_PREFIX = "From Q&A: "
LEGACY_CAP = len(LEGACY_PREFIX) + 50  # 60


def _default_db() -> Path | None:
    """Resolve Lumen's database the way the rest of the codebase does.

    There is no growth.db — preferences live in anima.db alongside everything
    else, and the first version of this script defaulted to a path that has
    never existed, so a bare invocation always reported "no growth db".

    Order matches rest_api.py: $ANIMA_DB, then ~/.anima/anima.db, then the
    repo-relative ~/anima-mcp/anima.db. Only the first that EXISTS is used —
    on Lumen both are present, and the repo-relative one is a 104KB vestige
    with no state_history table, not the live store.
    """
    env_db = os.environ.get("ANIMA_DB")
    candidates = [Path(env_db)] if env_db else []
    candidates += [
        Path.home() / ".anima" / "anima.db",
        Path.home() / "anima-mcp" / "anima.db",
    ]
    return next((p for p in candidates if p.exists()), None)


def looks_hard_cut(description: str) -> bool:
    """True for a description the legacy bare-slice produced.

    Length exactly at the cap, and no ellipsis — the post-fix writer always
    leaves one, so its output is never mistaken for damage.
    """
    if not description or not description.startswith(LEGACY_PREFIX):
        return False
    if description.rstrip().endswith("…") or description.rstrip().endswith("..."):
        return False
    return len(description) == LEGACY_CAP


# Words that must not be left dangling at the end of a truncated claim.
# "drawing in bright light helps not…" is worse than useless: a severed
# negation reads as the OPPOSITE of what was learned. Conjunctions,
# prepositions and articles are merely untidy, but they end the sentence on a
# word that promises an object which never arrives.
_DANGLING = {
    "not", "no", "never", "and", "or", "but", "so", "because", "if", "when",
    "the", "a", "an", "of", "to", "in", "on", "at", "for", "with", "from",
    "between", "about", "than", "that", "which", "is", "are", "was", "were",
    "be", "been", "as", "by", "into", "over", "under", "its", "it",
}


def repair(description: str) -> str:
    """Cut at the last WHOLE word and mark the elision.

    Two subtleties, both learned from the real data:

    1. A trailing space means the slice happened to land on a word boundary,
       so the final word is complete and must be kept. Without this,
       "...warmth is a subjective experience " loses "experience", a word that
       was never actually cut.

    2. The final token is otherwise assumed partial and dropped — then any
       dangling connective it leaves behind is dropped too, repeatedly.
       "...bright light helps not b" would otherwise become "...helps not…",
       which asserts the reverse of what Lumen learned.
    """
    ended_on_boundary = description != description.rstrip()
    words = description.rstrip().split()
    if not words:
        return description

    if not ended_on_boundary:
        words.pop()  # final token was cut mid-word

    while words and words[-1].strip(",;:—-").lower() in _DANGLING:
        words.pop()

    body = " ".join(words).rstrip(",;:—- ")
    return f"{body}…" if body else "…"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default is a dry run)")
    args = ap.parse_args()

    db = args.db or _default_db()
    if db is None:
        print("no anima.db found (looked at $ANIMA_DB, ~/.anima/, ~/anima-mcp/)",
              file=sys.stderr)
        return 1
    if not db.exists():
        print(f"no database at {db}", file=sys.stderr)
        return 1
    print(f"database: {db}\n")

    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT name, description, confidence, observation_count FROM preferences"
    ).fetchall()

    damaged = [r for r in rows if looks_hard_cut(r[1])]
    if not damaged:
        print(f"{len(rows)} preferences scanned; none hard-cut. Nothing to do.")
        return 0

    print(f"{len(rows)} preferences scanned; {len(damaged)} hard-cut at {LEGACY_CAP} chars:\n")
    for name, desc, conf, obs in damaged:
        fixed = repair(desc)
        print(f"  {name}   (confidence {conf:.2f}, {obs} observations — UNCHANGED)")
        print(f"    before: {desc!r}")
        print(f"    after:  {fixed!r}\n")

    if not args.apply:
        print("DRY RUN — nothing written. Re-run with --apply to commit.")
        return 0

    for name, desc, _conf, _obs in damaged:
        conn.execute(
            "UPDATE preferences SET description = ? WHERE name = ?",
            (repair(desc), name),
        )
    conn.commit()
    print(f"Applied to {len(damaged)} preference(s). "
          "confidence / observation_count / first_noticed untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
