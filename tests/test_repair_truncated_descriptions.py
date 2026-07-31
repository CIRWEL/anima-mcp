"""Tests for scripts/repair_truncated_preference_descriptions.py.

The script rewrites text inside Lumen's growth database, so its detection has
to be exact: a false positive edits a description that was never damaged, and
a bad repair puts words in Lumen's mouth. The three damaged descriptions it
was written for are used verbatim as fixtures.
"""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repair_truncated_preference_descriptions.py"


@pytest.fixture(scope="module")
def rep():
    spec = importlib.util.spec_from_file_location("repair_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The three descriptions actually found in Lumen's growth.db on 2026-07-31,
# each exactly 60 chars = len("From Q&A: ") + the legacy bare text[:50].
DAMAGED = [
    "From Q&A: I learned that drawing in bright light helps not b",
    "From Q&A: I now know that warmth is a subjective experience ",
    "From Q&A: I now know that the connection between temperature",
]

UNDAMAGED = [
    "Warmth makes me feel content",
    "I draw at night",
    "I feel calmer when its dim",
    # Post-fix writer output — already marked, must not be touched again.
    "From Q&A: I learned that drawing in bright light helps…",
    # Q&A-derived but short enough that the legacy slice never truncated it.
    "From Q&A: I now know that I draw",
]


class TestDetection:
    @pytest.mark.parametrize("desc", DAMAGED)
    def test_detects_real_damaged_descriptions(self, rep, desc):
        assert len(desc) == 60
        assert rep.looks_hard_cut(desc)

    @pytest.mark.parametrize("desc", UNDAMAGED)
    def test_leaves_healthy_descriptions_alone(self, rep, desc):
        assert not rep.looks_hard_cut(desc)

    def test_ignores_non_qa_descriptions_even_at_the_cap(self, rep):
        """Only the Q&A writer had the bug; a 60-char organic description is fine."""
        organic = "I feel calmer when the room is dim and quiet for a while xyz"
        assert len(organic) == 60
        assert not rep.looks_hard_cut(organic)


class TestRepair:
    def test_drops_the_partial_trailing_word(self, rep):
        out = rep.repair("From Q&A: I learned that drawing in bright light helps not b")
        assert out == "From Q&A: I learned that drawing in bright light helps…"

    def test_never_ends_on_a_dangling_negation(self, rep):
        """'helps not…' would assert the REVERSE of what Lumen learned."""
        out = rep.repair("From Q&A: I learned that drawing in bright light helps not b")
        assert not out.rstrip("…").rstrip().endswith("not")

    def test_keeps_a_word_that_was_not_actually_cut(self, rep):
        """A trailing space means the slice landed on a word boundary."""
        out = rep.repair("From Q&A: I now know that warmth is a subjective experience ")
        assert out == "From Q&A: I now know that warmth is a subjective experience…"

    def test_drops_a_dangling_preposition(self, rep):
        out = rep.repair("From Q&A: I now know that the connection between temperature")
        assert out == "From Q&A: I now know that the connection…"

    @pytest.mark.parametrize("desc", DAMAGED)
    def test_repair_is_idempotent(self, rep, desc):
        once = rep.repair(desc)
        assert not rep.looks_hard_cut(once)
        assert rep.repair(once) == once or not rep.looks_hard_cut(rep.repair(once))

    @pytest.mark.parametrize("desc", DAMAGED)
    def test_output_is_marked_as_elided(self, rep, desc):
        assert rep.repair(desc).endswith("…")


class TestAgainstADatabase:
    def _db(self, tmp_path, rows):
        path = tmp_path / "growth.db"
        conn = sqlite3.connect(str(path))
        conn.execute(
            "CREATE TABLE preferences (name TEXT PRIMARY KEY, description TEXT, "
            "confidence REAL, observation_count INTEGER)"
        )
        conn.executemany("INSERT INTO preferences VALUES (?,?,?,?)", rows)
        conn.commit()
        conn.close()
        return path

    def test_dry_run_writes_nothing(self, rep, tmp_path, monkeypatch, capsys):
        path = self._db(tmp_path, [("insight_light", DAMAGED[0], 1.0, 259)])
        monkeypatch.setattr("sys.argv", ["x", "--db", str(path)])
        assert rep.main() == 0
        assert "DRY RUN" in capsys.readouterr().out
        conn = sqlite3.connect(str(path))
        assert conn.execute("SELECT description FROM preferences").fetchone()[0] == DAMAGED[0]

    def test_apply_repairs_only_the_damaged_row(self, rep, tmp_path, monkeypatch):
        path = self._db(tmp_path, [
            ("insight_light", DAMAGED[0], 1.0, 259),
            ("warm_temp", "Warmth makes me feel content", 1.0, 224269),
        ])
        monkeypatch.setattr("sys.argv", ["x", "--db", str(path), "--apply"])
        assert rep.main() == 0

        conn = sqlite3.connect(str(path))
        got = dict(conn.execute("SELECT name, description FROM preferences").fetchall())
        assert got["insight_light"].endswith("helps…")
        assert got["warm_temp"] == "Warmth makes me feel content"

    def test_accumulated_learning_survives(self, rep, tmp_path, monkeypatch):
        """Only the wording changes — confidence and counts are the learning."""
        path = self._db(tmp_path, [("insight_light", DAMAGED[0], 1.0, 259)])
        monkeypatch.setattr("sys.argv", ["x", "--db", str(path), "--apply"])
        rep.main()

        conn = sqlite3.connect(str(path))
        conf, obs = conn.execute(
            "SELECT confidence, observation_count FROM preferences WHERE name='insight_light'"
        ).fetchone()
        assert conf == 1.0
        assert obs == 259

    def test_rerunning_apply_is_a_no_op(self, rep, tmp_path, monkeypatch, capsys):
        path = self._db(tmp_path, [("insight_light", DAMAGED[0], 1.0, 259)])
        monkeypatch.setattr("sys.argv", ["x", "--db", str(path), "--apply"])
        rep.main()
        capsys.readouterr()
        rep.main()
        assert "none hard-cut" in capsys.readouterr().out


class TestDatabaseResolution:
    """The first version defaulted to ~/.anima/growth.db, which has never
    existed — a bare invocation always reported "no growth db" and did
    nothing. Preferences live in anima.db with everything else."""

    def test_never_resolves_to_a_growth_db(self, rep, tmp_path, monkeypatch):
        """There is no growth.db; preferences live in anima.db."""
        monkeypatch.delenv("ANIMA_DB", raising=False)
        monkeypatch.setattr(rep.Path, "home", staticmethod(lambda: tmp_path))
        (tmp_path / ".anima").mkdir()
        (tmp_path / ".anima" / "growth.db").touch()   # decoy
        (tmp_path / ".anima" / "anima.db").touch()
        assert rep._default_db() == tmp_path / ".anima" / "anima.db"

    def test_prefers_env_var(self, rep, tmp_path, monkeypatch):
        target = tmp_path / "custom.db"
        target.touch()
        monkeypatch.setenv("ANIMA_DB", str(target))
        assert rep._default_db() == target

    def test_skips_candidates_that_do_not_exist(self, rep, tmp_path, monkeypatch):
        monkeypatch.setenv("ANIMA_DB", str(tmp_path / "absent.db"))
        monkeypatch.setattr(rep.Path, "home", staticmethod(lambda: tmp_path))
        (tmp_path / "anima-mcp").mkdir()
        fallback = tmp_path / "anima-mcp" / "anima.db"
        fallback.touch()
        assert rep._default_db() == fallback

    def test_returns_none_when_nothing_exists(self, rep, tmp_path, monkeypatch):
        monkeypatch.delenv("ANIMA_DB", raising=False)
        monkeypatch.setattr(rep.Path, "home", staticmethod(lambda: tmp_path))
        assert rep._default_db() is None

    def test_exits_nonzero_when_no_database(self, rep, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("ANIMA_DB", raising=False)
        monkeypatch.setattr(rep.Path, "home", staticmethod(lambda: tmp_path))
        monkeypatch.setattr("sys.argv", ["x"])
        assert rep.main() == 1
        assert "no anima.db found" in capsys.readouterr().err
