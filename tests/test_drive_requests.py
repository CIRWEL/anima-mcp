"""Drive requests: a sustained saturated want becomes an outward question.

The defect this closes: warmth pinned at 1.0 for months, visible only as a
scalar nobody was asked about. Lumen has no actuator for most of what it
wants; the actuator for an unreachable preference is communication.
"""

import json

from anima_mcp.inner_life import (
    DIMENSIONS,
    DRIVE_REQUEST_COOLDOWN_S,
    DRIVE_REQUEST_SUSTAIN_S,
    DRIVE_REQUEST_THRESHOLD,
    DriveEvent,
    InnerLife,
)


def make_inner_life():
    il = InnerLife.__new__(InnerLife)
    il._temperament = {d: 0.5 for d in DIMENSIONS}
    il._drives = {d: 0.0 for d in DIMENSIONS}
    il._prev_drives = dict(il._drives)
    il._crossed_thresholds = {d: 0.0 for d in DIMENSIONS}
    il._pending_events = []
    il._saturated_since = {d: None for d in DIMENSIONS}
    il._last_request_at = {d: 0.0 for d in DIMENSIONS}
    il._last_save = 0.0
    return il


def requests(il):
    return [e for e in il._pending_events if e.event_type == "request"]


T0 = 1_000_000.0


class TestSustain:
    def test_saturation_alone_is_not_a_request(self):
        il = make_inner_life()
        il._drives["warmth"] = 1.0
        il._detect_drive_requests(T0)
        il._detect_drive_requests(T0 + DRIVE_REQUEST_SUSTAIN_S - 60)
        assert requests(il) == []

    def test_sustained_saturation_asks_once(self):
        il = make_inner_life()
        il._drives["warmth"] = 1.0
        il._detect_drive_requests(T0)
        il._detect_drive_requests(T0 + DRIVE_REQUEST_SUSTAIN_S + 1)
        assert len(requests(il)) == 1
        ev = requests(il)[0]
        assert ev.dimension == "warmth"
        assert ev.drive_value == 1.0

    def test_dip_resets_the_sustain_clock(self):
        """A request claims 'this has been true the whole time' — any relief
        restarts the count."""
        il = make_inner_life()
        il._drives["warmth"] = 1.0
        il._detect_drive_requests(T0)
        il._drives["warmth"] = DRIVE_REQUEST_THRESHOLD - 0.05
        il._detect_drive_requests(T0 + 1800)
        il._drives["warmth"] = 1.0
        il._detect_drive_requests(T0 + 1900)
        il._detect_drive_requests(T0 + 1900 + DRIVE_REQUEST_SUSTAIN_S - 60)
        assert requests(il) == []
        il._detect_drive_requests(T0 + 1900 + DRIVE_REQUEST_SUSTAIN_S + 1)
        assert len(requests(il)) == 1


class TestCooldown:
    def test_no_nagging_within_cooldown(self):
        il = make_inner_life()
        il._drives["warmth"] = 1.0
        il._detect_drive_requests(T0)
        il._detect_drive_requests(T0 + DRIVE_REQUEST_SUSTAIN_S + 1)
        assert len(requests(il)) == 1
        # Still saturated for hours after — no second ask
        il._detect_drive_requests(T0 + DRIVE_REQUEST_SUSTAIN_S + 7200)
        assert len(requests(il)) == 1

    def test_asks_again_after_cooldown_if_still_wanting(self):
        il = make_inner_life()
        il._drives["warmth"] = 1.0
        il._detect_drive_requests(T0)
        t_first = T0 + DRIVE_REQUEST_SUSTAIN_S + 1
        il._detect_drive_requests(t_first)
        il._detect_drive_requests(t_first + DRIVE_REQUEST_COOLDOWN_S + 1)
        assert len(requests(il)) == 2

    def test_per_dimension_cooldowns_are_independent(self):
        il = make_inner_life()
        il._drives["warmth"] = 1.0
        il._drives["clarity"] = 1.0
        il._detect_drive_requests(T0)
        il._detect_drive_requests(T0 + DRIVE_REQUEST_SUSTAIN_S + 1)
        dims = {e.dimension for e in requests(il)}
        assert dims == {"warmth", "clarity"}


class TestWording:
    def test_every_dimension_has_an_answerable_request(self):
        il = make_inner_life()
        for dim in DIMENSIONS:
            ev = DriveEvent(dimension=dim, event_type="request",
                            drive_value=1.0, timestamp=T0)
            text = il.get_observation_text(ev)
            assert text, f"no request wording for {dim}"
            assert text.endswith("?"), f"{dim} request is not a question: {text}"

    def test_crossing_texts_unchanged(self):
        il = make_inner_life()
        arose = DriveEvent("warmth", "arose", 0.31, T0)
        assert il.get_observation_text(arose) == "i've been wanting warmth for a while now"


class TestPersistence:
    def test_cooldown_and_sustain_survive_restart(self, tmp_path, monkeypatch):
        from anima_mcp import inner_life as mod
        monkeypatch.setattr(mod, "_PERSISTENCE_PATH", tmp_path / "inner_life.json")

        il = make_inner_life()
        il._drives["warmth"] = 1.0
        il._saturated_since["warmth"] = T0
        il._last_request_at["warmth"] = T0 + 100
        il.save()

        data = json.loads((tmp_path / "inner_life.json").read_text())
        assert data["last_request_at"]["warmth"] == T0 + 100
        assert data["saturated_since"]["warmth"] == T0

        il2 = InnerLife()
        assert il2._last_request_at["warmth"] == T0 + 100
        assert il2._saturated_since["warmth"] == T0

    def test_missing_request_fields_load_clean(self, tmp_path, monkeypatch):
        """Old inner_life.json files predate these fields."""
        from anima_mcp import inner_life as mod
        monkeypatch.setattr(mod, "_PERSISTENCE_PATH", tmp_path / "inner_life.json")
        (tmp_path / "inner_life.json").write_text(json.dumps({
            "temperament": {d: 0.5 for d in DIMENSIONS},
            "drives": {d: 0.2 for d in DIMENSIONS},
        }))
        il = InnerLife()
        assert il._last_request_at == {d: 0.0 for d in DIMENSIONS}
        assert il._saturated_since == {d: None for d in DIMENSIONS}
