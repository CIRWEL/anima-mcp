"""Deployment wiring must preserve the single-owner runtime architecture."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_systemd_units_pin_single_owners():
    server = (ROOT / "systemd" / "anima.service").read_text()
    broker = (ROOT / "systemd" / "anima-broker.service").read_text()

    assert 'Environment="ANIMA_SENSORS_BACKEND=shm"' in server
    assert 'Environment="ANIMA_BROKER_AGENCY_ENABLED=false"' in broker


def test_deploy_syncs_core_units_before_restart():
    script = (ROOT / "deploy.sh").read_text()

    sync_at = script.index("Syncing core systemd units")
    restart_at = script.index("Restarting anima service")
    assert sync_at < restart_at
    assert "anima.service anima-broker.service" in script
    assert '"set -e; changed=0;' in script
    assert "sudo install -m 0644" in script
    assert "sudo systemctl daemon-reload" in script


def test_bootstrap_restarts_both_services_after_unit_install():
    script = (ROOT / "scripts" / "bootstrap_deploy.py").read_text()

    install_at = script.index("Synchronizing core systemd units")
    restart_at = script.index("Restarting broker and anima services")
    assert install_at < restart_at
    assert '["sudo", "systemctl", "restart", "anima-broker", "anima"]' in script
