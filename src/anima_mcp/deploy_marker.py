"""Out-of-repo record of the code that is actually running.

Why this exists: on the Pi, deploys can rewrite the checkout in ways that
make ``git log`` lie about the running code. ``deploy.sh`` rsyncs and then
aligns git to the exact deployed SHA (step 1b, PR #217), but the MCP
zip-overlay deploy paths — ``deploy_from_github`` and the gitless bootstrap
branch of ``git_pull`` — copy files over the tree without touching ``.git``
at all. And nothing inside the repo tree can record the truth, because the
deploy flow git-resets/cleans the working tree and has wiped repo-resident
files before.

So the marker lives OUTSIDE the repo tree, in the established persistent
state home (which also holds ``anima.env``, ``anima.db``,
``anima_config.json``; it is ``mkdir -p``'d and chmod-700-enforced by
``deploy.sh`` step 0a and is explicitly excluded from every reset/overlay):

    ~/.anima/deployed_ref.json

Two writers:

- :func:`write_startup_marker` — called from ``server.main()`` right after
  the pidfile write. Records the git ref of the code this process was
  started from. Because it runs at process start it catches EVERY restart
  path: deploy.sh's ``systemctl restart``, the MCP ``_delayed_restart``,
  manual restarts, reboots. It is ground truth and overwrites whatever the
  overlay writer left behind.
- :func:`record_zip_overlay` — called after a gitless zip-overlay deploy.
  Merges the commit SHA GitHub embeds in the codeload archive into the
  marker, so the deployed ref is named even before the restart lands and
  even when ``.git`` is absent entirely.

Readers: ``/health/detailed`` on the Pi, and unitares
``scripts/ops/deploy-status.sh`` over ssh from the operator's Mac.

Every write is atomic (tmp file + ``os.replace``) and wholly best-effort:
startup and deploys must never fail because of marker problems.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

MARKER_NAME = "deployed_ref.json"


def marker_path() -> Path:
    """``~/.anima/deployed_ref.json`` — same home the rest of the app uses."""
    return Path.home() / ".anima" / MARKER_NAME


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _repo_root() -> Path:
    # src/anima_mcp/deploy_marker.py -> anima_mcp -> src -> repo root
    return Path(__file__).resolve().parents[2]


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _git(repo_root: Path, *args: str) -> str | None:
    """Run one git command; None on any failure (no .git, no binary, ...)."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def read_marker(path: Path | None = None) -> dict | None:
    """Best-effort read; None when absent, unreadable, or not a JSON object."""
    target = path or marker_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def write_startup_marker(path: Path | None = None) -> bool:
    """Record the ref this process is running. Never raises.

    Returns True when the marker was written, False on any failure — the
    caller may log the failure but must not treat it as fatal.
    """
    try:
        target = path or marker_path()
        repo_root = _repo_root()
        if (repo_root / ".git").exists():
            head = _git(repo_root, "rev-parse", "HEAD")
            branch = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
            status = _git(
                repo_root, "status", "--porcelain", "--untracked-files=all"
            )
            dirty = bool(status) if status is not None else None
        else:
            head = None
            branch = None
            dirty = None
        payload: dict = {
            "head": head,
            "branch": branch,
            "dirty": dirty,
            "started_at": _utc_now_iso(),
            "pid": os.getpid(),
            "source": "startup",
        }
        if head is None:
            # No .git to name the ref — a prior zip-overlay record is then
            # the only statement of what was deployed, so carry it forward.
            previous = read_marker(target)
            if previous and previous.get("deployed_zip_sha"):
                payload["deployed_zip_sha"] = previous["deployed_zip_sha"]
        _atomic_write_json(target, payload)
        return True
    except Exception:
        return False


def record_zip_overlay(zip_sha: str | None, path: Path | None = None) -> bool:
    """Merge a gitless overlay deploy's SHA into the marker. Never raises.

    The startup marker overwrites this with ground truth at the restart that
    follows a deploy; this record covers the window in between, and the
    no-.git case where git can never name the ref.
    """
    try:
        target = path or marker_path()
        payload = read_marker(target) or {}
        payload["deployed_zip_sha"] = zip_sha
        payload["source"] = "zip-overlay"
        payload["overlaid_at"] = _utc_now_iso()
        _atomic_write_json(target, payload)
        return True
    except Exception:
        return False
