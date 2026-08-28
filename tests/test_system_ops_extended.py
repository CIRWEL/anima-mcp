import json
import subprocess
from pathlib import Path as RealPath
from unittest.mock import MagicMock, patch

import pytest

from conftest import parse_result

# These exercise what the system-ops handlers DO. The admin gate fails closed
# without a secret, so authenticate first — otherwise every test here would
# assert against the gate's refusal instead of the handler's behavior.
pytestmark = pytest.mark.usefixtures("admin_authorized")


def _cp(returncode=0, stdout="", stderr=""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


@pytest.mark.asyncio
class TestSystemServiceExtended:
    async def test_missing_service_param_returns_error(self):
        from anima_mcp.handlers.system_ops import handle_system_service

        data = parse_result(await handle_system_service({"action": "status"}))
        assert "service parameter required" in data["error"]

    async def test_invalid_service_rejected(self):
        from anima_mcp.handlers.system_ops import handle_system_service

        data = parse_result(await handle_system_service({"service": "postgres", "action": "status"}))
        assert "not in allowed list" in data["error"]
        assert "allowed" in data

    async def test_invalid_action_rejected(self):
        from anima_mcp.handlers.system_ops import handle_system_service

        data = parse_result(await handle_system_service({"service": "anima", "action": "reload"}))
        assert "not allowed" in data["error"]
        assert "allowed" in data

    async def test_rpi_connect_start_uses_rpi_cli_path(self):
        from anima_mcp.handlers.system_ops import handle_system_service

        with patch("anima_mcp.handlers.system_ops.subprocess.run", return_value=_cp(stdout="enabled")) as run_mock:
            data = parse_result(await handle_system_service({"service": "rpi-connect", "action": "start"}))

        run_mock.assert_called_once()
        assert data["success"] is True
        assert data["action"] == "rpi-connect on"

    async def test_status_includes_is_active(self):
        from anima_mcp.handlers.system_ops import handle_system_service

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=[_cp(stdout="anima status"), _cp(stdout="active\n")],
        ):
            data = parse_result(await handle_system_service({"service": "anima", "action": "status"}))

        assert data["success"] is True
        assert data["action"] == "status"
        assert data["is_active"] is True

    async def test_timeout_returns_error(self):
        from anima_mcp.handlers.system_ops import handle_system_service

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="systemctl", timeout=30),
        ):
            data = parse_result(await handle_system_service({"service": "anima", "action": "restart"}))

        assert "error" in data
        assert "timed out" in data["error"]

    async def test_command_not_found_returns_error(self):
        from anima_mcp.handlers.system_ops import handle_system_service

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=FileNotFoundError("systemctl"),
        ):
            data = parse_result(await handle_system_service({"service": "anima", "action": "status"}))

        assert "error" in data
        assert "Command not found" in data["error"]


@pytest.mark.asyncio
class TestFixSshPortExtended:
    async def test_invalid_port_rejected(self):
        from anima_mcp.handlers.system_ops import handle_fix_ssh_port

        data = parse_result(await handle_fix_ssh_port({"port": 9999}))
        assert "port must be 22, 2222, or 22222" in data["error"]
        assert "@lumen" in data["usage_22"]

    async def test_invalid_port_uses_configured_pi_host(self, monkeypatch):
        from anima_mcp.handlers.system_ops import handle_fix_ssh_port

        monkeypatch.setenv("ANIMA_PI_HOST", "100.1.2.3")
        data = parse_result(await handle_fix_ssh_port({"port": 9999}))
        assert "@100.1.2.3" in data["usage_2222"]

    async def test_port_22_reset_success(self):
        from anima_mcp.handlers.system_ops import handle_fix_ssh_port

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=[_cp(returncode=0), _cp(returncode=0, stderr="")],
        ):
            data = parse_result(await handle_fix_ssh_port({"port": 22}))

        assert data["success"] is True
        assert data["port"] == 22

    async def test_port_already_configured_restarts_ssh(self):
        from anima_mcp.handlers.system_ops import handle_fix_ssh_port

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=[_cp(returncode=0), _cp(returncode=0)],
        ):
            data = parse_result(await handle_fix_ssh_port({"port": 2222}))

        assert data["success"] is True
        assert "already on port 2222" in data["message"]

    async def test_port_append_failure_returns_error(self):
        from anima_mcp.handlers.system_ops import handle_fix_ssh_port

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=[
                _cp(returncode=1),  # grep: not found
                _cp(returncode=1, stderr="tee failed"),  # echo append fails
            ],
        ):
            data = parse_result(await handle_fix_ssh_port({"port": 22222}))

        assert data["success"] is False
        assert "Failed to update sshd_config" in data["error"]

    async def test_timeout_returns_error(self):
        from anima_mcp.handlers.system_ops import handle_fix_ssh_port

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="grep", timeout=5),
        ):
            data = parse_result(await handle_fix_ssh_port({"port": 2222}))

        assert data["success"] is False
        assert "timed out" in data["error"]

    async def test_unexpected_error_returns_stringified_error(self):
        from anima_mcp.handlers.system_ops import handle_fix_ssh_port

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=RuntimeError("kaboom"),
        ):
            data = parse_result(await handle_fix_ssh_port({"port": 2222}))

        assert data["success"] is False
        assert data["error"] == "kaboom"


@pytest.mark.asyncio
class TestSetupTailscaleExtended:
    async def test_setup_tailscale_requires_auth_key(self):
        from anima_mcp.handlers.system_ops import handle_setup_tailscale

        data = parse_result(await handle_setup_tailscale({}))
        assert "auth_key required" in data["error"]

    async def test_setup_tailscale_rejects_bad_key_prefix(self):
        from anima_mcp.handlers.system_ops import handle_setup_tailscale

        data = parse_result(await handle_setup_tailscale({"auth_key": "abc"}))
        assert "Invalid auth_key format" in data["error"]

    async def test_setup_tailscale_install_failure(self):
        from anima_mcp.handlers.system_ops import handle_setup_tailscale

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            return_value=_cp(returncode=1, stderr="install failed"),
        ):
            data = parse_result(await handle_setup_tailscale({"auth_key": "tskey-auth-abc"}))

        assert data["success"] is False
        assert "Install failed" in data["error"]

    async def test_setup_tailscale_success_returns_ip_and_mcp_url(self):
        from anima_mcp.handlers.system_ops import handle_setup_tailscale

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=[
                _cp(returncode=0),                         # install
                _cp(returncode=0),                         # tailscale up
                _cp(returncode=0, stdout="100.78.71.1\n"),  # tailscale ip -4
            ],
        ):
            data = parse_result(await handle_setup_tailscale({"auth_key": "tskey-auth-abc"}))

        assert data["success"] is True
        assert data["tailscale_ip"] == "100.78.71.1"
        assert data["mcp_url"] == "http://100.78.71.1:8766/mcp/"

    async def test_setup_tailscale_up_failure(self):
        from anima_mcp.handlers.system_ops import handle_setup_tailscale

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=[
                _cp(returncode=0),  # install
                _cp(returncode=1, stderr="bad key"),  # tailscale up
            ],
        ):
            data = parse_result(await handle_setup_tailscale({"auth_key": "tskey-auth-abc"}))

        assert data["success"] is False
        assert "hint" in data

    async def test_setup_tailscale_timeout_returns_error(self):
        from anima_mcp.handlers.system_ops import handle_setup_tailscale

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="tailscale", timeout=120),
        ):
            data = parse_result(await handle_setup_tailscale({"auth_key": "tskey-auth-abc"}))

        assert data["success"] is False
        assert "timed out" in data["error"]

    async def test_setup_tailscale_unexpected_error_returns_error(self):
        from anima_mcp.handlers.system_ops import handle_setup_tailscale

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=RuntimeError("oops"),
        ):
            data = parse_result(await handle_setup_tailscale({"auth_key": "tskey-auth-abc"}))

        assert data["success"] is False
        assert data["error"] == "oops"


@pytest.mark.asyncio
class TestSystemPowerExtended:
    async def test_invalid_power_action_rejected(self):
        from anima_mcp.handlers.system_ops import handle_system_power

        data = parse_result(await handle_system_power({"action": "hibernate"}))
        assert "not allowed" in data["error"]

    async def test_status_returns_uptime_text(self):
        from anima_mcp.handlers.system_ops import handle_system_power

        with patch("anima_mcp.handlers.system_ops.subprocess.run", return_value=_cp(stdout="up 10 minutes")):
            data = parse_result(await handle_system_power({"action": "status"}))

        assert data["action"] == "status"
        assert "up 10 minutes" in data["uptime"]

    async def test_reboot_requires_confirm(self):
        from anima_mcp.handlers.system_ops import handle_system_power

        data = parse_result(await handle_system_power({"action": "reboot", "confirm": False}))
        assert "requires confirm=true" in data["error"]

    async def test_reboot_with_confirm_schedules_shutdown(self):
        from anima_mcp.handlers.system_ops import handle_system_power

        with patch("anima_mcp.handlers.system_ops.subprocess.Popen") as popen_mock:
            data = parse_result(await handle_system_power({"action": "reboot", "confirm": True}))

        popen_mock.assert_called_once()
        assert data["success"] is True
        assert data["action"] == "reboot"

    async def test_shutdown_with_confirm_schedules_shutdown(self):
        from anima_mcp.handlers.system_ops import handle_system_power

        with patch("anima_mcp.handlers.system_ops.subprocess.Popen") as popen_mock:
            data = parse_result(await handle_system_power({"action": "shutdown", "confirm": True}))

        popen_mock.assert_called_once()
        assert data["success"] is True
        assert data["action"] == "shutdown"

    async def test_power_timeout_returns_error(self):
        from anima_mcp.handlers.system_ops import handle_system_power

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="uptime", timeout=10),
        ):
            data = parse_result(await handle_system_power({"action": "status"}))

        assert "timed out" in data["error"]

    async def test_power_unexpected_error_returns_error(self):
        from anima_mcp.handlers.system_ops import handle_system_power

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.Popen",
            side_effect=RuntimeError("no permission"),
        ):
            data = parse_result(await handle_system_power({"action": "shutdown", "confirm": True}))

        assert "Power command failed" in data["error"]


@pytest.mark.asyncio
class TestDelayedRestartExtended:
    async def test_delayed_restart_writes_lockfile_and_restarts(self, tmp_path):
        from anima_mcp.handlers.system_ops import RESTART_WAIT_SECONDS, _delayed_restart

        lockfile = tmp_path / "restart.lock"
        with patch("anima_mcp.handlers.system_ops.RESTART_LOCKFILE", lockfile), patch(
            "anima_mcp.handlers.system_ops.asyncio.sleep"
        ), patch("anima_mcp.handlers.system_ops.subprocess.Popen") as popen_mock:
            await _delayed_restart()

        data = json.loads(lockfile.read_text())
        assert data["wait_seconds"] == RESTART_WAIT_SECONDS
        popen_mock.assert_called_once()
        # Both units, explicitly: the broker unit has no PartOf=, so restarting
        # only 'anima' leaves the learning/belief writer on stale code — the
        # 2026-08-21 deploy shipped #184 to a broker that kept running pre-fix.
        cmd = popen_mock.call_args.args[0]
        assert cmd == ["sudo", "systemctl", "restart", "anima-broker", "anima"]

    async def test_delayed_restart_continues_if_lockfile_write_fails(self):
        from anima_mcp.handlers.system_ops import _delayed_restart

        class _BadLockfile:
            def write_text(self, *_args, **_kwargs):
                raise OSError("read-only")

        with patch("anima_mcp.handlers.system_ops.RESTART_LOCKFILE", _BadLockfile()), patch(
            "anima_mcp.handlers.system_ops.asyncio.sleep"
        ), patch("anima_mcp.handlers.system_ops.subprocess.Popen") as popen_mock:
            await _delayed_restart()

        popen_mock.assert_called_once()


class TestSyncSystemdServicesExtended:
    def test_sync_systemd_services_returns_empty_when_source_missing(self, tmp_path):
        from anima_mcp.handlers.system_ops import _sync_systemd_services

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        assert _sync_systemd_services(repo_root) == []

    def test_sync_systemd_services_installs_whitelisted_unit_and_reload(self, tmp_path):
        from anima_mcp.handlers.system_ops import _sync_systemd_services

        repo_root = tmp_path / "repo"
        systemd_dir = repo_root / "systemd"
        target_dir = tmp_path / "etc-systemd"
        systemd_dir.mkdir(parents=True)
        target_dir.mkdir()
        (systemd_dir / "anima-restore.service").write_text("[Unit]\nDescription=test", encoding="utf-8")

        def _fake_path(value):
            return target_dir if str(value) == "/etc/systemd/system" else RealPath(value)

        with patch("anima_mcp.handlers.system_ops.Path", side_effect=_fake_path), patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=[_cp(returncode=0), _cp(returncode=0), _cp(returncode=0)],
        ) as run_mock:
            synced = _sync_systemd_services(repo_root)

        assert synced == ["anima-restore.service (installed)"]
        assert any("enable" in call.args[0] for call in run_mock.call_args_list)
        assert any("daemon-reload" in call.args[0] for call in run_mock.call_args_list)

    def test_sync_systemd_services_updates_existing_changed_unit(self, tmp_path):
        from anima_mcp.handlers.system_ops import _sync_systemd_services

        repo_root = tmp_path / "repo"
        systemd_dir = repo_root / "systemd"
        target_dir = tmp_path / "etc-systemd"
        systemd_dir.mkdir(parents=True)
        target_dir.mkdir()
        (systemd_dir / "anima.service").write_text("new-content", encoding="utf-8")
        (target_dir / "anima.service").write_text("old-content", encoding="utf-8")

        def _fake_path(value):
            return target_dir if str(value) == "/etc/systemd/system" else RealPath(value)

        with patch("anima_mcp.handlers.system_ops.Path", side_effect=_fake_path), patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=[_cp(returncode=0), _cp(returncode=0)],
        ):
            synced = _sync_systemd_services(repo_root)

        assert synced == ["anima.service"]

    def test_sync_systemd_services_fails_closed_when_unit_install_fails(self, tmp_path):
        from anima_mcp.handlers.system_ops import _sync_systemd_services

        repo_root = tmp_path / "repo"
        systemd_dir = repo_root / "systemd"
        target_dir = tmp_path / "etc-systemd"
        systemd_dir.mkdir(parents=True)
        target_dir.mkdir()
        (systemd_dir / "anima-restore.service").write_text("[Unit]\n", encoding="utf-8")

        def _fake_path(value):
            return target_dir if str(value) == "/etc/systemd/system" else RealPath(value)

        with patch("anima_mcp.handlers.system_ops.Path", side_effect=_fake_path), patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            return_value=_cp(returncode=1, stderr="permission denied"),
        ), pytest.raises(RuntimeError, match="permission denied"):
            _sync_systemd_services(repo_root)


@pytest.mark.asyncio
class TestGitPullExtended:
    async def test_git_pull_success_includes_latest_commit(self):
        from anima_mcp.handlers.system_ops import handle_git_pull

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=[
                _cp(returncode=0, stdout="Already up to date.\n"),  # git pull
                _cp(returncode=0, stdout="abc123 test commit\n"),    # git log -1
            ],
        ), patch("anima_mcp.handlers.system_ops._sync_systemd_services", return_value=[]):
            data = parse_result(await handle_git_pull({"restart": False}))

        assert data["success"] is True
        assert data["latest_commit"] == "abc123 test commit"
        assert "note" in data

    async def test_git_pull_timeout_returns_error(self):
        from anima_mcp.handlers.system_ops import handle_git_pull

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git pull", timeout=60),
        ):
            data = parse_result(await handle_git_pull({}))

        assert data["error"] == "Git pull timed out"

    async def test_git_pull_stash_force_and_restart(self):
        from anima_mcp.handlers.system_ops import handle_git_pull

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=[
                _cp(returncode=0, stdout="Saved working directory"),  # stash
                _cp(returncode=0, stdout="fetch ok"),                 # fetch
                _cp(returncode=0, stdout="reset ok"),                 # reset --hard
                _cp(returncode=0, stdout="pulled"),                   # pull
                _cp(returncode=0, stdout="def456 latest\n"),          # log
            ],
        ), patch(
            "anima_mcp.handlers.system_ops._sync_systemd_services",
            return_value=["anima-restore.service (installed)"],
        ), patch(
            "anima_mcp.handlers.system_ops.asyncio.create_task"
        ) as create_task_mock, patch(
            "anima_mcp.state_snapshot.create_local_state_snapshot",
            return_value=RealPath("/tmp/predeploy-snapshot"),
        ):
            data = parse_result(await handle_git_pull({"stash": True, "force": True, "restart": True}))

        assert data["success"] is True
        assert data["latest_commit"] == "def456 latest"
        assert "restart" in data
        assert data["state_backup"] == "/tmp/predeploy-snapshot"
        assert "synced_services" in data
        create_task_mock.assert_called_once()
        # Prevent "coroutine was never awaited" warning in test runtime.
        create_task_mock.call_args[0][0].close()

    async def test_git_pull_backup_failure_does_not_schedule_restart(self):
        from anima_mcp.handlers.system_ops import handle_git_pull

        with patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=[
                _cp(returncode=0, stdout="pulled"),
                _cp(returncode=0, stdout="abc latest\n"),
            ],
        ) as run_mock, patch(
            "anima_mcp.handlers.system_ops._sync_systemd_services",
            return_value=[],
        ), patch(
            "anima_mcp.state_snapshot.create_local_state_snapshot",
            side_effect=RuntimeError("disk full"),
        ), patch(
            "anima_mcp.handlers.system_ops._spawn_delayed_restart"
        ) as restart_mock:
            data = parse_result(await handle_git_pull({"restart": True}))

        assert data["success"] is False
        assert data["restart"] == "not scheduled"
        assert data["update"] == "not attempted"
        assert "disk full" in data["error"]
        run_mock.assert_not_called()
        restart_mock.assert_not_called()


@pytest.mark.asyncio
class TestDeployFromGithubExtended:
    async def test_deploy_from_github_failure_returns_error(self):
        from anima_mcp.handlers.system_ops import handle_deploy_from_github

        with patch(
            "urllib.request.urlretrieve",
            side_effect=RuntimeError("network down"),
        ):
            data = parse_result(await handle_deploy_from_github({"restart": False}))

        assert data["success"] is False
        assert "network down" in data["error"]


class TestGithubArchiveOverlay:
    def test_preserves_compiled_broker_release_while_updating_sources(self, tmp_path):
        from anima_mcp.handlers.system_ops import _overlay_github_archive

        archive_root = tmp_path / "archive"
        repo_root = tmp_path / "repo"

        archived_broker_source = archive_root / "anima_broker" / "lib" / "broker.ex"
        archived_broker_source.parent.mkdir(parents=True)
        archived_broker_source.write_text("new source", encoding="utf-8")

        live_broker_source = repo_root / "anima_broker" / "lib" / "broker.ex"
        live_broker_source.parent.mkdir(parents=True)
        live_broker_source.write_text("old source", encoding="utf-8")
        compiled_release = (
            repo_root
            / "anima_broker"
            / "_build"
            / "prod"
            / "rel"
            / "anima_broker"
            / "bin"
            / "anima_broker"
        )
        compiled_release.parent.mkdir(parents=True)
        compiled_release.write_text("compiled release", encoding="utf-8")

        archived_docs = archive_root / "docs"
        archived_docs.mkdir()
        (archived_docs / "current.md").write_text("current", encoding="utf-8")
        live_docs = repo_root / "docs"
        live_docs.mkdir()
        (live_docs / "stale.md").write_text("stale", encoding="utf-8")

        _overlay_github_archive(archive_root, repo_root)

        assert live_broker_source.read_text(encoding="utf-8") == "new source"
        assert compiled_release.read_text(encoding="utf-8") == "compiled release"
        assert (live_docs / "current.md").read_text(encoding="utf-8") == "current"
        assert not (live_docs / "stale.md").exists()


class TestZipCommitSha:
    def _zip_with_comment(self, tmp_path, comment: bytes):
        import zipfile

        zip_path = tmp_path / "archive.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("anima-mcp-main/README.md", "x")
            z.comment = comment
        return zipfile.ZipFile(zip_path, "r")

    def test_reads_github_archive_comment(self, tmp_path):
        # GitHub codeload zips carry the exact commit SHA as the archive
        # comment — the only place a refs/heads/<branch>.zip names it.
        from anima_mcp.handlers.system_ops import _zip_commit_sha

        sha = "0123456789abcdef0123456789abcdef01234567"
        with self._zip_with_comment(tmp_path, sha.encode()) as z:
            assert _zip_commit_sha(z) == sha

    def test_rejects_missing_or_non_sha_comment(self, tmp_path):
        from anima_mcp.handlers.system_ops import _zip_commit_sha

        with self._zip_with_comment(tmp_path, b"") as z:
            assert _zip_commit_sha(z) is None
        with self._zip_with_comment(tmp_path, b"not a commit sha") as z:
            assert _zip_commit_sha(z) is None


class TestRecordOverlayRef:
    """The zip overlay rewrites files without touching .git; these assert the
    ref of what was actually deployed still gets named somewhere truthful."""

    def test_without_git_records_marker_only(self, tmp_path):
        from anima_mcp.handlers.system_ops import _record_overlay_ref

        sha = "ab" * 20
        output = {}
        with patch("anima_mcp.deploy_marker.record_zip_overlay") as rec, patch(
            "anima_mcp.handlers.system_ops.subprocess.run"
        ) as run_mock:
            _record_overlay_ref(tmp_path, sha, output)

        assert output["deployed_zip_sha"] == sha
        rec.assert_called_once_with(sha)
        run_mock.assert_not_called()

    def test_with_git_mirrors_deploy_sh_step_1b(self, tmp_path):
        from anima_mcp.handlers.system_ops import _record_overlay_ref

        (tmp_path / ".git").mkdir()
        sha = "cd" * 20
        output = {}
        with patch("anima_mcp.deploy_marker.record_zip_overlay") as rec, patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=[_cp(returncode=0), _cp(returncode=0)],
        ) as run_mock:
            _record_overlay_ref(tmp_path, sha, output)

        cmds = [call.args[0] for call in run_mock.call_args_list]
        assert cmds[0][:2] == ["git", "fetch"] and sha in cmds[0]
        assert cmds[1] == ["git", "reset", "--mixed", sha]
        assert "reset --mixed" in output["git_sync"]
        rec.assert_called_once_with(sha)

    def test_git_failure_is_reported_not_raised(self, tmp_path):
        from anima_mcp.handlers.system_ops import _record_overlay_ref

        (tmp_path / ".git").mkdir()
        sha = "ef" * 20
        output = {}
        with patch("anima_mcp.deploy_marker.record_zip_overlay") as rec, patch(
            "anima_mcp.handlers.system_ops.subprocess.run",
            side_effect=[_cp(returncode=0), _cp(returncode=1, stderr="bad object")],
        ):
            _record_overlay_ref(tmp_path, sha, output)

        assert "could not align git" in output["git_sync"]
        assert "bad object" in output["git_sync"]
        rec.assert_called_once_with(sha)  # marker still written

    def test_missing_sha_notes_unaligned_git(self, tmp_path):
        from anima_mcp.handlers.system_ops import _record_overlay_ref

        output = {}
        with patch("anima_mcp.deploy_marker.record_zip_overlay") as rec:
            _record_overlay_ref(tmp_path, None, output)

        assert "no commit SHA" in output["git_sync"]
        rec.assert_called_once_with(None)


@pytest.mark.asyncio
class TestDeployRefRecording:
    async def test_deploy_from_github_extracts_and_records_zip_sha(self):
        from anima_mcp.handlers.system_ops import handle_deploy_from_github

        import zipfile

        sha = "0123456789abcdef0123456789abcdef01234567"

        def fake_retrieve(url, dest):
            with zipfile.ZipFile(dest, "w") as z:
                z.writestr("anima-mcp-main/README.md", "x")
                z.comment = sha.encode()

        with patch("urllib.request.urlretrieve", side_effect=fake_retrieve), patch(
            "anima_mcp.handlers.system_ops._overlay_github_archive"
        ), patch(
            "anima_mcp.handlers.system_ops._sync_systemd_services", return_value=[]
        ), patch(
            "anima_mcp.handlers.system_ops._record_overlay_ref"
        ) as rec:
            data = parse_result(await handle_deploy_from_github({"restart": False}))

        assert data["success"] is True
        rec.assert_called_once()
        assert rec.call_args.args[1] == sha
