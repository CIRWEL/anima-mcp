"""Deployment wiring must preserve the single-owner runtime architecture."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_systemd_units_pin_single_owners():
    server = (ROOT / "systemd" / "anima.service").read_text()
    broker = (ROOT / "systemd" / "anima-broker.service").read_text()
    elixir_broker = (ROOT / "anima_broker" / "systemd" / "anima-broker-ex.service").read_text()

    assert 'Environment="ANIMA_SENSORS_BACKEND=shm"' in server
    assert 'Environment="ANIMA_CONFIG=/home/unitares-anima/.anima/anima_config.json"' in server
    assert 'Environment="ANIMA_CONFIG=/home/unitares-anima/.anima/anima_config.json"' in broker
    assert 'Environment="ANIMA_BROKER_AGENCY_ENABLED=false"' in broker
    assert 'Environment="ANIMA_BROKER_VOICE_ENABLED=false"' in broker
    assert "Requires=anima-restore.service" in broker
    assert "PartOf=anima.service" not in broker
    assert "UMask=0077" in server
    assert "UMask=0077" in broker
    assert "UMask=0077" in elixir_broker


def test_deploy_syncs_core_units_before_restart():
    script = (ROOT / "deploy.sh").read_text()

    sync_at = script.index("Syncing core systemd units")
    restart_at = script.index("Restarting anima service")
    assert sync_at < restart_at
    assert "anima-restore.service anima-broker.service anima.service" in script
    assert '"set -e; changed=0;' in script
    assert "sudo install -m 0644" in script
    assert "sudo systemctl daemon-reload" in script
    assert "sudo systemctl enable anima-restore.service" in script
    assert "scripts/deploy_elixir_broker.sh" in script
    assert "anima-broker-ex" in script
    assert "--exclude='anima_broker/_build'" in script
    assert "--exclude='anima_broker/deps'" in script
    assert "--exclude='.ruff_cache'" in script


def test_deploy_fails_closed_on_permissive_rest_and_hardens_state_modes():
    script = (ROOT / "deploy.sh").read_text()

    security_at = script.index("Checking runtime security")
    sync_at = script.index("Syncing code")
    assert security_at < sync_at
    assert "ANIMA_HTTP_ALLOW_UNAUTH_IF_NO_TOKEN" in script
    assert "ANIMA_OAUTH_DYNAMIC_REGISTRATION" in script
    assert "permissive-no-token" in script
    assert "registration_endpoint" in script
    assert 'chmod 700 "$HOME/.anima"' in script
    assert "chmod 600" in script
    assert "closed OAuth registration verified" in script


def test_deploy_fails_closed_on_backup_restart_or_runtime_verification():
    script = (ROOT / "deploy.sh").read_text()

    assert script.index("Migrating persistent calibration") < script.index("Backing up Pi state")
    assert "anima_config.json" in script
    assert "--skip-backup" in script
    assert 'python3 scripts/sync_state.py "${SYNC_ARGS[@]}"' in script
    assert "Verified state backup failed; deployment aborted" in script
    assert "sudo systemctl restart anima-broker anima" in script
    assert "systemctl is-active --quiet anima-broker" in script
    assert "ANIMA_SENSORS_BACKEND=shm" in script
    assert "/dev/shm/anima_state.json" in script
    assert "ServerAliveInterval=10" in script
    assert "for _attempt in 1 2 3" in script
    assert "Could not capture pre-restart service PIDs" in script
    assert "Restart connection interrupted; verifying changed service PIDs" in script
    assert "new_broker_pid" in script
    assert r'test \"\$new_broker_pid\" != ' in script
    assert r'test \"\$new_anima_pid\" != ' in script
    assert "'$OLD_BROKER_PID'" in script
    assert "'$OLD_ANIMA_PID'" in script
    assert "Restart or post-deploy verification failed" in script


def test_restore_quiesces_writers_and_restores_durable_event_inbox():
    script = (ROOT / "scripts" / "restore_lumen.sh").read_text()

    preflight_at = script.index("Recovery set verified and frozen before mutation")
    stop_at = script.index("Quiescing Lumen before restore")
    deploy_at = script.index("Deploying code")
    restore_at = script.index("Restoring Lumen data")
    assert preflight_at < stop_at < deploy_at < restore_at
    assert "anima_config.json preferences.json self_model.json patterns.json metacognition_baselines.json" in script
    assert "lumen-restore.XXXXXX" in script
    assert "--no-restart --skip-backup" in script
    assert "systemd/anima-restore.service" in script
    assert "scripts/deploy_elixir_broker.sh" in script
    assert "anima-broker-ex" in script
    assert "/dev/shm/anima_state.shadow.json" in script
    assert ".restore-anima.db" in script
    assert "PRAGMA integrity_check" in script
    assert '"$BACKUP/learning_inbox/"' in script
    assert "--delete" in script
    assert "refusing a silent fresh identity" in script
    assert "fresh shared state verified" in script


def test_nightly_backup_publishes_learned_state_only_from_staging():
    script = (ROOT / "scripts" / "backup_lumen_from_mac.sh").read_text()

    assert ".anima_data.staging." in script
    assert "anima_data.previous" in script
    assert "--exclude='*.db*'" in script
    assert "--exclude='anima.env*'" in script
    assert "this run is not a complete restore point" in script
    assert "MIRROR_CAPTURED -eq 1" in script
    assert "required restore state was incomplete" in script
    assert "lumen_recovery_${DAY_NAME}.tar" in script
    assert "hf_upload_with_watchdog" in script
    assert '"anima_${DATE}.db" "$(basename "$STATE_ARCHIVE")"' in script
    assert "PI_BACKUP_MAX_AGE_MINUTES" in script
    assert "recent Pi snapshot failed integrity_check" in script
    assert "~/.anima/oauth.db" in script
    assert "--exclude='./oauth.db'" in script


def test_predeploy_snapshot_uses_sqlite_backup_and_separate_bundle():
    script = (ROOT / "scripts" / "sync_state.py").read_text()

    assert "src.backup(dst)" in script
    assert "PRAGMA integrity_check" in script
    assert 'staging / "anima_data"' in script
    assert 'backup_root / "latest"' in script
    assert "LEGACY_LOCAL_DB" in script  # read-only compatibility for guarded push
    assert "shutil.copy2" not in script


def test_boot_restore_gates_silent_identity_replacement():
    script = (ROOT / "scripts" / "auto_restore.sh").read_text()
    unit = (ROOT / "systemd" / "anima-restore.service").read_text()

    assert "PRAGMA integrity_check" in script
    assert "learned_state_ok" in script
    assert "ANIMA_ALLOW_FRESH_START" in script
    assert "Refusing silent fresh start" in script
    assert ".auto-restore-state." in script
    assert ".auto-restore-db." in script
    assert "anima_data.previous" in script
    assert "learning_inbox/***" in script
    assert "find \"$ANIMA_DIR\" -maxdepth 1 -type f -name '*.json' -delete" in script
    assert ".pre-restore-anima.db" in script
    assert "anima_config.json preferences.json self_model.json patterns.json metacognition_baselines.json" in script
    assert "anima_data/anima.db" not in script
    assert "sqlite3 \"$DB_PATH\"" not in script
    assert "ConditionPathExists=!/run/anima-restore-attempted" in unit
    assert "ExecStartPost=/bin/touch /run/anima-restore-attempted" in unit
    assert "EnvironmentFile=-/home/unitares-anima/.anima/anima.env" in unit


def test_bootstrap_restarts_both_services_after_unit_install():
    script = (ROOT / "scripts" / "bootstrap_deploy.py").read_text()

    install_at = script.index("Synchronizing core systemd units")
    restart_at = script.index("Restarting broker and anima services")
    assert install_at < restart_at
    assert "deploy_elixir_broker.sh" in script
    assert '["sudo", "systemctl", "restart", "anima-broker", "anima"]' in script


def test_elixir_deploy_is_change_aware_and_verifies_shadow_state():
    script = (ROOT / "scripts" / "deploy_elixir_broker.sh").read_text()

    assert ".source-sha256" in script
    assert ".restart-required" in script
    assert "mix compile --warnings-as-errors" in script
    assert "mix release --overwrite" in script
    assert "sudo systemctl restart anima-broker-ex" in script
    assert "/dev/shm/anima_state.shadow.json" in script
    assert "Elixir broker is active but did not publish fresh shadow state" in script


def test_server_never_initializes_a_direct_sensor_backend():
    server = (ROOT / "src" / "anima_mcp" / "server.py").read_text()
    accessors = (ROOT / "src" / "anima_mcp" / "accessors.py").read_text()

    assert "from .sensors import get_sensors" not in server
    assert 'get_sensors(backend="shm")' in accessors
    assert "no direct sensor takeover" in server
