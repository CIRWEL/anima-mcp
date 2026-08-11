"""On-device recovery points before code updates restart Lumen.

Remote ``deploy.sh`` creates an off-device snapshot. MCP/zip updates originate
on the Pi and cannot assume the Mac is reachable, so they use this smaller
local guard before a new process can run migrations or changed persistence
code. SQLite is captured through ``Connection.backup`` and learned JSON/event
state is copied into an immutable generation.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .atomic_write import atomic_json_write
from .db_paths import resolve_db_path


DEFAULT_GENERATIONS = 5
REQUIRED_LEARNED_STATE = {
    "anima_config.json",
    "preferences.json",
    "self_model.json",
    "patterns.json",
    "metacognition_baselines.json",
}


class StateSnapshotError(RuntimeError):
    """The state could not be made recoverable, so restart must not proceed."""


def ensure_persistent_config(*, data_dir: str | Path | None = None) -> Path:
    """Migrate the old checkout-local YAML calibration into backed-up state."""
    state_root = Path(data_dir) if data_dir is not None else Path.home() / ".anima"
    destination = state_root / "anima_config.json"
    if destination.exists():
        try:
            data = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StateSnapshotError(
                f"persistent calibration is invalid: {destination}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise StateSnapshotError("persistent calibration must be a JSON object")
        return destination

    candidates: list[Path] = []
    configured = os.environ.get("ANIMA_CONFIG")
    if configured:
        candidates.append(Path(configured).expanduser())
    repo_root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            Path.home() / "anima-mcp" / "anima_config.yaml",
            Path.cwd() / "anima_config.yaml",
            repo_root / "anima_config.yaml",
            repo_root / "anima_config.yaml.example",
        ]
    )

    data: object = {}
    for source in candidates:
        if not source.is_file() or source.resolve() == destination.resolve():
            continue
        try:
            if source.suffix == ".json":
                data = json.loads(source.read_text(encoding="utf-8"))
            else:
                try:
                    import yaml
                except ImportError as exc:
                    if source.name.endswith(".example"):
                        # An empty mapping is exactly ConfigManager's defaults;
                        # this keeps a truly fresh stdlib-only bootstrap viable.
                        data = {}
                        break
                    raise StateSnapshotError(
                        f"PyYAML is required to migrate {source}"
                    ) from exc
                data = yaml.safe_load(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StateSnapshotError(
                f"could not migrate calibration from {source}: {exc}"
            ) from exc
        except Exception as exc:
            if isinstance(exc, StateSnapshotError):
                raise
            raise StateSnapshotError(
                f"could not migrate calibration from {source}: {exc}"
            ) from exc
        break
    if not isinstance(data, dict):
        raise StateSnapshotError("migrated calibration must be a mapping")
    atomic_json_write(destination, data, indent=2)
    return destination


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _copy_durable(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    with destination.open("rb") as handle:
        os.fsync(handle.fileno())


def _copy_learning_inbox(source: Path, destination: Path) -> None:
    if not source.is_dir():
        return
    for root, _directories, filenames in os.walk(source):
        root_path = Path(root)
        relative = root_path.relative_to(source)
        for filename in filenames:
            event_source = root_path / filename
            event_destination = destination / relative / filename
            try:
                _copy_durable(event_source, event_destination)
            except FileNotFoundError:
                # The broker consumed it after os.walk observed it. Its effect
                # has crossed into the owned learned snapshot, so it is no
                # longer pending recovery state.
                continue


def _sqlite_backup(source: Path, destination: Path, *, label: str) -> None:
    try:
        with sqlite3.connect(str(source)) as source_connection:
            with sqlite3.connect(str(destination)) as destination_connection:
                source_connection.backup(destination_connection)
    except sqlite3.Error as exc:
        raise StateSnapshotError(f"{label} SQLite backup failed: {exc}") from exc
    with sqlite3.connect(f"file:{destination}?mode=ro", uri=True) as check:
        integrity = check.execute("PRAGMA integrity_check").fetchall()
    if integrity != [("ok",)]:
        raise StateSnapshotError(
            f"{label} snapshot integrity_check failed: {integrity[:3]}"
        )


def _recognized_generations(root: Path) -> list[Path]:
    generations: list[Path] = []
    for path in root.iterdir():
        if path.is_symlink() or not path.is_dir():
            continue
        try:
            datetime.strptime(path.name, "%Y%m%dT%H%M%S.%fZ")
        except ValueError:
            continue
        if (path / "manifest.json").is_file():
            generations.append(path)
    return sorted(generations, reverse=True)


def create_local_state_snapshot(
    *,
    db_path: str | Path | None = None,
    data_dir: str | Path | None = None,
    backup_root: str | Path | None = None,
    keep: int = DEFAULT_GENERATIONS,
) -> Path:
    """Create a verified local recovery point and return its directory."""
    if keep < 1:
        raise ValueError("keep must be at least 1")

    state_root = Path(data_dir) if data_dir is not None else Path.home() / ".anima"
    ensure_persistent_config(data_dir=state_root)
    resolved_db = Path(resolve_db_path(str(db_path) if db_path is not None else None))
    if not resolved_db.is_file() or resolved_db.stat().st_size == 0:
        raise StateSnapshotError(f"state database is missing or empty: {resolved_db}")

    root = (
        Path(backup_root)
        if backup_root is not None
        else state_root / "backups" / "predeploy-code"
    )
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=root))
    snapshot = root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")

    try:
        destination_db = staging / "anima.db"
        _sqlite_backup(resolved_db, destination_db, label="identity database")

        oauth_source = state_root / "oauth.db"
        oauth_snapshot: str | None = None
        if oauth_source.is_file() and oauth_source.stat().st_size > 0:
            oauth_destination = staging / "oauth.db"
            _sqlite_backup(oauth_source, oauth_destination, label="OAuth database")
            oauth_destination.chmod(0o600)
            oauth_snapshot = oauth_destination.name

        learned_dir = staging / "anima_data"
        learned_dir.mkdir()
        for source in state_root.glob("*.json"):
            try:
                # Validate whole-file snapshots before blessing the generation.
                json.loads(source.read_text(encoding="utf-8"))
                _copy_durable(source, learned_dir / source.name)
            except FileNotFoundError:
                # Atomic writers can replace a path between glob and open; the
                # next snapshot captures that newer generation.
                continue
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise StateSnapshotError(
                    f"learned snapshot is invalid: {source.name}: {exc}"
                ) from exc
        missing = sorted(
            name for name in REQUIRED_LEARNED_STATE
            if not (learned_dir / name).is_file()
        )
        if missing:
            raise StateSnapshotError(
                "learned snapshot is incomplete; missing: " + ", ".join(missing)
            )
        _copy_learning_inbox(
            state_root / "learning_inbox",
            learned_dir / "learning_inbox",
        )

        atomic_json_write(
            staging / "manifest.json",
            {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "database": str(resolved_db),
                "database_integrity": "ok",
                "oauth_database": oauth_snapshot,
                "learned_json_count": len(list(learned_dir.glob("*.json"))),
                "event_file_count": len(
                    list((learned_dir / "learning_inbox").rglob("*.json"))
                ) if (learned_dir / "learning_inbox").exists() else 0,
            },
            indent=2,
        )
        staging.replace(snapshot)
        _fsync_directory(root)

        keep_set = {snapshot}
        keep_set.update(
            [path for path in _recognized_generations(root) if path != snapshot][
                : max(0, keep - 1)
            ]
        )
        for expired in _recognized_generations(root):
            if expired not in keep_set:
                shutil.rmtree(expired)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return snapshot


__all__ = [
    "StateSnapshotError",
    "create_local_state_snapshot",
    "ensure_persistent_config",
]
