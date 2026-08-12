"""Tests for reviewed, one-use application to a dedicated Git branch."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from anima_mcp.self_iteration import SelfIterationError, SelfIterationSystem
from anima_mcp.self_iteration_application import (
    ApplicationError,
    GitPlumbingApplicationWriter,
    application_approval_sha256,
    application_signing_input_b64,
    build_application_approval,
    build_signed_application_result,
    sign_application_approval,
    target_ref_for_candidate,
    validate_signed_application_result,
)
from anima_mcp.self_iteration_execution import SourceWorkspaceBuilder
from anima_mcp.self_iteration_verification import VerifierKey
from conftest import parse_result
from test_self_iteration_execution import (  # noqa: F401
    _commit_repo,
    _git,
    _prepared_lifecycle,
    _provenance_provider,
    execution_setup as _execution_setup_fixture,
)


@pytest.fixture
def application_setup(tmp_path, monkeypatch):
    return _execution_setup_fixture.__wrapped__(tmp_path, monkeypatch)


def _executed_lifecycle(setup):
    proposal, candidate, evaluation, prepared = _prepared_lifecycle(setup)
    execution_approval = prepared["approval"]
    from anima_mcp.self_iteration_execution import sign_execution_approval

    execution = setup.approver.execute_candidate(
        proposal_id=proposal["id"],
        challenge_id=execution_approval["challenge_id"],
        signature=sign_execution_approval(execution_approval, setup.keys["approver"]),
    )["result"]
    return proposal, candidate, evaluation, execution


def _prepare_application(setup, proposal, candidate, execution):
    return setup.reviewer.prepare_application(
        proposal_id=proposal["id"],
        candidate_id=candidate["candidate_id"],
        execution_id=execution["execution_id"],
        expected_execution_result_sha256=execution["result_sha256"],
    )


class TestApplicationArtifacts:
    def test_git_plumbing_creates_only_dedicated_branch_and_skips_hooks(self, tmp_path):
        repo = tmp_path / "repo"
        target = repo / "src/anima_mcp/display/eras/example.py"
        target.parent.mkdir(parents=True)
        target.write_text("VALUE = 'base'\n")
        revision = _commit_repo(repo)
        replacement = b"VALUE = 'candidate'\n"
        candidate_id = "sip-" + "5" * 32
        manifest = {
            "candidate_id": candidate_id,
            "files": [
                {
                    "path": "src/anima_mcp/display/eras/example.py",
                    "base_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "candidate_sha256": hashlib.sha256(replacement).hexdigest(),
                }
            ],
        }
        contents = {"src/anima_mcp/display/eras/example.py": replacement}
        snapshot = SourceWorkspaceBuilder().fingerprint(
            repo_root=repo,
            expected_revision=revision,
            candidate_manifest=manifest,
            candidate_contents=contents,
        )
        reviewer_key = VerifierKey("reviewer-1", "key-w", b"w" * 32)
        signer_key = VerifierKey("application-signer", "key-s", b"s" * 32)
        registry = {
            (reviewer_key.verifier_id, reviewer_key.key_id): reviewer_key,
            (signer_key.verifier_id, signer_key.key_id): signer_key,
        }
        writer = GitPlumbingApplicationWriter()
        target_ref = target_ref_for_candidate(candidate_id)
        git_identity = writer.probe(
            repo_root=repo,
            expected_parent_revision=revision,
            target_ref=target_ref,
        )
        now = "2026-08-11T22:45:00Z"
        from datetime import datetime

        approval = build_application_approval(
            proposal_id="si-20260811-application",
            proposal_content_sha256="1" * 64,
            source_fingerprint={
                "revision": revision,
                "manifest_sha256": "2" * 64,
            },
            active_attestation_ids=["sia-" + "3" * 32],
            candidate_id=candidate_id,
            candidate_sha256="4" * 64,
            execution_id="six-" + "6" * 32,
            execution_result_sha256="7" * 64,
            execution_approval_sha256="8" * 64,
            execution_finished_at="2026-08-11T22:44:00Z",
            source_snapshot=snapshot,
            reviewer_identity={
                "kind": "oauth_subject",
                "id": "reviewer-1",
                "issuer": "https://issuer.example.test",
            },
            reviewer_key_id=reviewer_key.key_id,
            git_identity=git_identity,
            result_signer_id=signer_key.verifier_id,
            result_signer_key_id=signer_key.key_id,
            issued_at=datetime.fromisoformat(now.replace("Z", "+00:00")),
        )
        signature = sign_application_approval(approval, reviewer_key)
        marker = tmp_path / "hook-ran"
        hook = repo / ".git/hooks/commit-msg"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        hook.chmod(0o755)

        receipt = writer.apply(
            repo_root=repo,
            expected_identity=git_identity,
            approval=approval,
            candidate_manifest=manifest,
            candidate_contents=contents,
            applied_at=now,
        )
        result = build_signed_application_result(
            approval=approval,
            approval_signature=signature,
            approval_key=reviewer_key,
            writer_receipt=receipt,
            applied_at=now,
            signer_key=signer_key,
        )

        def provider(actor, key_id):
            return registry.get((actor, key_id))

        assert validate_signed_application_result(result, provider) == result
        assert writer.verify_result(repo_root=repo, result=result) is True
        assert _git(repo, "rev-parse", "HEAD") == revision
        assert _git(repo, "status", "--porcelain") == ""
        assert _git(
            repo, "show", f"{target_ref}:src/anima_mcp/display/eras/example.py"
        ) == ("VALUE = 'candidate'")
        assert target.read_text() == "VALUE = 'base'\n"
        assert not marker.exists()
        assert result["eligible_for_canary_review"] is True
        assert result["eligible_for_live_activation"] is False
        assert result["pushed"] is False
        assert result["merged"] is False
        assert result["deployed"] is False
        assert (
            application_approval_sha256(approval)
            == result["application_approval_sha256"]
        )
        assert application_signing_input_b64(approval)

        tampered = copy.deepcopy(result)
        tampered["pushed"] = True
        with pytest.raises(ApplicationError):
            validate_signed_application_result(tampered, provider)


class TestReviewedApplicationLifecycle:
    @pytest.mark.asyncio
    async def test_handler_exposes_reviewed_application_lifecycle(
        self, application_setup, monkeypatch
    ):
        setup = application_setup
        proposal, candidate, _evaluation, execution = _executed_lifecycle(setup)
        monkeypatch.setattr(
            "anima_mcp.handlers.self_iteration.get_self_iteration_system",
            lambda: setup.reviewer,
        )
        from anima_mcp.handlers.self_iteration import handle_self_iteration

        prepared = parse_result(
            await handle_self_iteration(
                {
                    "action": "prepare_application",
                    "proposal_id": proposal["id"],
                    "candidate_id": candidate["candidate_id"],
                    "execution_id": execution["execution_id"],
                    "expected_execution_result_sha256": execution["result_sha256"],
                }
            )
        )
        approval = prepared["approval"]
        applied = parse_result(
            await handle_self_iteration(
                {
                    "action": "apply_candidate",
                    "proposal_id": proposal["id"],
                    "challenge_id": approval["challenge_id"],
                    "signature": sign_application_approval(
                        approval, setup.keys["reviewer"]
                    ),
                }
            )
        )
        status = parse_result(
            await handle_self_iteration(
                {
                    "action": "application_status",
                    "proposal_id": proposal["id"],
                    "candidate_id": candidate["candidate_id"],
                }
            )
        )

        assert prepared["success"] is True
        assert applied["success"] is True
        assert status["applications"][0]["state"] == "recorded"
        assert status["applications"][0]["ref_integrity_verified"] is True

    def test_review_creates_branch_without_touching_head_or_worktree(
        self, application_setup
    ):
        setup = application_setup
        before_head = _git(setup.repo, "rev-parse", "HEAD")
        before = {
            path.relative_to(setup.repo).as_posix(): path.read_bytes()
            for path in setup.repo.rglob("*")
            if path.is_file() and ".git" not in path.parts
        }
        proposal, candidate, _evaluation, execution = _executed_lifecycle(setup)
        prepared = _prepare_application(setup, proposal, candidate, execution)
        approval = prepared["approval"]
        applied = setup.reviewer.apply_candidate(
            proposal_id=proposal["id"],
            challenge_id=approval["challenge_id"],
            signature=sign_application_approval(approval, setup.keys["reviewer"]),
        )
        result = applied["result"]
        after = {
            path.relative_to(setup.repo).as_posix(): path.read_bytes()
            for path in setup.repo.rglob("*")
            if path.is_file() and ".git" not in path.parts
        }

        assert before == after
        assert _git(setup.repo, "rev-parse", "HEAD") == before_head
        assert (
            _git(setup.repo, "rev-parse", result["target_ref"]) == result["commit_oid"]
        )
        assert result["branch_created"] is True
        assert result["live_source_writes"] is False
        assert result["pushed"] is False
        assert result["merged"] is False
        assert result["deployed"] is False
        assert validate_signed_application_result(result, setup.registry) == result
        status = setup.reviewer.application_status(
            proposal_id=proposal["id"], candidate_id=candidate["candidate_id"]
        )
        assert status["applications"][0]["state"] == "recorded"
        assert status["applications"][0]["eligible_for_canary_review"] is True

        with pytest.raises(SelfIterationError, match="already exists|already claimed"):
            setup.reviewer.apply_candidate(
                proposal_id=proposal["id"],
                challenge_id=approval["challenge_id"],
                signature=sign_application_approval(approval, setup.keys["reviewer"]),
            )

    @pytest.mark.parametrize("actor", ["proposer", "verifier", "approver"])
    def test_all_prior_human_participants_are_refused_as_reviewer(
        self, application_setup, actor
    ):
        setup = application_setup
        proposal, candidate, _evaluation, execution = _executed_lifecycle(setup)
        with pytest.raises(SelfIterationError, match="all prior participants"):
            getattr(setup, actor).prepare_application(
                proposal_id=proposal["id"],
                candidate_id=candidate["candidate_id"],
                execution_id=execution["execution_id"],
                expected_execution_result_sha256=execution["result_sha256"],
            )

    def test_failure_after_claim_is_indeterminate_and_never_retried(
        self, application_setup
    ):
        setup = application_setup
        proposal, candidate, _evaluation, execution = _executed_lifecycle(setup)

        class FailingWriter:
            def __init__(self) -> None:
                self.delegate = GitPlumbingApplicationWriter()
                self.apply_count = 0

            def probe(self, **kwargs):
                return self.delegate.probe(**kwargs)

            def apply(self, **_kwargs):
                self.apply_count += 1
                raise ApplicationError("simulated Git writer failure")

            def verify_result(self, **_kwargs):
                return False

        writer = FailingWriter()
        reviewer = SelfIterationSystem(
            repo_root=setup.repo,
            ledger_path=setup.ledger,
            sandbox_root=setup.sandbox_root,
            clock=setup.clock,
            provenance_provider=_provenance_provider("reviewer-1"),
            verifier_key_provider=setup.registry,
            isolation_runner=setup.runner,
            application_writer=writer,
        )
        prepared = reviewer.prepare_application(
            proposal_id=proposal["id"],
            candidate_id=candidate["candidate_id"],
            execution_id=execution["execution_id"],
            expected_execution_result_sha256=execution["result_sha256"],
        )
        approval = prepared["approval"]
        signature = sign_application_approval(approval, setup.keys["reviewer"])

        with pytest.raises(SelfIterationError, match="simulated"):
            reviewer.apply_candidate(
                proposal_id=proposal["id"],
                challenge_id=approval["challenge_id"],
                signature=signature,
            )
        status = reviewer.application_status(
            proposal_id=proposal["id"], candidate_id=candidate["candidate_id"]
        )
        assert status["applications"][0]["state"] == ("claimed_result_indeterminate")
        assert status["applications"][0]["automatic_retry_allowed"] is False

        with pytest.raises(SelfIterationError, match="already claimed"):
            reviewer.apply_candidate(
                proposal_id=proposal["id"],
                challenge_id=approval["challenge_id"],
                signature=signature,
            )
        assert writer.apply_count == 1

    def test_tampered_signed_application_result_fails_closed(self, application_setup):
        setup = application_setup
        proposal, candidate, _evaluation, execution = _executed_lifecycle(setup)
        prepared = _prepare_application(setup, proposal, candidate, execution)
        approval = prepared["approval"]
        applied = setup.reviewer.apply_candidate(
            proposal_id=proposal["id"],
            challenge_id=approval["challenge_id"],
            signature=sign_application_approval(approval, setup.keys["reviewer"]),
        )["result"]
        result_path = (
            setup.sandbox_root
            / candidate["candidate_id"]
            / "applications"
            / f"{applied['application_result_id']}.json"
        )
        tampered = json.loads(result_path.read_text())
        tampered["commit_oid"] = "0" * len(tampered["commit_oid"])
        result_path.write_text(json.dumps(tampered))

        with pytest.raises(SelfIterationError, match="signed application result"):
            setup.reviewer.application_status(
                proposal_id=proposal["id"], candidate_id=candidate["candidate_id"]
            )
