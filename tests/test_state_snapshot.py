import json
import sqlite3

import pytest

from anima_mcp.state_snapshot import (
    StateSnapshotError,
    create_local_state_snapshot,
    ensure_persistent_config,
)


def _database(path):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE identity (creature_id TEXT)")
        connection.execute("INSERT INTO identity VALUES ('lumen')")


def _learned_state(path):
    for name in (
        "anima_config.json",
        "preferences.json",
        "self_model.json",
        "patterns.json",
        "metacognition_baselines.json",
    ):
        (path / name).write_text("{}")


def test_migrates_checkout_yaml_calibration_into_persistent_json(tmp_path, monkeypatch):
    source = tmp_path / "checkout.yaml"
    source.write_text("display:\n  led_brightness: 0.27\n")
    state = tmp_path / "state"
    monkeypatch.setenv("ANIMA_CONFIG", str(source))

    destination = ensure_persistent_config(data_dir=state)

    assert destination == state / "anima_config.json"
    assert json.loads(destination.read_text()) == {
        "display": {"led_brightness": 0.27}
    }


def test_local_snapshot_captures_wal_consistent_db_json_and_events(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    db = state / "anima.db"
    _database(db)
    oauth = state / "oauth.db"
    with sqlite3.connect(oauth) as connection:
        connection.execute("CREATE TABLE clients (client_id TEXT)")
        connection.execute("INSERT INTO clients VALUES ('federation-client')")
    _learned_state(state)
    (state / "self_model.json").write_text('{"beliefs": {}}')
    inbox = state / "learning_inbox"
    inbox.mkdir()
    (inbox / "event.json").write_text('{"event_id": "one"}')

    snapshot = create_local_state_snapshot(
        db_path=db,
        data_dir=state,
        backup_root=tmp_path / "backups",
    )

    with sqlite3.connect(snapshot / "anima.db") as connection:
        assert connection.execute("SELECT creature_id FROM identity").fetchone() == (
            "lumen",
        )
    assert json.loads(
        (snapshot / "anima_data" / "self_model.json").read_text()
    ) == {"beliefs": {}}
    with sqlite3.connect(snapshot / "oauth.db") as connection:
        assert connection.execute("SELECT client_id FROM clients").fetchone() == (
            "federation-client",
        )
    assert (snapshot / "anima_data" / "learning_inbox" / "event.json").exists()
    assert json.loads((snapshot / "manifest.json").read_text())[
        "database_integrity"
    ] == "ok"


def test_local_snapshot_rejects_invalid_learned_json(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    db = state / "anima.db"
    _database(db)
    _learned_state(state)
    (state / "self_model.json").write_text("not json")

    with pytest.raises(StateSnapshotError, match="self_model.json"):
        create_local_state_snapshot(
            db_path=db,
            data_dir=state,
            backup_root=tmp_path / "backups",
        )

    assert not list((tmp_path / "backups").glob(".staging-*"))


def test_local_snapshot_rejects_incomplete_learned_state(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    db = state / "anima.db"
    _database(db)
    (state / "self_model.json").write_text("{}")

    with pytest.raises(StateSnapshotError, match="learned snapshot is incomplete"):
        create_local_state_snapshot(
            db_path=db,
            data_dir=state,
            backup_root=tmp_path / "backups",
        )


def test_local_snapshot_retention_preserves_new_generation(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    db = state / "anima.db"
    _database(db)
    _learned_state(state)
    backup_root = tmp_path / "backups"

    first = create_local_state_snapshot(
        db_path=db,
        data_dir=state,
        backup_root=backup_root,
        keep=1,
    )
    second = create_local_state_snapshot(
        db_path=db,
        data_dir=state,
        backup_root=backup_root,
        keep=1,
    )

    assert second.exists()
    assert not first.exists()
