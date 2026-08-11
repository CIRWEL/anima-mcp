"""Executable contracts for the pre-deploy snapshot transaction."""

import argparse
import importlib.util
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "anima_sync_state_under_test", ROOT / "scripts" / "sync_state.py"
)
assert SPEC and SPEC.loader
sync_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_state)


def _valid_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE continuity (id INTEGER PRIMARY KEY)")


def _args(backup_dir: Path) -> argparse.Namespace:
    return argparse.Namespace(
        host="lumen.test",
        user="anima",
        port=22,
        identity_file=None,
        remote_db="~/.anima/anima.db",
        remote_oauth_db="~/.anima/oauth.db",
        backup_dir=backup_dir,
        snapshot=None,
        yes=False,
        keep=2,
    )


def test_verify_sqlite_rejects_non_database(tmp_path):
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_text("not sqlite")

    with pytest.raises(sync_state.SyncError):
        sync_state._verify_sqlite(corrupt)


def test_verify_learned_state_requires_all_authoritative_files(tmp_path):
    (tmp_path / "preferences.json").write_text("{}")

    with pytest.raises(sync_state.SyncError, match="learned-state mirror is incomplete"):
        sync_state._verify_learned_state(tmp_path)


def test_verify_learned_state_rejects_malformed_json(tmp_path):
    for name in (
        "anima_config.json",
        "preferences.json",
        "self_model.json",
        "patterns.json",
        "metacognition_baselines.json",
    ):
        (tmp_path / name).write_text("{}")
    (tmp_path / "patterns.json").write_text("{")

    with pytest.raises(sync_state.SyncError, match="patterns.json"):
        sync_state._verify_learned_state(tmp_path)


def test_pull_publishes_only_after_db_and_learned_state_verify(tmp_path, monkeypatch):
    backup_root = tmp_path / "predeploy"
    args = _args(backup_root)
    remote_commands: list[str] = []

    def fake_remote(_args, command, **_kwargs):
        remote_commands.append(command)
        return SimpleNamespace(
            stdout="oauth=1" if command.startswith("python3 -c ") else ""
        )

    def fake_run(command, **_kwargs):
        assert command[0] == "scp"
        _valid_db(Path(command[-1]))

    def fake_mirror(_args, destination):
        destination.mkdir(parents=True)
        for name in (
            "anima_config.json",
            "preferences.json",
            "self_model.json",
            "patterns.json",
            "metacognition_baselines.json",
        ):
            (destination / name).write_text("{}")

    monkeypatch.setattr(sync_state, "_remote", fake_remote)
    monkeypatch.setattr(sync_state, "_run", fake_run)
    monkeypatch.setattr(sync_state, "_mirror_learned_state", fake_mirror)

    snapshot = sync_state.sync_pull(args)

    assert sync_state._verify_sqlite(snapshot / "anima.db") is None
    assert sync_state._verify_sqlite(snapshot / "oauth.db") is None
    assert (snapshot / "anima_data" / "preferences.json").exists()
    assert (snapshot / "manifest.json").exists()
    assert (backup_root / "latest").resolve() == snapshot.resolve()
    assert any("src.backup(dst)" in command for command in remote_commands)
    assert any(command.startswith("rm -f /tmp/anima-predeploy-") for command in remote_commands)
    assert not list(backup_root.glob(".staging-*"))


def test_failed_pull_keeps_previous_latest_and_removes_staging(tmp_path, monkeypatch):
    backup_root = tmp_path / "predeploy"
    previous = backup_root / "20260810T120000.000000Z"
    previous.mkdir(parents=True)
    (previous / "manifest.json").write_text("{}")
    (backup_root / "latest").symlink_to(previous.name, target_is_directory=True)
    args = _args(backup_root)

    monkeypatch.setattr(sync_state, "_remote", lambda *_a, **_k: None)
    monkeypatch.setattr(
        sync_state,
        "_run",
        lambda *_a, **_k: (_ for _ in ()).throw(sync_state.SyncError("transfer failed")),
    )

    with pytest.raises(sync_state.SyncError, match="transfer failed"):
        sync_state.sync_pull(args)

    assert os.readlink(backup_root / "latest") == previous.name
    assert not list(backup_root.glob(".staging-*"))


def test_pruning_never_deletes_newly_published_snapshot_if_clock_moved(tmp_path):
    names = [
        "20260809T120000.000000Z",
        "20260810T120000.000000Z",
        "20260811T120000.000000Z",
    ]
    snapshots = []
    for name in names:
        path = tmp_path / name
        path.mkdir()
        (path / "manifest.json").write_text("{}")
        snapshots.append(path)

    sync_state._prune_snapshot_generations(
        tmp_path,
        2,
        preserve=snapshots[0],
    )

    assert snapshots[0].exists()
    assert not snapshots[1].exists()
    assert snapshots[2].exists()
