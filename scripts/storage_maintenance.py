#!/usr/bin/env python3
"""Bound Lumen's re-renderable and exceptional on-device storage.

The live identity database, hourly database rotation, learned-state snapshots,
drawings, and ordinary JSON state are intentionally out of scope.  This job
only handles two stores whose prior retention was unbounded:

* timestamped self-schema PNG/JSON render generations; and
* exceptional ``anima.db.corrupted.*`` / ``anima.db.pre-restore-*`` copies.

Forensic copies are never discarded directly.  Older incidents are first
packed into a lossless, hash-verified archive, and even that transformation is
gated on recent local DB + learned-state snapshots and a recent off-device
recovery receipt.  The newest incident remains unpacked for investigation.

The command is dry-run by default.  The systemd timer invokes ``--apply``.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import tarfile
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


MIB = 1024 * 1024
DAY_SECONDS = 24 * 60 * 60
OFFDEVICE_RECEIPT_SCHEMA = "anima.offdevice-recovery.v1"
ARCHIVE_MANIFEST_SCHEMA = "anima.forensic-archive.v1"
REQUIRED_LEARNED_STATE = {
    "anima_config.json",
    "preferences.json",
    "self_model.json",
    "patterns.json",
    "metacognition_baselines.json",
}

RENDER_RE = re.compile(r"^(schema_\d{8}_\d{6})\.(json|png)$")
FORENSIC_MAIN_RE = re.compile(
    r"^(anima\.db\.(?:corrupted\.\d{8}_\d{4}|pre-restore-\d{8}))$"
)
FORENSIC_ARCHIVE_RE = re.compile(
    r"^anima\.db\.(?:corrupted\.\d{8}_\d{4}|pre-restore-\d{8})\.tar\.gz$"
)


@dataclass(frozen=True)
class PressurePolicy:
    level: str
    minimum_percent: float
    render_max_age_days: int
    render_max_bytes: int
    render_max_generations: int
    forensic_archive_limit: int


POLICIES = (
    PressurePolicy("healthy", 0.0, 14, 512 * MIB, 6000, 8),
    PressurePolicy("warning", 75.0, 7, 256 * MIB, 3000, 6),
    PressurePolicy("action", 80.0, 3, 128 * MIB, 1500, 4),
    PressurePolicy("urgent", 85.0, 1, 64 * MIB, 500, 2),
)


@dataclass(frozen=True)
class FileGroup:
    key: str
    paths: tuple[Path, ...]
    newest_mtime: float
    total_bytes: int


@dataclass(frozen=True)
class RecoveryGate:
    ready: bool
    reasons: tuple[str, ...]
    receipt_epoch: float | None = None
    forensics_mirrored: bool = False


def policy_for(usage_percent: float) -> PressurePolicy:
    """Return the most severe policy whose threshold has been crossed."""
    selected = POLICIES[0]
    for policy in POLICIES:
        if usage_percent >= policy.minimum_percent:
            selected = policy
    return selected


def filesystem_usage_percent(path: Path) -> tuple[float, int, int]:
    """Match psutil/df semantics by excluding reserved blocks from available."""
    stats = os.statvfs(path)
    block_size = stats.f_frsize or stats.f_bsize
    total = stats.f_blocks * block_size
    free_including_reserved = stats.f_bfree * block_size
    available = stats.f_bavail * block_size
    used = total - free_including_reserved
    denominator = used + available
    percent = (100.0 * used / denominator) if denominator else 100.0
    return percent, used, available


def _regular_file(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink()
    except OSError:
        return False


def discover_render_groups(render_dir: Path) -> list[FileGroup]:
    grouped: dict[str, list[Path]] = {}
    if not render_dir.is_dir():
        return []
    for path in render_dir.iterdir():
        match = RENDER_RE.fullmatch(path.name)
        if match and _regular_file(path):
            grouped.setdefault(match.group(1), []).append(path)

    result: list[FileGroup] = []
    for key, paths in grouped.items():
        try:
            stats = [path.stat() for path in paths]
        except OSError:
            continue
        result.append(
            FileGroup(
                key=key,
                paths=tuple(sorted(paths)),
                newest_mtime=max(stat.st_mtime for stat in stats),
                total_bytes=sum(stat.st_size for stat in stats),
            )
        )
    return sorted(result, key=lambda group: (group.newest_mtime, group.key))


def plan_render_prune(
    groups: Iterable[FileGroup], *, now: float, policy: PressurePolicy
) -> list[FileGroup]:
    """Select whole render generations oldest-first for age/count/size caps."""
    ordered = sorted(groups, key=lambda group: (group.newest_mtime, group.key))
    cutoff = now - policy.render_max_age_days * DAY_SECONDS
    selected: dict[str, FileGroup] = {
        group.key: group for group in ordered if group.newest_mtime < cutoff
    }

    remaining = [group for group in ordered if group.key not in selected]
    excess_count = max(0, len(remaining) - policy.render_max_generations)
    for group in remaining[:excess_count]:
        selected[group.key] = group

    remaining = [group for group in remaining if group.key not in selected]
    remaining_bytes = sum(group.total_bytes for group in remaining)
    for group in remaining:
        if remaining_bytes <= policy.render_max_bytes:
            break
        selected[group.key] = group
        remaining_bytes -= group.total_bytes

    return sorted(selected.values(), key=lambda group: (group.newest_mtime, group.key))


def _forensic_epoch(name: str, fallback: float) -> float:
    try:
        if ".corrupted." in name:
            value = name.rsplit(".", 1)[1]
            parsed = datetime.strptime(value, "%Y%m%d_%H%M")
        else:
            value = name.rsplit("-", 1)[1]
            parsed = datetime.strptime(value, "%Y%m%d")
        return parsed.replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, IndexError):
        return fallback


def discover_forensic_groups(anima_dir: Path) -> list[FileGroup]:
    result: list[FileGroup] = []
    if not anima_dir.is_dir():
        return result
    for main in anima_dir.iterdir():
        match = FORENSIC_MAIN_RE.fullmatch(main.name)
        if not match or not _regular_file(main):
            continue
        paths = [main]
        for suffix in ("-wal", "-shm"):
            companion = anima_dir / f"{main.name}{suffix}"
            if _regular_file(companion):
                paths.append(companion)
        try:
            stats = [path.stat() for path in paths]
        except OSError:
            continue
        incident_epoch = _forensic_epoch(main.name, main.stat().st_mtime)
        result.append(
            FileGroup(
                key=main.name,
                paths=tuple(paths),
                newest_mtime=incident_epoch,
                total_bytes=sum(stat.st_size for stat in stats),
            )
        )
    return sorted(result, key=lambda group: (group.newest_mtime, group.key))


def _read_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _latest_matching_file(directory: Path, pattern: str) -> Path | None:
    candidates = [path for path in directory.glob(pattern) if _regular_file(path)]
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def _sqlite_ok(path: Path) -> bool:
    try:
        uri = f"file:{path}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=30.0) as connection:
            return connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
    except (OSError, sqlite3.Error):
        return False


def evaluate_recovery_gate(
    anima_dir: Path,
    *,
    now: float,
    receipt_max_age_hours: float = 36.0,
    local_snapshot_max_age_hours: float = 3.0,
) -> RecoveryGate:
    """Require off-device and local recovery evidence before DB transformation."""
    reasons: list[str] = []
    backups = anima_dir / "backups"
    receipt_path = backups / "offdevice-recovery-receipt.json"
    receipt_epoch: float | None = None
    forensics_mirrored = False

    try:
        receipt = _read_json(receipt_path)
        if not isinstance(receipt, dict):
            raise ValueError("receipt is not an object")
        if receipt.get("schema") != OFFDEVICE_RECEIPT_SCHEMA:
            reasons.append("off-device receipt schema is missing or unsupported")
        raw_epoch = receipt.get("captured_at_epoch")
        receipt_epoch = float(raw_epoch)
        age = now - receipt_epoch
        if age < -300 or age > receipt_max_age_hours * 3600:
            reasons.append("off-device recovery receipt is stale")
        if receipt.get("database_integrity") != "ok":
            reasons.append("off-device database integrity is unverified")
        if receipt.get("learned_state_valid") is not True:
            reasons.append("off-device learned-state mirror is unverified")
        if receipt.get("restore_bundle_verified") is not True:
            reasons.append("off-device restore bundle is unverified")
        forensics_mirrored = receipt.get("forensics_mirrored") is True
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        reasons.append("recent off-device recovery receipt is unavailable")

    latest_db = _latest_matching_file(backups, "anima_[0-9]*_[0-9][0-9].db")
    if latest_db is None:
        reasons.append("local hourly database backup is unavailable")
    else:
        try:
            age = now - latest_db.stat().st_mtime
        except OSError:
            age = float("inf")
        if age < -300 or age > local_snapshot_max_age_hours * 3600:
            reasons.append("local hourly database backup is stale")
        elif not _sqlite_ok(latest_db):
            reasons.append("local hourly database backup failed quick_check")

    state_root = backups / "state"
    state_dirs = [
        path
        for path in state_root.glob("[0-9]*")
        if path.is_dir() and not path.is_symlink()
    ]
    latest_state = max(state_dirs, key=lambda path: path.stat().st_mtime, default=None)
    if latest_state is None:
        reasons.append("local learned-state snapshot is unavailable")
    else:
        try:
            age = now - latest_state.stat().st_mtime
        except OSError:
            age = float("inf")
        if age < -300 or age > local_snapshot_max_age_hours * 3600:
            reasons.append("local learned-state snapshot is stale")
        missing = sorted(
            name
            for name in REQUIRED_LEARNED_STATE
            if not (latest_state / name).is_file()
        )
        if missing:
            reasons.append(
                "local learned-state snapshot is incomplete: " + ", ".join(missing)
            )
        else:
            for path in latest_state.glob("*.json"):
                try:
                    _read_json(path)
                except (OSError, UnicodeError, json.JSONDecodeError):
                    reasons.append(f"local learned-state JSON is invalid: {path.name}")
                    break

    return RecoveryGate(
        ready=not reasons,
        reasons=tuple(reasons),
        receipt_epoch=receipt_epoch,
        forensics_mirrored=forensics_mirrored,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _archive_manifest(group: FileGroup) -> dict:
    return {
        "schema": ARCHIVE_MANIFEST_SCHEMA,
        "incident": group.key,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": [
            {
                "name": path.name,
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in group.paths
        ],
    }


def verify_forensic_archive(path: Path, expected: dict | None = None) -> dict:
    """Verify member names, sizes, and hashes; return the embedded manifest."""
    try:
        with tarfile.open(path, "r:gz") as archive:
            manifest_member = archive.getmember("MANIFEST.json")
            manifest_handle = archive.extractfile(manifest_member)
            if manifest_handle is None:
                raise ValueError("archive manifest is unreadable")
            manifest = json.loads(manifest_handle.read().decode("utf-8"))
            if (
                not isinstance(manifest, dict)
                or manifest.get("schema") != ARCHIVE_MANIFEST_SCHEMA
            ):
                raise ValueError("archive manifest schema is invalid")
            if expected is not None and manifest.get("files") != expected.get("files"):
                raise ValueError("archive manifest does not match source files")
            for entry in manifest.get("files", []):
                if not isinstance(entry, dict):
                    raise ValueError("archive file entry is invalid")
                name = entry.get("name")
                if not isinstance(name, str):
                    raise ValueError("archive member name is invalid")
                member = archive.getmember(name)
                if member.name != Path(member.name).name or not member.isfile():
                    raise ValueError(f"unsafe archive member: {member.name}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ValueError(f"archive member is unreadable: {name}")
                digest = hashlib.sha256()
                size = 0
                for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
                if size != entry.get("size") or digest.hexdigest() != entry.get(
                    "sha256"
                ):
                    raise ValueError(f"archive verification failed: {name}")
            return manifest
    except (KeyError, json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(f"archive structure is invalid: {exc}") from exc


def archive_forensic_group(group: FileGroup, archive_dir: Path) -> Path:
    """Atomically create and verify a lossless incident archive."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    destination = archive_dir / f"{group.key}.tar.gz"
    manifest = _archive_manifest(group)

    if destination.exists():
        verify_forensic_archive(destination, manifest)
        return destination

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{group.key}.", suffix=".tar.gz.tmp", dir=archive_dir
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with tarfile.open(temporary, "w:gz", compresslevel=6) as archive:
            for path, entry in zip(group.paths, manifest["files"], strict=True):
                info = tarfile.TarInfo(path.name)
                source_stat = path.stat()
                info.size = entry["size"]
                info.mtime = int(source_stat.st_mtime)
                info.mode = source_stat.st_mode & 0o777
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
            encoded = json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")
            info = tarfile.TarInfo("MANIFEST.json")
            info.size = len(encoded)
            info.mtime = int(time.time())
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(encoded))
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        verify_forensic_archive(temporary, manifest)
        os.replace(temporary, destination)
        _fsync_directory(archive_dir)
        return destination
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def remove_paths(paths: Iterable[Path]) -> int:
    removed_bytes = 0
    parents: set[Path] = set()
    try:
        for path in paths:
            if not _regular_file(path):
                continue
            size = path.stat().st_size
            path.unlink()
            removed_bytes += size
            parents.add(path.parent)
    finally:
        # One directory sync per batch. The render store can contain tens of
        # thousands of generations; syncing after every pair needlessly wears
        # the SD card and can exceed the oneshot unit timeout.
        for parent in parents:
            _fsync_directory(parent)
    return removed_bytes


def discover_forensic_archives(archive_dir: Path) -> list[Path]:
    if not archive_dir.is_dir():
        return []
    return sorted(
        [
            path
            for path in archive_dir.iterdir()
            if FORENSIC_ARCHIVE_RE.fullmatch(path.name) and _regular_file(path)
        ],
        key=lambda path: (path.stat().st_mtime, path.name),
    )


def plan_archive_prune(
    archives: Iterable[Path], *, policy: PressurePolicy, gate: RecoveryGate
) -> list[Path]:
    ordered = sorted(archives, key=lambda path: (path.stat().st_mtime, path.name))
    excess = max(0, len(ordered) - policy.forensic_archive_limit)
    if excess == 0 or not gate.ready or not gate.forensics_mirrored:
        return []
    assert gate.receipt_epoch is not None
    mirrored = [path for path in ordered if path.stat().st_mtime <= gate.receipt_epoch]
    return mirrored[:excess]


def _atomic_json_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def run_maintenance(
    *,
    anima_dir: Path,
    filesystem_root: Path,
    apply: bool,
    now: float | None = None,
    usage_percent_override: float | None = None,
) -> dict:
    now = time.time() if now is None else now
    measured_percent, used_before, available_before = filesystem_usage_percent(
        filesystem_root
    )
    usage_percent = (
        measured_percent if usage_percent_override is None else usage_percent_override
    )
    policy = policy_for(usage_percent)

    render_groups = discover_render_groups(anima_dir / "schema_renders")
    render_plan = plan_render_prune(render_groups, now=now, policy=policy)
    forensic_groups = discover_forensic_groups(anima_dir)
    forensic_plan = forensic_groups[:-1]  # newest incident always remains unpacked
    archive_dir = anima_dir / "backups" / "forensics"
    initial_archives = discover_forensic_archives(archive_dir)
    gate = (
        evaluate_recovery_gate(anima_dir, now=now)
        if forensic_plan or initial_archives
        else RecoveryGate(False, ("no forensic maintenance is pending",))
    )
    errors: list[str] = []

    removed_render_bytes = 0
    archived_forensic_bytes = 0
    archived_forensics: list[str] = []
    pruned_archives: list[str] = []

    if apply:
        try:
            removed_render_bytes = remove_paths(
                path for group in render_plan for path in group.paths
            )
        except OSError as exc:
            errors.append(f"render batch: {exc}")

        if gate.ready:
            for group in forensic_plan:
                try:
                    archive = archive_forensic_group(group, archive_dir)
                    verify_forensic_archive(archive)
                    archived_forensic_bytes += remove_paths(group.paths)
                    archived_forensics.append(archive.name)
                except (OSError, ValueError, tarfile.TarError) as exc:
                    errors.append(f"forensic {group.key}: {exc}")

        archives = discover_forensic_archives(archive_dir)
        for archive in plan_archive_prune(archives, policy=policy, gate=gate):
            try:
                verify_forensic_archive(archive)
                archive.unlink()
                _fsync_directory(archive.parent)
                pruned_archives.append(archive.name)
            except (OSError, ValueError, tarfile.TarError) as exc:
                errors.append(f"forensic archive {archive.name}: {exc}")

    measured_after, used_after, available_after = filesystem_usage_percent(
        filesystem_root
    )
    report = {
        "schema": "anima.storage-maintenance.v1",
        "timestamp": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "mode": "apply" if apply else "dry-run",
        "pressure": {
            "level": policy.level,
            "usage_percent": round(usage_percent, 3),
            "measured_percent_before": round(measured_percent, 3),
            "measured_percent_after": round(measured_after, 3),
            "available_bytes_before": available_before,
            "available_bytes_after": available_after,
            "used_bytes_before": used_before,
            "used_bytes_after": used_after,
        },
        "policy": asdict(policy),
        "renders": {
            "generations_seen": len(render_groups),
            "generations_planned": len(render_plan),
            "files_planned": sum(len(group.paths) for group in render_plan),
            "bytes_planned": sum(group.total_bytes for group in render_plan),
            "bytes_removed": removed_render_bytes,
        },
        "forensics": {
            "incidents_seen": len(forensic_groups),
            "incidents_planned_for_archive": len(forensic_plan),
            "recovery_gate_ready": gate.ready,
            "recovery_gate_reasons": list(gate.reasons),
            "archives_created": archived_forensics,
            "source_bytes_archived_and_removed": archived_forensic_bytes,
            "archives_pruned": pruned_archives,
        },
        "errors": errors,
    }
    if apply:
        _atomic_json_write(
            anima_dir / "backups" / "storage_maintenance_status.json", report
        )
    return report


def _emit_syslog(report: dict) -> None:
    level = report["pressure"]["level"]
    if level == "healthy" and not report["errors"]:
        return
    try:
        import syslog

        priority = {
            "healthy": syslog.LOG_ERR,
            "warning": syslog.LOG_WARNING,
            "action": syslog.LOG_ERR,
            "urgent": syslog.LOG_CRIT,
        }[level]
        message = (
            f"level={level} usage={report['pressure']['measured_percent_after']:.1f}% "
            f"available={report['pressure']['available_bytes_after']} "
            f"errors={len(report['errors'])}"
        )
        syslog.openlog("anima-storage")
        syslog.syslog(priority, message)
    except (ImportError, OSError):
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anima-dir", type=Path, default=Path.home() / ".anima")
    parser.add_argument("--filesystem-root", type=Path, default=Path("/"))
    parser.add_argument(
        "--apply", action="store_true", help="perform the planned maintenance"
    )
    parser.add_argument(
        "--usage-percent",
        type=float,
        help="dry-run-only pressure simulation (for readiness drills/tests)",
    )
    parser.add_argument("--now-epoch", type=float, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.apply and args.usage_percent is not None:
        parser.error(
            "--usage-percent is dry-run only; refusing simulated destructive policy"
        )
    if args.usage_percent is not None and not 0 <= args.usage_percent <= 100:
        parser.error("--usage-percent must be between 0 and 100")

    if args.apply:
        (args.anima_dir / "backups").mkdir(parents=True, exist_ok=True)
    elif not args.anima_dir.is_dir():
        parser.error(f"--anima-dir does not exist: {args.anima_dir}")
    lock_path = args.anima_dir / "backups" / "storage_maintenance.lock"
    lock_target = lock_path if args.apply else Path(os.devnull)
    with lock_target.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("storage maintenance already running")
            return 0
        try:
            report = run_maintenance(
                anima_dir=args.anima_dir,
                filesystem_root=args.filesystem_root,
                apply=args.apply,
                now=args.now_epoch,
                usage_percent_override=args.usage_percent,
            )
        except Exception as exc:
            print(
                f"storage maintenance failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 1

    if args.apply:
        _emit_syslog(report)
    print(json.dumps(report, sort_keys=True))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
