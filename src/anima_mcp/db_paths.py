"""Where the store lives.

A bare ``db_path: str = "anima.db"`` default binds persistence to whatever
directory the process happened to start in. That is how the broker's agency
learning ended up in ``~/anima-mcp/anima.db`` — 1.6M TD updates in a file no
backup covered — while ``~/.anima/anima.db`` accumulated a second, separate
copy (#123). Both systemd units already set ``ANIMA_DB`` correctly; the code
simply never read it.

Resolution order is **explicit > $ANIMA_DB > ~/.anima/anima.db**. Explicit
wins because a caller that names a store means it — that is how the broker
pins its own agency store (see ``BROKER_AGENCY_DB``) while every other
subsystem follows the environment. In deployment the two agree, since explicit
paths are derived from the same store the units point at, so the ordering only
matters where a caller diverges on purpose.

The one thing this never returns is a relative path.
"""

import os
from pathlib import Path
from typing import Optional

# The historical bare default. Treated as "the caller said nothing", never as
# a real relative path — resolving it against the cwd is the bug this module
# exists to prevent.
DEFAULT_DB_NAME = "anima.db"


def resolve_db_path(db_path: Optional[str] = None) -> str:
    """Resolve a store path that never binds to the working directory."""
    if db_path and db_path != DEFAULT_DB_NAME:
        return db_path

    env_db = os.environ.get("ANIMA_DB")
    if env_db:
        return env_db

    home_db = Path.home() / ".anima" / DEFAULT_DB_NAME
    try:
        home_db.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Unwritable home: still return the absolute path rather than falling
        # back to the cwd. Let the caller's connect() fail where it can be seen.
        pass
    return str(home_db)


# The Python broker's agency store, pinned deliberately (#123).
#
# The broker and the server each run a full TD loop over their own value table.
# Honouring ANIMA_DB here would merge them onto the store that actually drives
# Lumen — a second writer on the live table, and a discontinuity in learned
# values (ask_question 0.051 -> 0.35). The broker keeps its own file until the
# prior question is settled: with I2C moved to anima-broker-ex and LEDs owned by
# the server, what the broker's agency is still *for* is undecided.
#
# Absolute, so it no longer depends on the service's WorkingDirectory.
BROKER_AGENCY_DB = Path.home() / "anima-mcp" / DEFAULT_DB_NAME
