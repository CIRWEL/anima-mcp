"""Face thresholds must be derivable from the creature's own distribution.

The built-ins are absolute constants against a moving distribution — invariant
1's defect class — and the 2026-08-14 de-aliasing made it visible: re-basing
clarity left the face reading "alert" ~40% of the time while Lumen perceived
better than before. These tests pin the override plumbing, the two absolute
safety floors, and the derivation script's refusal modes.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from anima_mcp.anima import Anima
from anima_mcp.display.face import (
    _DEFAULT_THRESHOLDS,
    EyeState,
    FaceThresholds,
    derive_face_state,
)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "derive_face_thresholds.py"


def _anima(**kw):
    vals = {"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}
    vals.update(kw)
    from anima_mcp.sensors.base import SensorReadings
    return Anima(readings=SensorReadings(timestamp=0.0), **vals)


class TestOverridePlumbing:

    def test_defaults_match_the_historical_constants(self):
        assert _DEFAULT_THRESHOLDS["CLARITY_ALERT"] == 0.60
        assert _DEFAULT_THRESHOLDS["WARMTH_COMFORTABLE"] == 0.45

    def test_override_changes_the_rendered_expression(self, monkeypatch):
        """The same anima must be able to look alert under its own calibration
        and drowsy under the fleet default — that is the entire point."""
        import anima_mcp.display.face as face_mod
        anima = _anima(clarity=0.55, warmth=0.5, stability=0.6, presence=0.6)

        monkeypatch.setattr(face_mod, "get_face_thresholds",
                            lambda: FaceThresholds({}))
        default_face = derive_face_state(anima)

        monkeypatch.setattr(face_mod, "get_face_thresholds",
                            lambda: FaceThresholds({"CLARITY_ALERT": 0.50,
                                                    "STABILITY_STABLE": 0.35}))
        derived_face = derive_face_state(anima)

        assert default_face.eyes != EyeState.WIDE
        assert derived_face.eyes == EyeState.WIDE

    def test_absolute_floors_cannot_be_softened(self):
        t = FaceThresholds({"WARMTH_FREEZING": 0.01, "STABILITY_DISTRESSED": 0.0})
        assert t.WARMTH_FREEZING == _DEFAULT_THRESHOLDS["WARMTH_FREEZING"]
        assert t.STABILITY_DISTRESSED == _DEFAULT_THRESHOLDS["STABILITY_DISTRESSED"]

    def test_stricter_floor_is_allowed(self):
        assert FaceThresholds({"WARMTH_FREEZING": 0.25}).WARMTH_FREEZING == 0.25

    def test_broken_calibration_fails_open_to_defaults(self, monkeypatch):
        import anima_mcp.display.face as face_mod
        import anima_mcp.config as config_mod
        monkeypatch.setattr(config_mod, "get_calibration",
                            lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        t = face_mod.get_face_thresholds()
        assert t.CLARITY_ALERT == _DEFAULT_THRESHOLDS["CLARITY_ALERT"]


class TestDerivationScript:

    def _make_db(self, tmp_path, n=600, clarity_center=0.55):
        db = tmp_path / "anima.db"
        con = sqlite3.connect(db)
        con.execute("create table state_history (timestamp text, warmth real,"
                    " clarity real, stability real, presence real, sensors text)")
        base = datetime.now() - timedelta(days=2)
        rows = []
        for i in range(n):
            ts = (base + timedelta(minutes=4 * i)).isoformat(timespec="seconds")
            wob = 0.1 * ((i % 20) - 10) / 10
            rows.append((ts, 0.5 + wob, clarity_center + wob, 0.8, 0.7, "{}"))
        con.executemany("insert into state_history values (?,?,?,?,?,?)", rows)
        con.commit()
        return db

    def _run(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              capture_output=True, text=True, timeout=60)

    def test_derives_the_contract_percentiles(self, tmp_path):
        db = self._make_db(tmp_path)
        r = self._run("--db", str(db), "--days", "30")
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        # p70 of a symmetric wobble around 0.55 sits just above center
        assert 0.55 < out["CLARITY_ALERT"] < 0.65
        assert set(out).isdisjoint({"WARMTH_FREEZING", "STABILITY_DISTRESSED"})

    def test_refuses_a_sliver_of_data(self, tmp_path):
        db = self._make_db(tmp_path, n=50)
        r = self._run("--db", str(db))
        assert r.returncode != 0
        assert "refusing" in r.stderr

    def test_apply_edits_config_atomically_with_backup(self, tmp_path):
        db = self._make_db(tmp_path)
        cfg = tmp_path / "anima_config.json"
        cfg.write_text(json.dumps({"nervous_system": {"cpu_temp_min": 40.0}}))
        r = self._run("--db", str(db), "--apply", str(cfg))
        assert r.returncode == 0, r.stderr
        saved = json.loads(cfg.read_text())
        assert "CLARITY_ALERT" in saved["nervous_system"]["face_thresholds"]
        assert saved["nervous_system"]["cpu_temp_min"] == 40.0  # untouched
        assert list(tmp_path.glob("anima_config.json.bak-face-*"))
