"""Tests for signed, externally supervised transient canary evaluation."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import socket
import tempfile
import threading
from datetime import datetime, timedelta

import pytest

from anima_mcp.self_iteration import SelfIterationError, SelfIterationSystem
from anima_mcp.self_iteration_application import sign_application_approval
from anima_mcp.self_iteration_canary import (
    CANARY_SOCKET_ENV,
    CanaryError,
    UnixSocketCanarySupervisor,
    build_canary_request,
    build_signed_canary_result,
    canary_contract,
    canary_profile,
    sign_canary_approval,
    validate_signed_canary_result,
)
from anima_mcp.self_iteration_verification import VerifierKey
from conftest import parse_result
from test_self_iteration_application import (
    _executed_lifecycle,
    _prepare_application,
    application_setup as _application_setup_fixture,
)
from test_self_iteration_execution import _provenance_provider


def _supervisor_identity(signer: VerifierKey) -> dict:
    return {
        "schema": "anima.self_iteration.canary_supervisor.v1",
        "backend": "external_unix_socket_supervisor",
        "protocol_version": 1,
        "supervisor_id": signer.verifier_id,
        "result_signer": {
            "id": signer.verifier_id,
            "key_id": signer.key_id,
            "algorithm": "hmac-sha256",
            "assurance": "symmetric_mac_server_verifiable",
        },
        "profile": canary_profile(),
        "local_transport": "unix_socket",
        "transient_activation_only": True,
        "baseline_restore_required": True,
        "persistent_activation_allowed": False,
        "arbitrary_command_allowed": False,
        "shell_allowed": False,
        "service_control_allowed": False,
        "push_allowed": False,
        "merge_allowed": False,
    }


class FakeCanarySupervisor:
    def __init__(self, signer: VerifierKey) -> None:
        self.signer = signer
        self.identity = _supervisor_identity(signer)
        self.outcome = "passed"
        self.baseline_restored = True
        self.fail_evaluate = False
        self.run_count = 0
        self.seen_request: dict | None = None

    def probe(self) -> dict:
        return copy.deepcopy(self.identity)

    def evaluate(
        self,
        *,
        approval: dict,
        approval_signature: str,
        requested_at: str,
    ) -> dict:
        self.run_count += 1
        if self.fail_evaluate:
            raise CanaryError("simulated external supervisor failure")
        request = build_canary_request(
            approval=approval,
            approval_signature=approval_signature,
            requested_at=requested_at,
        )
        self.seen_request = copy.deepcopy(request)
        started = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
        checks = []
        if self.outcome in {"passed", "failed", "timed_out"}:
            for name in canary_profile()["health_checks"]:
                status = "passed"
                if self.outcome != "passed" and name == "display_heartbeat":
                    status = "failed" if self.outcome == "failed" else "timed_out"
                checks.append(
                    {
                        "name": name,
                        "status": status,
                        "duration_ms": 10,
                        "evidence_sha256": hashlib.sha256(
                            f"{name}:{status}".encode()
                        ).hexdigest(),
                        "summary": f"fixed check {name}: {status}",
                    }
                )
        return build_signed_canary_result(
            request=request,
            supervisor_receipt={
                "started_at": requested_at,
                "finished_at": (started + timedelta(seconds=1))
                .isoformat()
                .replace("+00:00", "Z"),
                "outcome": self.outcome,
                "activation_performed": self.outcome
                not in {"activation_failed", "supervisor_error"},
                "health_checks": checks,
                "baseline_restore_attempted": self.outcome
                not in {"activation_failed", "supervisor_error"},
                "baseline_restored": self.baseline_restored,
                "live_revision_after": (
                    approval["baseline_revision"]
                    if self.baseline_restored
                    else approval["candidate_commit_oid"]
                ),
            },
            signer_key=self.signer,
        )


@pytest.fixture
def canary_setup(tmp_path, monkeypatch):
    setup = _application_setup_fixture.__wrapped__(tmp_path, monkeypatch)
    canary_key = VerifierKey("canary-reviewer", "key-c", b"c" * 32)
    supervisor_key = VerifierKey("canary-supervisor", "key-z", b"z" * 32)
    for key in (canary_key, supervisor_key):
        setup.registry.keys[(key.verifier_id, key.key_id)] = key
        setup.registry.active[key.verifier_id] = key.key_id
    setup.keys["canary"] = canary_key
    setup.keys["canary_supervisor"] = supervisor_key
    monkeypatch.setenv(
        "ANIMA_SELF_ITERATION_CANARY_SUPERVISOR_SIGNER_ID",
        supervisor_key.verifier_id,
    )
    supervisor = FakeCanarySupervisor(supervisor_key)

    def system(actor_id: str | None) -> SelfIterationSystem:
        return SelfIterationSystem(
            repo_root=setup.repo,
            ledger_path=setup.ledger,
            sandbox_root=setup.sandbox_root,
            clock=setup.clock,
            provenance_provider=_provenance_provider(actor_id),
            verifier_key_provider=setup.registry,
            isolation_runner=setup.runner,
            canary_supervisor=supervisor,
        )

    setup.supervisor = supervisor
    setup.canary_reviewer = system("canary-reviewer")
    setup.canary_actors = {
        "proposer": system("proposer-1"),
        "verifier": system("verifier-1"),
        "approver": system("approver-1"),
        "application_reviewer": system("reviewer-1"),
    }
    return setup


def _applied_lifecycle(setup):
    proposal, candidate, evaluation, execution = _executed_lifecycle(setup)
    prepared = _prepare_application(setup, proposal, candidate, execution)
    approval = prepared["approval"]
    application = setup.reviewer.apply_candidate(
        proposal_id=proposal["id"],
        challenge_id=approval["challenge_id"],
        signature=sign_application_approval(approval, setup.keys["reviewer"]),
    )["result"]
    return proposal, candidate, evaluation, execution, application


def _prepare_canary(setup, proposal, candidate, application):
    return setup.canary_reviewer.prepare_canary(
        proposal_id=proposal["id"],
        candidate_id=candidate["candidate_id"],
        application_result_id=application["application_result_id"],
        expected_application_result_sha256=application["result_sha256"],
    )


class TestCanaryProtocol:
    def test_canary_protocol_is_a_protected_self_iteration_surface(self, canary_setup):
        boundary = canary_setup.canary_reviewer.classify_target(
            "src/anima_mcp/self_iteration_canary.py"
        )
        assert boundary["boundary"] == "protected_core"
        assert boundary["risk_floor"] == "high"

    def test_default_supervisor_is_disabled_without_an_exact_unix_socket(
        self, monkeypatch
    ):
        monkeypatch.delenv(CANARY_SOCKET_ENV, raising=False)
        with pytest.raises(CanaryError, match="absolute local Unix socket"):
            UnixSocketCanarySupervisor.from_environment().probe()

    def test_unix_socket_probe_accepts_only_the_fixed_supervisor_identity(self):
        signer = VerifierKey("canary-supervisor", "key-z", b"z" * 32)
        temporary_root = "/private/tmp" if os.path.isdir("/private/tmp") else "/tmp"
        temporary = tempfile.TemporaryDirectory(
            prefix="anima-canary-test-", dir=temporary_root
        )
        socket_path = f"{temporary.name}/canary.sock"
        seen: list[dict] = []
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(socket_path)
        server.listen(1)

        def serve() -> None:
            connection, _address = server.accept()
            with connection:
                payload = bytearray()
                while b"\n" not in payload:
                    payload.extend(connection.recv(65536))
                seen.append(json.loads(bytes(payload).split(b"\n", 1)[0]))
                connection.sendall(
                    json.dumps(
                        {
                            "schema": "anima.self_iteration.canary_probe_response.v1",
                            "ok": True,
                            "identity": _supervisor_identity(signer),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                    + b"\n"
                )
            server.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        identity = UnixSocketCanarySupervisor(socket_path).probe()
        thread.join(timeout=2)
        temporary.cleanup()

        assert identity == _supervisor_identity(signer)
        assert seen == [
            {
                "schema": "anima.self_iteration.canary_request.v1",
                "action": "probe",
                "profile": canary_profile(),
                "persistent_activation_allowed": False,
            }
        ]

    def test_signed_result_requires_restoration_and_never_grants_activation(
        self, canary_setup
    ):
        setup = canary_setup
        proposal, candidate, _evaluation, _execution, application = _applied_lifecycle(
            setup
        )
        prepared = _prepare_canary(setup, proposal, candidate, application)
        approval = prepared["approval"]
        signature = sign_canary_approval(approval, setup.keys["canary"])
        requested_at = approval["issued_at"]
        request = build_canary_request(
            approval=approval,
            approval_signature=signature,
            requested_at=requested_at,
        )
        result = setup.supervisor.evaluate(
            approval=approval,
            approval_signature=signature,
            requested_at=requested_at,
        )

        assert setup.supervisor.seen_request == request
        assert validate_signed_canary_result(result, setup.registry) == result
        assert result["baseline_restored"] is True
        assert result["live_revision_after"] == approval["baseline_revision"]
        assert result["persistent_activation_retained"] is False
        assert result["eligible_for_merge_review"] is True
        assert result["eligible_for_live_activation"] is False
        assert result["authority_granted"] is False

        tampered = copy.deepcopy(result)
        tampered["baseline_restored"] = False
        with pytest.raises(CanaryError):
            validate_signed_canary_result(tampered, setup.registry)


class TestTransientCanaryLifecycle:
    @pytest.mark.asyncio
    async def test_handler_exposes_transient_canary_lifecycle(
        self, canary_setup, monkeypatch
    ):
        setup = canary_setup
        proposal, candidate, _evaluation, _execution, application = _applied_lifecycle(
            setup
        )
        monkeypatch.setattr(
            "anima_mcp.handlers.self_iteration.get_self_iteration_system",
            lambda: setup.canary_reviewer,
        )
        from anima_mcp.handlers.self_iteration import handle_self_iteration

        prepared = parse_result(
            await handle_self_iteration(
                {
                    "action": "prepare_canary",
                    "proposal_id": proposal["id"],
                    "candidate_id": candidate["candidate_id"],
                    "application_result_id": application["application_result_id"],
                    "expected_application_result_sha256": application["result_sha256"],
                }
            )
        )
        approval = prepared["approval"]
        ran = parse_result(
            await handle_self_iteration(
                {
                    "action": "run_canary",
                    "proposal_id": proposal["id"],
                    "challenge_id": approval["challenge_id"],
                    "signature": sign_canary_approval(approval, setup.keys["canary"]),
                }
            )
        )
        status = parse_result(
            await handle_self_iteration(
                {
                    "action": "canary_status",
                    "proposal_id": proposal["id"],
                    "candidate_id": candidate["candidate_id"],
                }
            )
        )

        assert ran["success"] is True
        assert ran["result"]["baseline_restored"] is True
        assert status["canaries"][0]["state"] == "recorded"
        assert status["canaries"][0]["eligible_for_merge_review"] is True
        assert status["eligible_for_live_activation"] is False

    def test_passing_canary_restores_baseline_and_records_recommendation(
        self, canary_setup
    ):
        setup = canary_setup
        proposal, candidate, _evaluation, _execution, application = _applied_lifecycle(
            setup
        )
        prepared = _prepare_canary(setup, proposal, candidate, application)
        approval = prepared["approval"]
        ran = setup.canary_reviewer.run_canary(
            proposal_id=proposal["id"],
            challenge_id=approval["challenge_id"],
            signature=sign_canary_approval(approval, setup.keys["canary"]),
        )
        result = ran["result"]

        assert setup.supervisor.run_count == 1
        assert result["outcome"] == "passed"
        assert result["activation_performed"] is True
        assert result["baseline_restore_attempted"] is True
        assert result["baseline_restored"] is True
        assert result["recommended_decision"] == ("keep_candidate_for_merge_review")
        assert result["persistent_activation_retained"] is False
        status = setup.canary_reviewer.canary_status(
            proposal_id=proposal["id"], candidate_id=candidate["candidate_id"]
        )
        assert status["canaries"][0]["state"] == "recorded"
        assert status["canaries"][0]["application_ref_intact"] is True
        assert status["canaries"][0]["eligible_for_merge_review"] is True

    @pytest.mark.parametrize(
        "actor", ["proposer", "verifier", "approver", "application_reviewer"]
    )
    def test_every_prior_participant_is_refused_as_canary_reviewer(
        self, canary_setup, actor
    ):
        setup = canary_setup
        proposal, candidate, _evaluation, _execution, application = _applied_lifecycle(
            setup
        )
        with pytest.raises(SelfIterationError, match="all prior participants"):
            setup.canary_actors[actor].prepare_canary(
                proposal_id=proposal["id"],
                candidate_id=candidate["candidate_id"],
                application_result_id=application["application_result_id"],
                expected_application_result_sha256=application["result_sha256"],
            )

    def test_failed_health_check_restores_baseline_and_rejects_candidate(
        self, canary_setup
    ):
        setup = canary_setup
        setup.supervisor.outcome = "failed"
        proposal, candidate, _evaluation, _execution, application = _applied_lifecycle(
            setup
        )
        prepared = _prepare_canary(setup, proposal, candidate, application)
        approval = prepared["approval"]
        result = setup.canary_reviewer.run_canary(
            proposal_id=proposal["id"],
            challenge_id=approval["challenge_id"],
            signature=sign_canary_approval(approval, setup.keys["canary"]),
        )["result"]

        assert result["baseline_restored"] is True
        assert result["recommended_decision"] == "reject_candidate"
        assert result["eligible_for_merge_review"] is False

    def test_rollback_failure_requires_operator_recovery(self, canary_setup):
        setup = canary_setup
        setup.supervisor.outcome = "rollback_failed"
        setup.supervisor.baseline_restored = False
        proposal, candidate, _evaluation, _execution, application = _applied_lifecycle(
            setup
        )
        prepared = _prepare_canary(setup, proposal, candidate, application)
        approval = prepared["approval"]
        result = setup.canary_reviewer.run_canary(
            proposal_id=proposal["id"],
            challenge_id=approval["challenge_id"],
            signature=sign_canary_approval(approval, setup.keys["canary"]),
        )["result"]
        status = setup.canary_reviewer.canary_status(
            proposal_id=proposal["id"], candidate_id=candidate["candidate_id"]
        )

        assert result["recommended_decision"] == "operator_recovery_required"
        assert result["eligible_for_merge_review"] is False
        assert status["canaries"][0]["state"] == "recorded_recovery_required"

    def test_failure_after_claim_is_indeterminate_and_never_retried(self, canary_setup):
        setup = canary_setup
        proposal, candidate, _evaluation, _execution, application = _applied_lifecycle(
            setup
        )
        prepared = _prepare_canary(setup, proposal, candidate, application)
        approval = prepared["approval"]
        signature = sign_canary_approval(approval, setup.keys["canary"])
        setup.supervisor.fail_evaluate = True

        with pytest.raises(SelfIterationError, match="simulated"):
            setup.canary_reviewer.run_canary(
                proposal_id=proposal["id"],
                challenge_id=approval["challenge_id"],
                signature=signature,
            )
        status = setup.canary_reviewer.canary_status(
            proposal_id=proposal["id"], candidate_id=candidate["candidate_id"]
        )
        assert status["canaries"][0]["state"] == "claimed_result_indeterminate"
        assert status["canaries"][0]["automatic_retry_allowed"] is False

        setup.supervisor.fail_evaluate = False
        with pytest.raises(SelfIterationError, match="already claimed"):
            setup.canary_reviewer.run_canary(
                proposal_id=proposal["id"],
                challenge_id=approval["challenge_id"],
                signature=signature,
            )
        assert setup.supervisor.run_count == 1

    def test_tampered_signed_result_fails_closed(self, canary_setup):
        setup = canary_setup
        proposal, candidate, _evaluation, _execution, application = _applied_lifecycle(
            setup
        )
        prepared = _prepare_canary(setup, proposal, candidate, application)
        approval = prepared["approval"]
        result = setup.canary_reviewer.run_canary(
            proposal_id=proposal["id"],
            challenge_id=approval["challenge_id"],
            signature=sign_canary_approval(approval, setup.keys["canary"]),
        )["result"]
        result_path = (
            setup.sandbox_root
            / candidate["candidate_id"]
            / "canaries"
            / f"{result['canary_result_id']}.json"
        )
        tampered = json.loads(result_path.read_text())
        tampered["outcome"] = "failed"
        result_path.write_text(json.dumps(tampered))

        with pytest.raises(SelfIterationError, match="signed canary result"):
            setup.canary_reviewer.canary_status(
                proposal_id=proposal["id"], candidate_id=candidate["candidate_id"]
            )

    def test_schema_v6_migrates_to_canary_contract(self, canary_setup):
        setup = canary_setup
        proposal = setup.proposer.propose(
            observation="Canary migration fixture.",
            hypothesis="The migration remains no-authority.",
            expected_outcome="A transient canary contract is added.",
            evidence=["local ledger"],
            target_paths=["src/anima_mcp/display/eras/test_era.py"],
            verification=["inspect migration event"],
            risk="low",
        )
        ledger = json.loads(setup.ledger.read_text())
        ledger["schema_version"] = 6
        ledger.pop("canary_contract")
        setup.ledger.write_text(json.dumps(ledger))

        migrated = setup.canary_reviewer.list_proposals(proposal_id=proposal["id"])[
            "proposals"
        ][0]
        on_disk = json.loads(setup.ledger.read_text())
        assert migrated["events"][-1] == {
            "type": "canary_schema_migrated",
            "at": "2026-08-11T22:30:00Z",
            "from_schema": 6,
            "to_schema": 7,
            "authority_granted": False,
        }
        assert on_disk["schema_version"] == 7
        assert on_disk["canary_contract"] == canary_contract()
