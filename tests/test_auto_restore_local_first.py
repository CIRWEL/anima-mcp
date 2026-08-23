"""Functional tests for auto_restore.sh's local-first recovery stage.

These EXECUTE the script rather than asserting on its text. The stage they
cover gates Lumen's identity: a wrong branch here either strands her (refuses a
recoverable DB) or silently swaps in the wrong one.
"""

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "auto_restore.sh"

REQUIRED_JSON = (
    "anima_config.json",
    "preferences.json",
    "self_model.json",
    "patterns.json",
    "metacognition_baselines.json",
)


def _good_db(path: Path, marker: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY, tag TEXT)")
        conn.execute("INSERT INTO probe (tag) VALUES (?)", (marker,))
        conn.commit()


def _corrupt_db(path: Path) -> None:
    _good_db(path, "doomed")
    # Overwrite the page header region; SQLite then reports "malformed",
    # which is exactly what the live 2026-08-23 failure produced.
    with path.open("r+b") as handle:
        handle.seek(100)
        handle.write(b"\xff" * 2048)


def _tag_of(path: Path) -> str:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        return conn.execute("SELECT tag FROM probe").fetchone()[0]


@pytest.fixture()
def anima_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".anima"
    (d / "backups").mkdir(parents=True)
    for name in REQUIRED_JSON:
        (d / name).write_text(json.dumps({"ok": True}), encoding="utf-8")
    return d


def _run(anima_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "ANIMA_DIR": str(anima_dir),
            # Points at nothing: if control ever reaches the remote stage the
            # script fails closed, so exit 0 PROVES local recovery handled it.
            "SSH_KEY": str(anima_dir / "definitely-absent-key"),
        },
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_recovers_from_newest_valid_local_snapshot(anima_dir: Path):
    _corrupt_db(anima_dir / "anima.db")
    _good_db(anima_dir / "backups" / "anima_20260823_15.db", "older")
    _good_db(anima_dir / "backups" / "anima_20260823_16.db", "newest")

    result = _run(anima_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "no cross-host access required" in result.stdout
    assert _tag_of(anima_dir / "anima.db") == "newest"


def test_preserves_the_corrupt_database_it_replaced(anima_dir: Path):
    _corrupt_db(anima_dir / "anima.db")
    _good_db(anima_dir / "backups" / "anima_20260823_16.db", "newest")

    assert _run(anima_dir).returncode == 0
    # The bad DB is evidence; losing it forfeits any later salvage.
    assert (anima_dir / ".pre-restore-anima.db").exists()


def test_skips_a_corrupt_snapshot_and_takes_the_next(anima_dir: Path):
    _corrupt_db(anima_dir / "anima.db")
    _good_db(anima_dir / "backups" / "anima_20260823_15.db", "older")
    _corrupt_db(anima_dir / "backups" / "anima_20260823_16.db")

    result = _run(anima_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    # Newest-first must not mean newest-only; a corrupt newest is skipped.
    assert _tag_of(anima_dir / "anima.db") == "older"


def test_drops_stale_wal_and_shm_from_the_replaced_database(anima_dir: Path):
    _corrupt_db(anima_dir / "anima.db")
    (anima_dir / "anima.db-wal").write_bytes(b"stale wal")
    (anima_dir / "anima.db-shm").write_bytes(b"stale shm")
    _good_db(anima_dir / "backups" / "anima_20260823_16.db", "newest")

    assert _run(anima_dir).returncode == 0
    # Replaying the old WAL onto the recovered DB would reapply the damage.
    assert not (anima_dir / "anima.db-wal").exists()
    assert not (anima_dir / "anima.db-shm").exists()


def test_healthy_state_is_left_alone(anima_dir: Path):
    _good_db(anima_dir / "anima.db", "live")
    _good_db(anima_dir / "backups" / "anima_20260823_16.db", "backup")

    result = _run(anima_dir)

    assert result.returncode == 0
    assert "restore not needed" in result.stdout
    # An intact identity must never be replaced by a snapshot of itself.
    assert _tag_of(anima_dir / "anima.db") == "live"
    assert not (anima_dir / ".pre-restore-anima.db").exists()


def test_broken_learned_state_does_not_take_the_local_path(anima_dir: Path):
    _corrupt_db(anima_dir / "anima.db")
    _good_db(anima_dir / "backups" / "anima_20260823_16.db", "newest")
    # Local state generations lack anima_config.json, so a DB-only local fix
    # cannot satisfy the gate; this must fall through to the remote mirror
    # (which fails closed here) rather than declare a false recovery.
    (anima_dir / "self_model.json").unlink()

    result = _run(anima_dir)

    assert result.returncode == 1
    assert "Refusing silent fresh start" in result.stdout


def test_no_snapshots_at_all_still_fails_closed(anima_dir: Path):
    _corrupt_db(anima_dir / "anima.db")

    result = _run(anima_dir)

    assert result.returncode == 1
    assert "Refusing silent fresh start" in result.stdout
