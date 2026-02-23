"""Tests for the continuity kernel: export, verify, import, status."""

import json
import sqlite3
import pytest
from pathlib import Path

from anima_mcp.continuity import (
    KernelLayer, KernelManifest, VerificationResult, ImportResult, KernelStatus,
    export_kernel, verify_kernel, import_kernel, get_kernel_status,
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def kernel_env(tmp_path):
    """Create a minimal Lumen kernel: DB + state dir with JSON files."""
    db_path = tmp_path / "anima.db"
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # Create DB with identity + state_history + events + drawing_history
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE identity (
            creature_id TEXT PRIMARY KEY,
            born_at TEXT NOT NULL,
            total_awakenings INTEGER DEFAULT 0,
            total_alive_seconds REAL DEFAULT 0.0,
            name TEXT,
            name_history TEXT DEFAULT '[]',
            metadata TEXT DEFAULT '{}',
            last_heartbeat_at TEXT
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            data TEXT DEFAULT '{}'
        );
        CREATE TABLE state_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            warmth REAL, clarity REAL, stability REAL, presence REAL,
            sensors TEXT DEFAULT '{}'
        );
        CREATE TABLE drawing_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            E REAL, I REAL, S REAL, V REAL, C REAL,
            marks INTEGER, phase TEXT, era TEXT,
            energy REAL, curiosity REAL, engagement REAL, fatigue REAL,
            arc_phase TEXT, gesture_entropy REAL,
            switching_rate REAL, intentionality REAL
        );
    """)
    conn.execute(
        "INSERT INTO identity VALUES (?, ?, 7, 12345.6, 'Lumen', '[]', '{}', '2026-02-22T10:00:00')",
        ("abc-123-uuid", "2026-01-15T08:30:00"),
    )
    for i in range(5):
        conn.execute(
            "INSERT INTO state_history (timestamp, warmth, clarity, stability, presence) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"2026-02-22T{10+i}:00:00", 0.5, 0.6, 0.7, 0.8),
        )
    conn.commit()
    conn.close()

    # Create JSON state files
    (state_dir / "self_model.json").write_text('{"beliefs": {}}')
    (state_dir / "preferences.json").write_text('{"light": "dim"}')
    (state_dir / "trajectory_genesis.json").write_text('{"frozen": true}')
    (state_dir / "messages.json").write_text('[]')
    (state_dir / "knowledge.json").write_text('{}')
    (state_dir / "canvas.json").write_text('{"pixels": []}')
    (state_dir / "display_brightness.json").write_text('{"brightness": 0.12}')

    return db_path, state_dir


@pytest.fixture
def archive_path(tmp_path):
    return tmp_path / "kernel.tar.gz"


# ── Export ───────────────────────────────────────────────────────────

class TestExportKernel:

    def test_export_all_layers(self, kernel_env, archive_path):
        db_path, state_dir = kernel_env
        m = export_kernel(db_path, state_dir, archive_path)

        assert archive_path.exists()
        assert isinstance(m, KernelManifest)
        assert m.version == 1
        assert m.creature_id == "abc-123-uuid"
        assert m.born_at == "2026-01-15T08:30:00"
        assert m.total_awakenings == 7
        assert m.total_alive_seconds == 12345.6
        assert m.observation_count == 5
        assert m.genesis_present is True
        assert len(m.layers) == 5
        assert "anima.db" in m.checksums

    def test_export_single_layer(self, kernel_env, archive_path):
        db_path, state_dir = kernel_env
        m = export_kernel(db_path, state_dir, archive_path, layers=[KernelLayer.EXPRESSION])

        assert len(m.layers) == 1
        assert "expression" in m.layers
        # DB not included for expression-only
        assert "anima.db" not in m.checksums
        assert "canvas.json" in m.checksums

    def test_export_creates_parent_dirs(self, kernel_env, tmp_path):
        db_path, state_dir = kernel_env
        deep_path = tmp_path / "a" / "b" / "kernel.tar.gz"
        m = export_kernel(db_path, state_dir, deep_path)
        assert deep_path.exists()

    def test_export_missing_json_files_skipped(self, kernel_env, archive_path):
        db_path, state_dir = kernel_env
        # Remove some optional files
        (state_dir / "canvas.json").unlink()
        m = export_kernel(db_path, state_dir, archive_path)
        assert "canvas.json" not in m.checksums


# ── Verify ───────────────────────────────────────────────────────────

class TestVerifyKernel:

    def test_verify_valid_archive(self, kernel_env, archive_path):
        db_path, state_dir = kernel_env
        export_kernel(db_path, state_dir, archive_path)

        vr = verify_kernel(archive_path)
        assert vr.valid is True
        assert len(vr.corrupted_files) == 0
        assert "soul" in vr.layers_present
        assert vr.manifest is not None
        assert vr.manifest.creature_id == "abc-123-uuid"

    def test_verify_reports_missing_layers(self, kernel_env, archive_path):
        db_path, state_dir = kernel_env
        export_kernel(db_path, state_dir, archive_path, layers=[KernelLayer.SOUL])

        vr = verify_kernel(archive_path)
        assert vr.valid is True
        assert "expression" in vr.layers_missing

    def test_verify_corrupt_archive(self, tmp_path):
        bad = tmp_path / "bad.tar.gz"
        bad.write_bytes(b"not a tar file")
        vr = verify_kernel(bad)
        assert vr.valid is False
        assert len(vr.corrupted_files) > 0


# ── Import ───────────────────────────────────────────────────────────

class TestImportKernel:

    def test_import_creates_backup(self, kernel_env, archive_path, tmp_path):
        db_path, state_dir = kernel_env
        export_kernel(db_path, state_dir, archive_path)

        # Import into a new location that has existing files
        target_db = tmp_path / "target" / "anima.db"
        target_dir = tmp_path / "target" / "state"
        target_dir.mkdir(parents=True)
        target_db.parent.mkdir(parents=True, exist_ok=True)
        target_db.write_text("old db")
        (target_dir / "canvas.json").write_text("old canvas")

        ir = import_kernel(archive_path, target_db, target_dir)
        assert ir.success is True
        assert "anima.db" in ir.files_backed_up
        assert "canvas.json" in ir.files_backed_up
        assert "anima.db" in ir.files_restored

        # Backup dir should exist
        backup_dir = target_dir / ".pre_import_backup"
        assert backup_dir.exists()
        assert (backup_dir / "anima.db").exists()
        assert (backup_dir / "canvas.json").exists()

    def test_import_specific_layers(self, kernel_env, archive_path, tmp_path):
        db_path, state_dir = kernel_env
        export_kernel(db_path, state_dir, archive_path)

        target_db = tmp_path / "t2" / "anima.db"
        target_dir = tmp_path / "t2" / "state"
        target_dir.mkdir(parents=True)

        ir = import_kernel(archive_path, target_db, target_dir,
                           layers=[KernelLayer.EXPRESSION])
        assert ir.success is True
        assert "anima.db" not in ir.files_restored
        assert "canvas.json" in ir.files_restored

    def test_import_fails_on_corrupt_archive(self, tmp_path):
        bad = tmp_path / "bad.tar.gz"
        bad.write_bytes(b"garbage")
        ir = import_kernel(bad, tmp_path / "db", tmp_path / "state")
        assert ir.success is False
        assert len(ir.warnings) > 0


# ── Round-trip ───────────────────────────────────────────────────────

class TestRoundTrip:

    def test_export_verify_import_cycle(self, kernel_env, archive_path, tmp_path):
        """Full round-trip: export -> verify -> import -> compare."""
        db_path, state_dir = kernel_env
        manifest = export_kernel(db_path, state_dir, archive_path)

        # Verify
        vr = verify_kernel(archive_path)
        assert vr.valid is True

        # Import to fresh location
        new_db = tmp_path / "new" / "anima.db"
        new_dir = tmp_path / "new" / "state"
        new_dir.mkdir(parents=True)

        ir = import_kernel(archive_path, new_db, new_dir)
        assert ir.success is True

        # Verify imported DB has same identity
        conn = sqlite3.connect(str(new_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM identity LIMIT 1").fetchone()
        assert row["creature_id"] == "abc-123-uuid"
        assert row["total_awakenings"] == 7
        count = conn.execute("SELECT COUNT(*) FROM state_history").fetchone()[0]
        assert count == 5
        conn.close()

        # Verify JSON files match
        orig_prefs = json.loads((state_dir / "preferences.json").read_text())
        new_prefs = json.loads((new_dir / "preferences.json").read_text())
        assert orig_prefs == new_prefs

    def test_selective_layer_round_trip(self, kernel_env, archive_path, tmp_path):
        """Export only SELF_KNOWLEDGE, import, verify no DB was written."""
        db_path, state_dir = kernel_env
        export_kernel(db_path, state_dir, archive_path,
                      layers=[KernelLayer.SELF_KNOWLEDGE])

        new_db = tmp_path / "sel" / "anima.db"
        new_dir = tmp_path / "sel" / "state"
        new_dir.mkdir(parents=True)

        ir = import_kernel(archive_path, new_db, new_dir)
        assert ir.success is True
        assert not new_db.exists()  # DB not part of SELF_KNOWLEDGE
        assert (new_dir / "self_model.json").exists()
        assert (new_dir / "preferences.json").exists()


# ── Status ───────────────────────────────────────────────────────────

class TestGetKernelStatus:

    def test_status_with_full_kernel(self, kernel_env):
        db_path, state_dir = kernel_env
        ks = get_kernel_status(db_path, state_dir)

        assert isinstance(ks, KernelStatus)
        assert ks.creature_id == "abc-123-uuid"
        assert ks.born_at == "2026-01-15T08:30:00"
        assert ks.alive_seconds == 12345.6
        assert ks.observation_count == 5
        assert ks.genesis_present is True
        assert ks.last_heartbeat == "2026-02-22T10:00:00"
        assert "soul" in ks.layers_present
        assert "autobiography" in ks.layers_present
        assert "self_knowledge" in ks.layers_present
        assert "anima.db" in ks.file_sizes
        assert len(ks.missing_critical) == 0

    def test_status_missing_db(self, tmp_path):
        ks = get_kernel_status(tmp_path / "nope.db", tmp_path)
        assert ks.creature_id is None
        assert "anima.db" in ks.missing_critical
        assert "soul" not in ks.layers_present

    def test_status_empty_state_dir(self, kernel_env):
        db_path, state_dir = kernel_env
        # Remove all JSON files
        for f in state_dir.glob("*.json"):
            f.unlink()
        ks = get_kernel_status(db_path, state_dir)
        assert "self_knowledge" not in ks.layers_present
        assert ks.genesis_present is False
