#!/usr/bin/env python3
"""Create or restore a consistent Lumen state snapshot.

The Pi is the source of truth.  ``pull`` mints a WAL-consistent SQLite backup
on the Pi, mirrors the small learned-state files, verifies the database, and
only then publishes an immutable local snapshot directory.  A failed or
partial transfer never replaces ``latest``.

Usage:
    python3 scripts/sync_state.py pull
    python3 scripts/sync_state.py push --snapshot PATH --yes

For a complete reflash restore (including learned JSON and the event inbox),
use ``scripts/restore_lumen.sh``.  ``push`` is the guarded database-only
emergency path.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


DEFAULT_REMOTE_HOST = os.environ.get("PI_HOST", "lumen.local")
DEFAULT_REMOTE_USER = os.environ.get("PI_USER", "unitares-anima")
DEFAULT_REMOTE_PORT = int(os.environ.get("PI_PORT", "22"))
DEFAULT_REMOTE_DB = os.environ.get("ANIMA_REMOTE_DB", "~/.anima/anima.db")
DEFAULT_REMOTE_OAUTH_DB = os.environ.get(
    "ANIMA_REMOTE_OAUTH_DB", "~/.anima/oauth.db"
)
DEFAULT_BACKUP_ROOT = Path(
    os.environ.get(
        "ANIMA_SYNC_BACKUP_DIR",
        str(Path.home() / "backups" / "lumen" / "predeploy"),
    )
).expanduser()
try:
    DEFAULT_SNAPSHOTS_TO_KEEP = int(os.environ.get("ANIMA_SYNC_KEEP", "10"))
except ValueError:
    DEFAULT_SNAPSHOTS_TO_KEEP = 10
LEGACY_LOCAL_DB = Path.home() / ".anima" / "anima.db"


class SyncError(RuntimeError):
    """A snapshot operation failed without publishing partial state."""


def _identity_file(value: str | None) -> Path | None:
    if value:
        return Path(value).expanduser()
    env_value = os.environ.get("SSH_KEY")
    if env_value:
        return Path(env_value).expanduser()
    conventional = Path.home() / ".ssh" / "id_ed25519_pi"
    return conventional if conventional.exists() else None


def _ssh_args(args: argparse.Namespace) -> list[str]:
    command = [
        "ssh",
        "-p",
        str(args.port),
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=4",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    identity = _identity_file(args.identity_file)
    if identity is not None:
        command.extend(["-i", str(identity)])
    return command


def _scp_args(args: argparse.Namespace) -> list[str]:
    command = [
        "scp",
        "-P",
        str(args.port),
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=4",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    identity = _identity_file(args.identity_file)
    if identity is not None:
        command.extend(["-i", str(identity)])
    return command


def _target(args: argparse.Namespace) -> str:
    return f"{args.user}@{args.host}"


def _run(
    command: Sequence[str],
    *,
    timeout: int = 180,
    accepted_codes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SyncError(f"command failed to run: {command[0]}: {exc}") from exc
    if result.returncode not in accepted_codes:
        detail = (result.stderr or result.stdout or "no diagnostic output").strip()
        raise SyncError(f"{command[0]} failed ({result.returncode}): {detail}")
    return result


def _remote(
    args: argparse.Namespace, command: str, *, timeout: int = 180
) -> subprocess.CompletedProcess[str]:
    return _run([*_ssh_args(args), _target(args), command], timeout=timeout)


def _verify_sqlite(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise SyncError(f"database snapshot is missing or empty: {path}")
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as exc:
        raise SyncError(f"database snapshot cannot be opened: {exc}") from exc
    if rows != [("ok",)]:
        raise SyncError(f"database snapshot failed integrity_check: {rows[:3]}")


def _write_manifest(path: Path, data: dict[str, object]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _prune_snapshot_generations(root: Path, keep: int, *, preserve: Path) -> None:
    """Bound pre-deploy storage using only recognized snapshot directories."""
    if keep < 1:
        raise SyncError("--keep must be at least 1")
    snapshots: list[Path] = []
    for path in root.iterdir():
        if path.is_symlink() or not path.is_dir():
            continue
        try:
            datetime.strptime(path.name, "%Y%m%dT%H%M%S.%fZ")
        except ValueError:
            continue
        if (path / "manifest.json").is_file():
            snapshots.append(path)
    # Pin the just-published target even if the device clock moved backward.
    keep_set = {preserve}
    keep_set.update(
        [path for path in sorted(snapshots, reverse=True) if path != preserve][
            : max(0, keep - 1)
        ]
    )
    for expired in snapshots:
        if expired not in keep_set:
            shutil.rmtree(expired)


def _mirror_learned_state(args: argparse.Namespace, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    ssh_transport = shlex.join(_ssh_args(args))
    command = [
        "rsync",
        "-az",
        "--timeout=120",
        "--exclude=backups/",
        "--exclude=schema_renders/",
        "--exclude=models/",
        "--exclude=drawings/",
        "--exclude=*.db*",
        "--exclude=anima.env*",
        "--exclude=*.tmp",
        "--exclude=*.log",
        "-e",
        ssh_transport,
        f"{_target(args)}:~/.anima/",
        f"{destination}/",
    ]
    # Exit 24 is expected when the broker consumes a queued one-file event
    # between rsync's scan and copy. The event has then crossed into its owned
    # snapshot; all other transfer failures remain fatal.
    _run(command, timeout=240, accepted_codes=(0, 24))


def _verify_learned_state(path: Path) -> None:
    required = {
        "anima_config.json",
        "preferences.json",
        "self_model.json",
        "patterns.json",
        "metacognition_baselines.json",
    }
    missing = sorted(name for name in required if not (path / name).is_file())
    if missing:
        raise SyncError(
            "learned-state mirror is incomplete; missing: " + ", ".join(missing)
        )
    for snapshot in path.glob("*.json"):
        try:
            json.loads(snapshot.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SyncError(
                f"learned-state snapshot is invalid: {snapshot.name}: {exc}"
            ) from exc


def sync_pull(args: argparse.Namespace) -> Path:
    """Publish a verified DB + learned-state snapshot and return its path."""
    backup_root = Path(args.backup_dir).expanduser().resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=backup_root))
    latest_tmp: Path | None = None
    remote_tmp = f"/tmp/anima-predeploy-{os.getpid()}-{uuid.uuid4().hex[:10]}.db"
    remote_oauth_tmp = (
        f"/tmp/anima-predeploy-oauth-{os.getpid()}-{uuid.uuid4().hex[:10]}.db"
    )
    snapshot_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    snapshot = backup_root / snapshot_name

    print(f"Capturing Lumen state from {_target(args)}...")
    try:
        backup_code = "\n".join(
            [
                "import os, sqlite3",
                f"main = os.path.expanduser({args.remote_db!r})",
                f"oauth = os.path.expanduser({args.remote_oauth_db!r})",
                "if not os.path.isfile(main):",
                "    raise SystemExit('identity database is missing')",
                "def capture(source, destination):",
                "    with sqlite3.connect(source) as src:",
                "        with sqlite3.connect(destination) as dst:",
                "            src.backup(dst)",
                f"capture(main, {remote_tmp!r})",
                "oauth_present = os.path.isfile(oauth) and os.path.getsize(oauth) > 0",
                "if oauth_present:",
                f"    capture(oauth, {remote_oauth_tmp!r})",
                "print('oauth=1' if oauth_present else 'oauth=0')",
            ]
        )
        backup_result = _remote(args, f"python3 -c {shlex.quote(backup_code)}")
        oauth_present = "oauth=1" in getattr(backup_result, "stdout", "")

        local_db = staging / "anima.db"
        _run(
            [
                *_scp_args(args),
                f"{_target(args)}:{remote_tmp}",
                str(local_db),
            ],
            timeout=240,
        )
        _verify_sqlite(local_db)
        oauth_snapshot: str | None = None
        if oauth_present:
            local_oauth = staging / "oauth.db"
            _run(
                [
                    *_scp_args(args),
                    f"{_target(args)}:{remote_oauth_tmp}",
                    str(local_oauth),
                ],
                timeout=120,
            )
            _verify_sqlite(local_oauth)
            local_oauth.chmod(0o600)
            oauth_snapshot = local_oauth.name
        _mirror_learned_state(args, staging / "anima_data")
        _verify_learned_state(staging / "anima_data")

        _write_manifest(
            staging / "manifest.json",
            {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source": _target(args),
                "database": "anima.db",
                "database_bytes": local_db.stat().st_size,
                "database_integrity": "ok",
                "oauth_database": oauth_snapshot,
                "learned_state": "anima_data",
                "learned_state_complete": True,
            },
        )
        _fsync_directory(staging)
        staging.replace(snapshot)
        _fsync_directory(backup_root)

        latest_tmp = backup_root / f".latest-{uuid.uuid4().hex[:8]}"
        latest_tmp.symlink_to(snapshot.name, target_is_directory=True)
        os.replace(latest_tmp, backup_root / "latest")
        _fsync_directory(backup_root)
        _prune_snapshot_generations(backup_root, args.keep, preserve=snapshot)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if latest_tmp is not None:
            latest_tmp.unlink(missing_ok=True)
        raise
    finally:
        try:
            _remote(
                args,
                f"rm -f {shlex.quote(remote_tmp)} {shlex.quote(remote_oauth_tmp)}",
                timeout=30,
            )
        except SyncError:
            # The remote temp is uniquely named and lives under /tmp; failure to
            # remove it must not erase an otherwise verified local snapshot.
            pass

    size_mb = (snapshot / "anima.db").stat().st_size / 1024 / 1024
    print(f"  Verified DB: {size_mb:.1f} MB")
    print(f"  Snapshot: {snapshot}")
    return snapshot


def _resolve_restore_db(args: argparse.Namespace) -> Path:
    if args.snapshot:
        selected = Path(args.snapshot).expanduser()
    else:
        selected = Path(args.backup_dir).expanduser() / "latest"
        if not selected.exists() and LEGACY_LOCAL_DB.exists():
            selected = LEGACY_LOCAL_DB
    if selected.is_dir():
        selected = selected / "anima.db"
    selected = selected.resolve()
    _verify_sqlite(selected)
    return selected


def sync_push(args: argparse.Namespace) -> None:
    """Guarded database-only emergency restore."""
    local_db = _resolve_restore_db(args)
    size_mb = local_db.stat().st_size / 1024 / 1024
    print(f"WARNING: This will replace Lumen's database on {_target(args)}.")
    print(f"  Verified local DB: {local_db} ({size_mb:.1f} MB)")
    print("  Learned JSON is not restored by this command; use restore_lumen.sh for that.")
    if not args.yes:
        confirm = input("  Continue? (y/N) ")
        if confirm.lower() != "y":
            print("Aborted.")
            return

    remote_tmp = f"/tmp/anima-restore-{os.getpid()}-{uuid.uuid4().hex[:10]}.db"
    try:
        _run(
            [*_scp_args(args), str(local_db), f"{_target(args)}:{remote_tmp}"],
            timeout=240,
        )
        verify_code = (
            "import sqlite3,sys;"
            f"c=sqlite3.connect({remote_tmp!r});"
            "r=c.execute('PRAGMA integrity_check').fetchall();c.close();"
            "sys.exit(0 if r==[('ok',)] else 1)"
        )
        install_code = (
            "import os;"
            f"src={remote_tmp!r};dst=os.path.expanduser({args.remote_db!r});"
            "parent=os.path.dirname(dst);os.makedirs(parent,exist_ok=True);"
            "os.replace(src,dst);"
            "[os.unlink(p) for p in (dst+'-wal',dst+'-shm') if os.path.exists(p)];"
            "fd=os.open(parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0));"
            "os.fsync(fd);os.close(fd)"
        )
        command = (
            "set -eu; "
            f"python3 -c {shlex.quote(verify_code)}; "
            "stopped=0; "
            "cleanup() { if [ \"$stopped\" -eq 1 ]; then "
            "sudo systemctl start anima-broker anima >/dev/null 2>&1 || true; fi; }; "
            "trap cleanup EXIT; "
            "sudo systemctl stop anima anima-broker; "
            "stopped=1; "
            f"python3 -c {shlex.quote(install_code)}; "
            "sudo systemctl start anima-broker; "
            "sudo systemctl start anima; "
            "systemctl is-active --quiet anima-broker; "
            "systemctl is-active --quiet anima; "
            "stopped=0; trap - EXIT"
        )
        _remote(args, command, timeout=180)
    finally:
        try:
            _remote(args, f"rm -f {shlex.quote(remote_tmp)}", timeout=30)
        except SyncError:
            pass
    print(f"  Restored and restarted services from {local_db}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Snapshot or restore Lumen's persistent state"
    )
    parser.add_argument("direction", choices=["pull", "push"])
    parser.add_argument("--host", default=DEFAULT_REMOTE_HOST)
    parser.add_argument("--user", default=DEFAULT_REMOTE_USER)
    parser.add_argument("--port", type=int, default=DEFAULT_REMOTE_PORT)
    parser.add_argument("--identity-file")
    parser.add_argument("--remote-db", default=DEFAULT_REMOTE_DB)
    parser.add_argument("--remote-oauth-db", default=DEFAULT_REMOTE_OAUTH_DB)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_ROOT)
    parser.add_argument(
        "--keep",
        type=int,
        default=DEFAULT_SNAPSHOTS_TO_KEEP,
        help="number of verified pre-deploy snapshots to retain (default: 10)",
    )
    parser.add_argument("--snapshot", type=Path, help="DB file or snapshot directory for push")
    parser.add_argument("--yes", action="store_true", help="skip push confirmation")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.direction == "pull":
            sync_pull(args)
        else:
            sync_push(args)
    except (SyncError, OSError) as exc:
        print(f"State sync failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
