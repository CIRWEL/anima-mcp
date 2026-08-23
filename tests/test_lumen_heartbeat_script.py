"""Tests for scripts/lumen-heartbeat.sh — the outbound dead-man's switch.

The point of the switch is that it cannot fail quietly. Every path here exists
because the naive version of this script (a cron line that curls a URL) would
have reported healthy through every software failure Lumen has ever had: it
proves the Pi has power, not that Lumen is alive.

Strategy: the script takes its paths from the environment, so no rewriting is
needed. `curl` is stubbed through a PATH overlay that records the URL it was
called with, which is the only externally visible behaviour that matters.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "lumen-heartbeat.sh"

PING = "https://hc-ping.test/abc123"


@pytest.fixture
def rig(tmp_path):
    """Env + a curl stub that records every URL it is handed."""
    calls = tmp_path / "curl-calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "curl"
    # Records every URL curl is handed. CURL_FAIL_URLS is a space-separated list
    # of substrings; a request matching any of them exits non-zero, so a test can
    # kill one endpoint (the server probe, say) without killing the others.
    stub.write_text(
        "#!/bin/bash\n"
        f'for a in "$@"; do case "$a" in http*) echo "$a" >> "{calls}";\n'
        '    for f in ${CURL_FAIL_URLS:-}; do case "$a" in *"$f"*) exit 7;; esac; done;;\n'
        '  esac; done\n'
        '[ -n "${CURL_SHOULD_FAIL:-}" ] && exit 7\nexit 0\n'
    )
    stub.chmod(0o755)

    env_file = tmp_path / "anima.env"
    env_file.write_text(f"ANIMA_HEARTBEAT_URL={PING}\n")

    log = tmp_path / "heartbeat.log"
    shm = tmp_path / "anima_state.json"
    shadow = tmp_path / "anima_state.shadow.json"
    day_summary = tmp_path / "day_summaries.json"
    anima_history = tmp_path / "anima_history.json"

    def run(extra_env=None):
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["ANIMA_ENV_FILE"] = str(env_file)
        env["ANIMA_HEARTBEAT_LOG"] = str(log)
        env["ANIMA_SHM_PATH"] = str(shm)
        env["ANIMA_HEARTBEAT_SHADOW_PATH"] = str(shadow)
        env["DAY_SUMMARY_PATH"] = str(day_summary)
        env["ANIMA_HISTORY_PATH"] = str(anima_history)
        # The curl stub answers 200 for everything, so the server probe passes
        # unless a test overrides it.
        env["ANIMA_HEARTBEAT_SERVER_URL"] = "http://server.test/health"
        env["ANIMA_HEARTBEAT_INERT_MARK"] = str(tmp_path / ".inert-mark")
        env.pop("ANIMA_HEARTBEAT_URL", None)
        env.update(extra_env or {})
        return subprocess.run(
            ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60
        )

    def pinged():
        """Only heartbeat-provider URLs; the server health probe is not a ping."""
        if not calls.exists():
            return []
        return [u for u in calls.read_text().splitlines() if u.startswith(PING)]

    def _write(path, age_seconds=0, stamp_age_seconds=None):
        stamp = datetime.now() - timedelta(
            seconds=stamp_age_seconds if stamp_age_seconds is not None else age_seconds
        )
        path.write_text(json.dumps({"updated_at": stamp.isoformat(), "data": {}}))
        if age_seconds:
            old = time.time() - age_seconds
            os.utime(path, (old, old))

    def write_envelope(age_seconds=0, stamp_age_seconds=None, shadow_age=0):
        """Write the broker envelope; keep the shadow healthy unless told otherwise."""
        _write(shm, age_seconds, stamp_age_seconds)
        _write(shadow, shadow_age)

    def write_shadow(age_seconds=0):
        _write(shadow, age_seconds)

    def write_day_summary(
        writer_age_seconds=0,
        evidence_age_seconds=0,
        *,
        include_written_at=True,
        mtime_age_seconds=None,
    ):
        payload = {
            "summaries": [{
                "date": (
                    datetime.now() - timedelta(seconds=evidence_age_seconds)
                ).isoformat(),
                "center": [0.5, 0.5, 0.5, 0.5],
                "variance": [0.0, 0.0, 0.0, 0.0],
                "n_obs": 100,
                "hours": 1.0,
                "perturbations": 0,
                "trends": {},
            }],
            "version": "1.0",
        }
        if include_written_at:
            payload["written_at"] = (
                datetime.now() - timedelta(seconds=writer_age_seconds)
            ).isoformat()
        day_summary.write_text(json.dumps(payload))
        if mtime_age_seconds is not None:
            modified = time.time() - mtime_age_seconds
            os.utime(day_summary, (modified, modified))

    def write_anima_history(count=100, age_seconds=0):
        observed_at = (
            datetime.now() - timedelta(seconds=age_seconds)
        ).isoformat()
        anima_history.write_text(json.dumps({
            "observations": [
                {"t": observed_at, "w": 0.5, "c": 0.5, "s": 0.5, "p": 0.5}
                for _ in range(count)
            ],
            "version": "1.0",
        }))

    def write_bootstrap_marker(age_seconds=0):
        day_summary.write_text(json.dumps({
            "summaries": [],
            "writer_started_at": (
                datetime.now() - timedelta(seconds=age_seconds)
            ).isoformat(),
            "version": "1.0",
        }))

    # Existing heartbeat tests exercise other components. Give them honest,
    # fresh long-clock work output by default so a newly added probe cannot be
    # bypassed merely because the fixture forgot to model it.
    write_day_summary()
    write_anima_history()

    return type(
        "Rig", (), {"run": staticmethod(run), "pinged": staticmethod(pinged),
                    "write_envelope": staticmethod(write_envelope),
                    "write_shadow": staticmethod(write_shadow),
                    "write_day_summary": staticmethod(write_day_summary),
                    "write_anima_history": staticmethod(write_anima_history),
                    "write_bootstrap_marker": staticmethod(write_bootstrap_marker),
                    "log": log, "shm": shm, "shadow": shadow,
                    "day_summary": day_summary, "anima_history": anima_history,
                    "env_file": env_file}
    )


def test_fresh_envelope_pings_success(rig):
    rig.write_envelope(age_seconds=0)
    assert rig.run().returncode == 0
    assert rig.pinged() == [PING]


def test_stale_envelope_signals_failure(rig):
    """A broker that stopped writing must page immediately, not wait out the grace."""
    rig.write_envelope(age_seconds=600)
    assert rig.run().returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]


def test_missing_envelope_signals_failure(rig):
    assert not rig.shm.exists()
    assert rig.run().returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]


def test_corrupt_envelope_signals_failure(rig):
    """Unparseable must resolve to 'not fresh', never to a healthy default."""
    rig.shm.write_text("{not json")
    assert rig.run().returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]


def test_fresh_payload_over_stale_file_is_treated_as_stale(rig):
    """The worse of mtime and payload timestamp wins.

    A payload that claims to be fresh while the file has not been touched means
    something is republishing a cached value — exactly the shape that makes an
    instrument report health it cannot observe.
    """
    rig.write_envelope(age_seconds=600, stamp_age_seconds=0)
    assert rig.run().returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]


def test_unprovisioned_pi_is_inert_not_a_crash_loop(rig):
    rig.env_file.write_text("# no heartbeat url here\n")
    rig.write_envelope(age_seconds=0)
    result = rig.run()
    assert result.returncode == 0
    assert rig.pinged() == []
    assert "inert" in rig.log.read_text()


def test_inert_notice_is_rate_limited_to_daily(rig):
    """The timer fires every 5 min; 288 inert lines/day would bury real trouble."""
    rig.env_file.write_text("# no heartbeat url here\n")
    rig.write_envelope(age_seconds=0)
    for _ in range(4):
        assert rig.run().returncode == 0
    assert rig.log.read_text().count("inert") == 1


def test_unreachable_provider_does_not_masquerade_as_lumen_failure(rig):
    """The Pi's uplink dying is not Lumen dying; the provider sees it as absence."""
    rig.write_envelope(age_seconds=0)
    result = rig.run({"CURL_FAIL_URLS": "hc-ping.test"})
    assert result.returncode == 0
    assert "provider unreachable" in rig.log.read_text()


def test_max_age_is_configurable(rig):
    rig.write_envelope(age_seconds=200)
    assert rig.run({"ANIMA_HEARTBEAT_MAX_AGE": "300"}).returncode == 0
    assert rig.pinged() == [PING]


def test_anima_env_override_is_resolved_after_sourcing(rig):
    rig.env_file.write_text(
        f"ANIMA_HEARTBEAT_URL={PING}\nANIMA_HEARTBEAT_MAX_AGE=300\n"
    )
    rig.write_envelope(age_seconds=200)

    assert rig.run().returncode == 0
    assert rig.pinged() == [PING]


@pytest.mark.parametrize("invalid", ["bogus", "0", "-1", "999999999999999999999"])
def test_invalid_broker_max_age_fails_closed(rig, invalid):
    rig.write_envelope(age_seconds=0)

    assert rig.run({"ANIMA_HEARTBEAT_MAX_AGE": invalid}).returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]
    assert "MAX_AGE" in rig.log.read_text()


def test_happy_path_stays_quiet_in_the_log(rig):
    """This runs every 5 minutes forever; a chatty success path buries the signal."""
    rig.write_envelope(age_seconds=0)
    rig.run()
    assert not rig.log.exists() or rig.log.read_text().strip() == ""


# ---------------------------------------------------------------------------
# The long clock must prove both writer liveness and current source evidence
# ---------------------------------------------------------------------------


def test_fresh_day_summary_pings_success(rig):
    rig.write_envelope(age_seconds=0)
    rig.write_day_summary(writer_age_seconds=30, evidence_age_seconds=60)
    assert rig.run().returncode == 0
    assert rig.pinged() == [PING]


def test_stale_day_summary_evidence_fails_with_fresh_writer(rig):
    """A live writer republishing frozen evidence is not healthy work output."""
    rig.write_envelope(age_seconds=0)
    rig.write_day_summary(writer_age_seconds=0, evidence_age_seconds=36 * 3600 + 1)
    assert rig.run().returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]
    assert "day_summary stale" in rig.log.read_text()
    assert "evidence" in rig.log.read_text()


def test_stale_day_summary_writer_fails_with_fresh_evidence(rig):
    rig.write_envelope(age_seconds=0)
    rig.write_day_summary(writer_age_seconds=36 * 3600 + 1, evidence_age_seconds=0)
    assert rig.run().returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]
    assert "day_summary stale" in rig.log.read_text()
    assert "writer" in rig.log.read_text()


def test_legacy_day_summary_uses_mtime_as_writer_freshness(rig):
    rig.write_envelope(age_seconds=0)
    rig.write_day_summary(
        evidence_age_seconds=0,
        include_written_at=False,
        mtime_age_seconds=36 * 3600 + 1,
    )
    assert rig.run().returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]
    assert "day_summary stale" in rig.log.read_text()


def test_corrupt_day_summary_fails(rig):
    rig.write_envelope(age_seconds=0)
    rig.day_summary.write_text("{not json")
    assert rig.run().returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]
    assert "day_summary unreadable" in rig.log.read_text()


def test_missing_day_summary_fails_without_a_writer_marker(rig):
    rig.write_envelope(age_seconds=0)
    rig.day_summary.unlink()
    assert rig.run().returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]
    assert "no bootstrap marker" in rig.log.read_text()


def test_durable_bootstrap_marker_allows_initial_history_absence(rig):
    rig.write_envelope(age_seconds=0)
    rig.write_bootstrap_marker(age_seconds=60)
    rig.anima_history.unlink()

    assert rig.run().returncode == 0
    assert rig.pinged() == [PING]


def test_bootstrap_marker_allows_below_100_recent_observations(rig):
    rig.write_envelope(age_seconds=0)
    rig.write_bootstrap_marker(age_seconds=60)
    rig.write_anima_history(count=99, age_seconds=60)

    assert rig.run().returncode == 0
    assert rig.pinged() == [PING]


def test_bootstrap_marker_fails_once_source_is_eligible(rig):
    rig.write_envelope(age_seconds=0)
    rig.write_bootstrap_marker(age_seconds=60)
    rig.write_anima_history(count=100, age_seconds=60)

    assert rig.run().returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]
    assert "empty with eligible source" in rig.log.read_text()


def test_bootstrap_marker_expires_without_progress(rig):
    rig.write_envelope(age_seconds=0)
    rig.write_bootstrap_marker(age_seconds=1801)
    rig.anima_history.unlink()

    assert rig.run().returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]
    assert "bootstrap grace expired" in rig.log.read_text()


@pytest.mark.parametrize("variable", ["DAY_SUMMARY_MAX_AGE", "DAY_SUMMARY_BOOTSTRAP_GRACE_SECONDS"])
@pytest.mark.parametrize("invalid", ["bogus", "0", "nan", "inf"])
def test_invalid_day_summary_age_configuration_fails_closed(rig, variable, invalid):
    rig.write_envelope(age_seconds=0)

    assert rig.run({variable: invalid}).returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]
    assert "invalid" in rig.log.read_text()


@pytest.mark.parametrize("future_field", ["writer", "evidence"])
def test_future_day_summary_timestamp_fails(rig, future_field):
    rig.write_envelope(age_seconds=0)
    writer_age = -301 if future_field == "writer" else 0
    evidence_age = -301 if future_field == "evidence" else 0
    rig.write_day_summary(
        writer_age_seconds=writer_age,
        evidence_age_seconds=evidence_age,
    )
    assert rig.run().returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]
    assert "future-dated" in rig.log.read_text()


def test_small_clock_skew_is_tolerated(rig):
    rig.write_envelope(age_seconds=0)
    rig.write_day_summary(writer_age_seconds=-299, evidence_age_seconds=-299)
    assert rig.run().returncode == 0
    assert rig.pinged() == [PING]


# ---------------------------------------------------------------------------
# The creature is three processes; one process's work output is not the whole
# ---------------------------------------------------------------------------
#
# The first version gated only on the broker's envelope. If the MCP server died
# — agency learner, metacognition, growth, drawing, the whole tool surface — the
# broker kept writing, the envelope stayed fresh, and the switch would have
# pinged green forever. That is the exact failure the switch exists to prevent.


def test_dead_mcp_server_fails_even_with_fresh_envelopes(rig):
    rig.write_envelope(age_seconds=0)
    result = rig.run({"CURL_FAIL_URLS": "server.test"})
    assert result.returncode == 0
    assert rig.pinged()[-1].endswith("/fail")
    assert "MCP server not answering" in rig.log.read_text()


def test_dead_elixir_broker_fails_even_with_a_fresh_main_envelope(rig):
    """anima-broker-ex owns the governance check-ins; its silence is an outage."""
    rig.write_envelope(age_seconds=0, shadow_age=600)
    assert rig.run().returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]
    assert "broker_ex envelope stale" in rig.log.read_text()


def test_missing_shadow_envelope_fails(rig):
    rig.write_envelope(age_seconds=0)
    rig.shadow.unlink()
    assert rig.run().returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]
    assert "broker_ex envelope unreadable" in rig.log.read_text()


def test_all_three_healthy_pings_success(rig):
    rig.write_envelope(age_seconds=0)
    assert rig.run().returncode == 0
    assert rig.pinged() == [PING]


def test_skip_list_allows_a_documented_rollback(rig):
    """Reverting the Elixir broker leaves a stale shadow that would page forever."""
    rig.write_envelope(age_seconds=0, shadow_age=99999)
    assert rig.run({"ANIMA_HEARTBEAT_SKIP": "broker_ex"}).returncode == 0
    assert rig.pinged() == [PING]


def test_skip_list_allows_day_summary_writer_rollback(rig):
    rig.write_envelope(age_seconds=0)
    rig.day_summary.write_text("{not json")
    rig.env_file.write_text(
        f"ANIMA_HEARTBEAT_URL={PING}\nANIMA_HEARTBEAT_SKIP=day_summary\n"
    )
    assert rig.run().returncode == 0
    assert rig.pinged() == [PING]


def test_skip_list_does_not_disable_the_others(rig):
    rig.write_envelope(age_seconds=600, shadow_age=0)
    assert rig.run({"ANIMA_HEARTBEAT_SKIP": "broker_ex"}).returncode == 0
    assert rig.pinged() == [f"{PING}/fail"]
    assert "broker envelope stale" in rig.log.read_text()
