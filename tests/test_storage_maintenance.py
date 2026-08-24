"""Safety and pressure-policy tests for Lumen storage maintenance."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "storage_maintenance.py"


@pytest.fixture(scope="module")
def storage():
    spec = importlib.util.spec_from_file_location("storage_maintenance", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _touch(path: Path, data: bytes, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))


def _render(anima: Path, stamp: str, *, mtime: float, pair: bool = True) -> None:
    root = anima / "schema_renders"
    _touch(root / f"schema_{stamp}.json", b'{"nodes": []}', mtime)
    if pair:
        _touch(root / f"schema_{stamp}.png", b"PNG" * 30, mtime)


def _database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE identity (creature_id TEXT)")
        connection.execute("INSERT INTO identity VALUES ('lumen')")


def _recovery_gate(anima: Path, now: float, *, mirrored: bool = True) -> None:
    backups = anima / "backups"
    db = backups / "anima_20270115_12.db"
    _database(db)
    os.utime(db, (now - 600, now - 600))

    state = backups / "state" / "20270115_123000"
    state.mkdir(parents=True)
    for name in (
        "anima_config.json",
        "preferences.json",
        "self_model.json",
        "patterns.json",
        "metacognition_baselines.json",
    ):
        (state / name).write_text("{}")
    os.utime(state, (now - 300, now - 300))

    receipt = {
        "schema": "anima.offdevice-recovery.v1",
        "captured_at_epoch": now - 120,
        "database_integrity": "ok",
        "learned_state_valid": True,
        "restore_bundle_verified": True,
        "forensics_mirrored": mirrored,
    }
    (backups / "offdevice-recovery-receipt.json").write_text(json.dumps(receipt))


def test_pressure_boundaries_are_explicit(storage):
    assert storage.policy_for(74.999).level == "healthy"
    assert storage.policy_for(75.0).level == "warning"
    assert storage.policy_for(80.0).level == "action"
    assert storage.policy_for(85.0).level == "urgent"
    assert storage.policy_for(85.0).render_max_age_days == 1


def test_dry_run_plans_whole_generations_without_deleting(storage, tmp_path):
    now = 1_800_000_000.0
    anima = tmp_path / ".anima"
    _render(anima, "20270101_000000", mtime=now - 15 * 86400)
    _render(anima, "20270115_120000", mtime=now - 60)
    unknown = anima / "schema_renders" / "README.keep"
    unknown.write_text("operator note")

    report = storage.run_maintenance(
        anima_dir=anima,
        filesystem_root=tmp_path,
        apply=False,
        now=now,
        usage_percent_override=66.0,
    )

    assert report["renders"]["generations_planned"] == 1
    assert report["renders"]["files_planned"] == 2
    assert (anima / "schema_renders" / "schema_20270101_000000.json").exists()
    assert unknown.exists()
    assert not (anima / "backups" / "storage_maintenance_status.json").exists()


def test_apply_prunes_only_recognized_old_render_pairs(storage, tmp_path):
    now = 1_800_000_000.0
    anima = tmp_path / ".anima"
    _render(anima, "20270101_000000", mtime=now - 15 * 86400)
    _render(anima, "20270115_120000", mtime=now - 60, pair=False)
    unknown = anima / "schema_renders" / "schema_manual.png"
    unknown.write_bytes(b"keep")

    report = storage.run_maintenance(
        anima_dir=anima,
        filesystem_root=tmp_path,
        apply=True,
        now=now,
        usage_percent_override=66.0,
    )

    assert report["renders"]["bytes_removed"] > 0
    assert not (anima / "schema_renders" / "schema_20270101_000000.json").exists()
    assert not (anima / "schema_renders" / "schema_20270101_000000.png").exists()
    assert (anima / "schema_renders" / "schema_20270115_120000.json").exists()
    assert unknown.exists()


def test_forensics_are_untouched_without_recovery_evidence(storage, tmp_path):
    now = 1_800_000_000.0
    anima = tmp_path / ".anima"
    anima.mkdir()
    old = anima / "anima.db.corrupted.20260704_0000"
    newest = anima / "anima.db.corrupted.20270115_1200"
    old.write_bytes(b"old evidence")
    newest.write_bytes(b"new evidence")

    report = storage.run_maintenance(
        anima_dir=anima,
        filesystem_root=tmp_path,
        apply=True,
        now=now,
        usage_percent_override=86.0,
    )

    assert report["forensics"]["recovery_gate_ready"] is False
    assert old.exists() and newest.exists()
    assert not list((anima / "backups" / "forensics").glob("*.tar.gz"))


def test_older_forensics_are_losslessly_archived_after_gate(storage, tmp_path):
    now = 1_800_000_000.0
    anima = tmp_path / ".anima"
    anima.mkdir()
    _recovery_gate(anima, now)
    sources = {
        "anima.db.corrupted.20260704_0000": b"old-corrupt" * 1000,
        "anima.db.pre-restore-20260723": b"old-restore" * 1000,
        "anima.db.corrupted.20270115_1200": b"newest" * 1000,
    }
    for name, data in sources.items():
        (anima / name).write_bytes(data)
    (anima / "anima.db.corrupted.20260704_0000-wal").write_bytes(b"wal")

    report = storage.run_maintenance(
        anima_dir=anima,
        filesystem_root=tmp_path,
        apply=True,
        now=now,
        usage_percent_override=66.0,
    )

    assert report["forensics"]["recovery_gate_ready"] is True
    assert len(report["forensics"]["archives_created"]) == 2
    assert not (anima / "anima.db.corrupted.20260704_0000").exists()
    assert not (anima / "anima.db.corrupted.20260704_0000-wal").exists()
    assert not (anima / "anima.db.pre-restore-20260723").exists()
    assert (anima / "anima.db.corrupted.20270115_1200").read_bytes() == sources[
        "anima.db.corrupted.20270115_1200"
    ]
    for archive in (anima / "backups" / "forensics").glob("*.tar.gz"):
        manifest = storage.verify_forensic_archive(archive)
        assert manifest["schema"] == "anima.forensic-archive.v1"


def test_apply_rejects_simulated_pressure(storage, tmp_path):
    anima = tmp_path / ".anima"
    anima.mkdir()
    with pytest.raises(SystemExit):
        storage.main(
            [
                "--anima-dir",
                str(anima),
                "--filesystem-root",
                str(tmp_path),
                "--apply",
                "--usage-percent",
                "86",
            ]
        )
