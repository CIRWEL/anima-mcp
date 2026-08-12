"""Tests for quarantined patch artifacts and non-executing evaluation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from anima_mcp.self_iteration import (
    PROVENANCE_SCHEMA,
    SelfIterationError,
    SelfIterationSystem,
)
from anima_mcp.self_iteration_sandbox import sandbox_contract
from anima_mcp.self_iteration_verification import VerifierKey, sign_attestation
from conftest import parse_result


@dataclass
class MutableClock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


class KeyRegistry:
    def __init__(self, *keys: VerifierKey) -> None:
        self.keys = {(key.verifier_id, key.key_id): key for key in keys}
        self.active = {key.verifier_id: key.key_id for key in keys}

    def __call__(
        self, verifier_id: str, requested_key_id: str | None
    ) -> VerifierKey | None:
        key_id = requested_key_id or self.active.get(verifier_id)
        return self.keys.get((verifier_id, key_id))


def _provenance_provider(actor_id: str | None):
    def provider(recorded_at: str) -> dict:
        authenticated = actor_id is not None
        return {
            "schema": PROVENANCE_SCHEMA,
            "recorded_by": "anima-mcp-sandbox-test",
            "recorded_at": recorded_at,
            "transport": {"kind": "test", "server_observed": True},
            "authentication": {
                "method": "oauth_bearer" if authenticated else "none",
                "verified": authenticated,
            },
            "actor": (
                {
                    "kind": "oauth_subject",
                    "id": actor_id,
                    "issuer": "https://issuer.example.test",
                    "verified": True,
                }
                if authenticated
                else None
            ),
            "session": {"present": False, "verified": False},
            "trust": {},
        }

    return provider


def _proposal_args(**overrides):
    values = {
        "observation": "The display repeats a converged mark.",
        "hypothesis": "A bounded seed change will reduce repeated marks.",
        "expected_outcome": "Duplicate rate falls below ten percent.",
        "evidence": ["8 of 20 recent drawings repeated the mark"],
        "target_paths": ["src/anima_mcp/display/eras/test_era.py"],
        "verification": ["Measure twenty canary drawings"],
        "risk": "low",
    }
    values.update(overrides)
    return values


@pytest.fixture
def sandbox_setup(tmp_path):
    repo = tmp_path / "anima-mcp"
    files = {
        "pyproject.toml": '[project]\nname = "anima-mcp"\nversion = "9.9.9"\n',
        "README.md": "# Test creature\n",
        "src/anima_mcp/display/eras/test_era.py": ("def draw():\n    return None\n"),
        "src/anima_mcp/sample.py": "def sample():\n    return True\n",
        "docs/guide.md": "# Guide\n",
        "docs/settings.json": '{"enabled": true}\n',
        "docs/settings.yaml": "enabled: true\n",
    }
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    clock = MutableClock(datetime(2026, 8, 11, 21, 30, tzinfo=timezone.utc))
    proposer_key = VerifierKey("proposer-1", "key-p", b"p" * 32)
    verifier_key = VerifierKey("verifier-1", "key-v", b"v" * 32)
    other_key = VerifierKey("verifier-2", "key-o", b"o" * 32)
    registry = KeyRegistry(proposer_key, verifier_key, other_key)
    ledger = tmp_path / "state" / "self_iteration.json"
    sandbox_root = tmp_path / "quarantine"

    def system(
        actor_id: str | None, *, root: Path | None = None
    ) -> SelfIterationSystem:
        return SelfIterationSystem(
            repo_root=repo,
            ledger_path=ledger,
            sandbox_root=root or sandbox_root,
            clock=clock,
            provenance_provider=_provenance_provider(actor_id),
            verifier_key_provider=registry,
        )

    return SimpleNamespace(
        repo=repo,
        ledger=ledger,
        sandbox_root=sandbox_root,
        clock=clock,
        registry=registry,
        proposer_key=proposer_key,
        verifier_key=verifier_key,
        other_key=other_key,
        proposer=system("proposer-1"),
        verifier=system("verifier-1"),
        other=system("verifier-2"),
        unauthenticated=system(None),
        system=system,
    )


def _record_verdict(
    setup,
    proposal: dict,
    *,
    decision: str = "verified",
    system: SelfIterationSystem | None = None,
    key: VerifierKey | None = None,
    expires_at: str | None = None,
) -> dict:
    verifier = system or setup.verifier
    signing_key = key or setup.verifier_key
    challenge = verifier.prepare_verification(
        proposal_id=proposal["id"],
        verification_decision=decision,
        verification_statement=f"Independent result: {decision}.",
        verification_evidence=[
            {
                "kind": "canary",
                "uri": f"artifact://canary/{proposal['id']}.json",
                "sha256": "a" * 64,
            }
        ],
        expected_content_sha256=proposal["content_sha256"],
        expires_at=expires_at,
    )
    return verifier.record_verification(
        proposal_id=proposal["id"],
        challenge_id=challenge["challenge_id"],
        signature=sign_attestation(challenge["attestation"], signing_key),
    )


def _verified_proposal(setup, **overrides) -> dict:
    proposal = setup.proposer.propose(**_proposal_args(**overrides))
    return _record_verdict(setup, proposal)


def _change(setup, content: str, path: str | None = None) -> dict:
    relative = path or "src/anima_mcp/display/eras/test_era.py"
    current = (setup.repo / relative).read_bytes()
    return {
        "path": relative,
        "expected_sha256": hashlib.sha256(current).hexdigest(),
        "content": content,
    }


def _construct(setup, proposal: dict, content: str, path: str | None = None) -> dict:
    return setup.proposer.construct_patch(
        proposal_id=proposal["id"],
        expected_content_sha256=proposal["content_sha256"],
        changes=[_change(setup, content, path)],
    )["candidate"]


def _repo_snapshot(repo: Path) -> dict[str, bytes]:
    return {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in repo.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


class TestQuarantinedPatchLifecycle:
    def test_construct_and_evaluate_never_touch_live_source(self, sandbox_setup):
        setup = sandbox_setup
        proposal = _verified_proposal(setup)
        before = _repo_snapshot(setup.repo)

        candidate = _construct(
            setup,
            proposal,
            "def draw():\n    return 'varied'\n",
        )
        candidate_dir = setup.sandbox_root / candidate["candidate_id"]

        assert candidate_dir.is_dir()
        assert setup.repo not in candidate_dir.parents
        assert candidate["proposal_binding"]["proposal_id"] == proposal["id"]
        assert candidate["author_identity"]["id"] == "proposer-1"
        assert candidate["construction_policy"]["candidate_code_executed"] is False
        assert candidate["construction_policy"]["tests_executed"] is False
        assert candidate["authority_granted"] is False
        assert _repo_snapshot(setup.repo) == before

        result = setup.verifier.evaluate_patch(
            proposal_id=proposal["id"],
            candidate_id=candidate["candidate_id"],
            expected_candidate_sha256=candidate["candidate_sha256"],
        )
        evaluation = result["evaluation"]

        assert evaluation["status"] == "static_checks_passed"
        assert evaluation["eligible_for_external_review"] is True
        assert evaluation["eligible_for_execution"] is False
        assert evaluation["execution_performed"] is False
        assert evaluation["tests_executed"] is False
        assert evaluation["authority_granted"] is False
        assert _repo_snapshot(setup.repo) == before

        status = setup.proposer.patch_status(
            proposal_id=proposal["id"],
            candidate_id=candidate["candidate_id"],
            include_patch=True,
        )
        assert status["patch_included"] is True
        assert "return 'varied'" in status["patch"]
        assert status["evaluations"][0]["evaluation_id"] == evaluation["evaluation_id"]
        assert status["unledgered_evaluation_artifact_count"] == 0
        assert status["current_state"]["eligible_for_new_static_evaluation"] is True
        assert status["current_state"]["eligible_for_execution"] is False
        assert (
            setup.unauthenticated.patch_status(
                proposal_id=proposal["id"],
                candidate_id=candidate["candidate_id"],
            )["patch_included"]
            is False
        )
        with pytest.raises(SelfIterationError, match="authenticated actor"):
            setup.unauthenticated.patch_status(
                proposal_id=proposal["id"],
                candidate_id=candidate["candidate_id"],
                include_patch=True,
            )

        ledger = json.loads(setup.ledger.read_text())
        events = ledger["proposals"][0]["events"]
        construction = next(
            event for event in events if event["type"] == "patch_candidate_constructed"
        )
        recorded_evaluation = next(
            event for event in events if event["type"] == "patch_candidate_evaluated"
        )
        assert construction["live_source_writes"] is False
        assert construction["execution_performed"] is False
        assert recorded_evaluation["eligible_for_execution"] is False
        assert recorded_evaluation["requester_identity"]["id"] == "verifier-1"
        assert recorded_evaluation["authority_granted"] is False

    def test_static_python_rejections_are_recorded_without_execution(
        self, sandbox_setup
    ):
        setup = sandbox_setup
        proposal = _verified_proposal(setup)
        syntax_candidate = _construct(setup, proposal, "def draw(:\n    pass\n")
        syntax_result = setup.proposer.evaluate_patch(
            proposal_id=proposal["id"],
            candidate_id=syntax_candidate["candidate_id"],
            expected_candidate_sha256=syntax_candidate["candidate_sha256"],
        )["evaluation"]

        assert syntax_result["status"] == "rejected"
        syntax_checks = syntax_result["files"][0]["checks"]
        assert (
            next(
                check for check in syntax_checks if check["name"] == "python_ast_parse"
            )["findings"][0]["kind"]
            == "syntax_error"
        )

        capability_candidate = _construct(
            setup,
            proposal,
            "import subprocess\n\ndef draw():\n    return open('/tmp/x', 'w')\n",
        )
        capability_result = setup.verifier.evaluate_patch(
            proposal_id=proposal["id"],
            candidate_id=capability_candidate["candidate_id"],
            expected_candidate_sha256=capability_candidate["candidate_sha256"],
        )["evaluation"]
        capability_check = next(
            check
            for check in capability_result["files"][0]["checks"]
            if check["name"] == "python_capability_heuristic"
        )

        assert capability_result["status"] == "rejected"
        assert {item["kind"] for item in capability_check["findings"]} == {
            "forbidden_call",
            "forbidden_import",
        }
        assert capability_result["execution_performed"] is False
        assert capability_result["eligible_for_execution"] is False

    def test_json_yaml_and_markdown_receive_only_static_parsing(self, sandbox_setup):
        setup = sandbox_setup
        proposal = _verified_proposal(
            setup,
            target_paths=[
                "docs/settings.json",
                "docs/settings.yaml",
                "docs/guide.md",
            ],
        )
        changes = [
            _change(setup, '{"enabled": false}\n', "docs/settings.json"),
            _change(setup, "enabled: false\n", "docs/settings.yaml"),
            _change(setup, "# Revised guide\n", "docs/guide.md"),
        ]
        candidate = setup.proposer.construct_patch(
            proposal_id=proposal["id"],
            expected_content_sha256=proposal["content_sha256"],
            changes=changes,
        )["candidate"]
        evaluation = setup.verifier.evaluate_patch(
            proposal_id=proposal["id"],
            candidate_id=candidate["candidate_id"],
            expected_candidate_sha256=candidate["candidate_sha256"],
        )["evaluation"]

        assert evaluation["status"] == "static_checks_passed"
        assert {
            check["name"]
            for file_result in evaluation["files"]
            for check in file_result["checks"]
        } >= {"json_parse", "yaml_safe_load", "markdown_utf8_validation"}
        assert evaluation["tests_executed"] is False


class TestPatchGatesAndIntegrity:
    def test_current_verified_attestation_is_required(self, sandbox_setup):
        setup = sandbox_setup
        unverified = setup.proposer.propose(**_proposal_args())
        with pytest.raises(SelfIterationError, match="verified attestation"):
            _construct(setup, unverified, "def draw():\n    return 1\n")

        rejected = setup.proposer.propose(
            **_proposal_args(observation="A separately rejected observation.")
        )
        _record_verdict(setup, rejected, decision="rejected")
        with pytest.raises(SelfIterationError, match="verified attestation"):
            _construct(setup, rejected, "def draw():\n    return 2\n")

        expiring = setup.proposer.propose(
            **_proposal_args(observation="A separately expiring observation.")
        )
        _record_verdict(
            setup,
            expiring,
            expires_at=(setup.clock.value + timedelta(hours=1)).isoformat(),
        )
        setup.clock.advance(hours=2)
        with pytest.raises(SelfIterationError, match="verified attestation"):
            _construct(setup, expiring, "def draw():\n    return 3\n")

        assert not setup.sandbox_root.exists()

    def test_only_authenticated_proposer_can_construct(self, sandbox_setup):
        setup = sandbox_setup
        proposal = _verified_proposal(setup)
        changes = [_change(setup, "def draw():\n    return 1\n")]

        with pytest.raises(SelfIterationError, match="proposal author"):
            setup.other.construct_patch(
                proposal_id=proposal["id"],
                expected_content_sha256=proposal["content_sha256"],
                changes=changes,
            )
        with pytest.raises(SelfIterationError, match="authenticated actor"):
            setup.unauthenticated.construct_patch(
                proposal_id=proposal["id"],
                expected_content_sha256=proposal["content_sha256"],
                changes=changes,
            )

    def test_non_target_missing_and_review_surfaces_are_refused(self, sandbox_setup):
        setup = sandbox_setup
        proposal = _verified_proposal(setup)
        with pytest.raises(SelfIterationError, match="not bound"):
            setup.proposer.construct_patch(
                proposal_id=proposal["id"],
                expected_content_sha256=proposal["content_sha256"],
                changes=[_change(setup, "# Changed\n", "README.md")],
            )

        review_proposal = setup.proposer.propose(
            **_proposal_args(target_paths=["src/anima_mcp/sample.py"])
        )
        _record_verdict(setup, review_proposal)
        with pytest.raises(SelfIterationError, match="only low-risk proposals"):
            setup.proposer.construct_patch(
                proposal_id=review_proposal["id"],
                expected_content_sha256=review_proposal["content_sha256"],
                changes=[
                    _change(
                        setup,
                        "def sample():\n    return False\n",
                        "src/anima_mcp/sample.py",
                    )
                ],
            )

        missing = _verified_proposal(
            setup,
            observation="A missing documentation page was proposed.",
            target_paths=["docs/missing.md"],
        )
        with pytest.raises(SelfIterationError, match="existing repository file"):
            setup.proposer.construct_patch(
                proposal_id=missing["id"],
                expected_content_sha256=missing["content_sha256"],
                changes=[
                    {
                        "path": "docs/missing.md",
                        "expected_sha256": "0" * 64,
                        "content": "# New file\n",
                    }
                ],
            )

    def test_stale_source_and_wrong_base_digest_fail_closed(self, sandbox_setup):
        setup = sandbox_setup
        proposal = _verified_proposal(setup)
        (setup.repo / "README.md").write_text("# Source changed\n")

        with pytest.raises(SelfIterationError, match="source no longer matches"):
            _construct(setup, proposal, "def draw():\n    return 1\n")

        (setup.repo / "README.md").write_text("# Test creature\n")
        with pytest.raises(SelfIterationError, match="base digest changed"):
            setup.proposer.construct_patch(
                proposal_id=proposal["id"],
                expected_content_sha256=proposal["content_sha256"],
                changes=[
                    {
                        "path": "src/anima_mcp/display/eras/test_era.py",
                        "expected_sha256": "0" * 64,
                        "content": "def draw():\n    return 1\n",
                    }
                ],
            )

    @pytest.mark.parametrize("artifact_name", ["workspace", "patch"])
    def test_tampered_artifact_is_never_evaluated(self, sandbox_setup, artifact_name):
        setup = sandbox_setup
        proposal = _verified_proposal(setup)
        candidate = _construct(setup, proposal, "def draw():\n    return 1\n")
        directory = setup.sandbox_root / candidate["candidate_id"]
        if artifact_name == "workspace":
            target = directory / "workspace/src/anima_mcp/display/eras/test_era.py"
            target.write_text("def draw():\n    return 'tampered'\n")
        else:
            (directory / "candidate.patch").write_text("tampered patch\n")

        with pytest.raises(SelfIterationError, match="digest"):
            setup.verifier.evaluate_patch(
                proposal_id=proposal["id"],
                candidate_id=candidate["candidate_id"],
                expected_candidate_sha256=candidate["candidate_sha256"],
            )
        ledger = json.loads(setup.ledger.read_text())
        assert not any(
            event["type"] == "patch_candidate_evaluated"
            for event in ledger["proposals"][0]["events"]
        )

    def test_new_attestation_makes_existing_candidate_binding_stale(
        self, sandbox_setup
    ):
        setup = sandbox_setup
        proposal = _verified_proposal(setup)
        candidate = _construct(setup, proposal, "def draw():\n    return 1\n")
        _record_verdict(
            setup,
            proposal,
            system=setup.other,
            key=setup.other_key,
        )

        with pytest.raises(SelfIterationError, match="verification binding is stale"):
            setup.verifier.evaluate_patch(
                proposal_id=proposal["id"],
                candidate_id=candidate["candidate_id"],
                expected_candidate_sha256=candidate["candidate_sha256"],
            )

    def test_sandbox_root_inside_repository_is_refused(self, sandbox_setup):
        setup = sandbox_setup
        inside = setup.system("proposer-1", root=setup.repo / ".candidate-artifacts")
        proposal = _verified_proposal(setup)

        with pytest.raises(SelfIterationError, match="outside the source repository"):
            inside.construct_patch(
                proposal_id=proposal["id"],
                expected_content_sha256=proposal["content_sha256"],
                changes=[_change(setup, "def draw():\n    return 1\n")],
            )
        assert not (setup.repo / ".candidate-artifacts").exists()

    def test_schema_v3_migrates_to_static_sandbox_contract(self, sandbox_setup):
        setup = sandbox_setup
        proposal = setup.proposer.propose(**_proposal_args())
        ledger = json.loads(setup.ledger.read_text())
        ledger["schema_version"] = 3
        ledger.pop("sandbox_contract")
        setup.ledger.write_text(json.dumps(ledger))

        migrated = setup.proposer.list_proposals(proposal_id=proposal["id"])[
            "proposals"
        ][0]
        on_disk = json.loads(setup.ledger.read_text())

        assert migrated["events"][-4]["type"] == "sandbox_schema_migrated"
        assert migrated["events"][-4]["authority_granted"] is False
        assert migrated["events"][-3]["type"] == "execution_schema_migrated"
        assert migrated["events"][-3]["authority_granted"] is False
        assert migrated["events"][-2]["type"] == "application_schema_migrated"
        assert migrated["events"][-2]["authority_granted"] is False
        assert migrated["events"][-1]["type"] == "canary_schema_migrated"
        assert migrated["events"][-1]["authority_granted"] is False
        assert on_disk["schema_version"] == 7
        assert on_disk["sandbox_contract"] == sandbox_contract()
        assert on_disk["migrations"][-4]["classification"] == (
            "quarantined_patch_static_evaluation_only"
        )
        assert on_disk["migrations"][-3]["classification"] == (
            "externally_approved_isolated_execution_only"
        )
        assert on_disk["migrations"][-2]["classification"] == (
            "reviewed_dedicated_branch_application_only"
        )
        assert on_disk["migrations"][-1]["classification"] == (
            "signed_transient_canary_with_mandatory_restore"
        )

    def test_ledger_cannot_flip_patch_authority_bits(self, sandbox_setup):
        setup = sandbox_setup
        proposal = _verified_proposal(setup)
        _construct(setup, proposal, "def draw():\n    return 1\n")
        ledger = json.loads(setup.ledger.read_text())
        construction = next(
            event
            for event in ledger["proposals"][0]["events"]
            if event["type"] == "patch_candidate_constructed"
        )
        construction["execution_performed"] = True
        setup.ledger.write_text(json.dumps(ledger))
        tampered = setup.ledger.read_text()

        with pytest.raises(SelfIterationError, match="violates its boundary"):
            setup.proposer.patch_status(
                proposal_id=proposal["id"],
                candidate_id=construction["candidate_id"],
            )
        assert setup.ledger.read_text() == tampered

    def test_patch_author_is_derived_from_authenticated_provenance(self, sandbox_setup):
        setup = sandbox_setup
        proposal = _verified_proposal(setup)
        candidate = _construct(setup, proposal, "def draw():\n    return 1\n")
        ledger = json.loads(setup.ledger.read_text())
        construction = next(
            event
            for event in ledger["proposals"][0]["events"]
            if event["type"] == "patch_candidate_constructed"
        )
        construction["provenance"]["actor"]["id"] = "spoofed-author"
        setup.ledger.write_text(json.dumps(ledger))
        tampered = setup.ledger.read_text()

        with pytest.raises(SelfIterationError, match="not bound to request provenance"):
            setup.proposer.patch_status(
                proposal_id=proposal["id"],
                candidate_id=candidate["candidate_id"],
            )
        assert setup.ledger.read_text() == tampered


@pytest.mark.asyncio
async def test_handler_exposes_quarantine_actions_without_execution(
    sandbox_setup, monkeypatch
):
    setup = sandbox_setup
    proposal = _verified_proposal(setup)
    monkeypatch.setattr(
        "anima_mcp.handlers.self_iteration.get_self_iteration_system",
        lambda: setup.proposer,
    )
    from anima_mcp.handlers.self_iteration import handle_self_iteration

    constructed = parse_result(
        await handle_self_iteration(
            {
                "action": "construct_patch",
                "proposal_id": proposal["id"],
                "expected_content_sha256": proposal["content_sha256"],
                "changes": [_change(setup, "def draw():\n    return 1\n")],
            }
        )
    )
    candidate = constructed["candidate"]
    evaluated = parse_result(
        await handle_self_iteration(
            {
                "action": "evaluate_patch",
                "proposal_id": proposal["id"],
                "candidate_id": candidate["candidate_id"],
                "expected_candidate_sha256": candidate["candidate_sha256"],
            }
        )
    )
    status = parse_result(
        await handle_self_iteration(
            {
                "action": "patch_status",
                "proposal_id": proposal["id"],
                "candidate_id": candidate["candidate_id"],
            }
        )
    )

    assert constructed["success"] is True
    assert evaluated["success"] is True
    assert evaluated["evaluation"]["execution_performed"] is False
    assert status["patch_included"] is False
    assert status["current_state"]["eligible_for_execution"] is False
