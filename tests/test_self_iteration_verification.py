"""Tests for independent signed self-iteration verification."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from anima_mcp.self_iteration import (
    PROVENANCE_SCHEMA,
    SelfIterationError,
    SelfIterationSystem,
)
from anima_mcp.self_iteration_verification import (
    VERIFIER_KEYS_ENV,
    VerificationError,
    VerifierKey,
    canonical_json_bytes,
    proposal_content_sha256,
    sign_attestation,
    verifier_key_from_env,
)
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
            "recorded_by": "anima-mcp-verification-test",
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


def _verification_args(proposal: dict, **overrides):
    values = {
        "proposal_id": proposal["id"],
        "verification_decision": "verified",
        "verification_statement": "The independent canary met the declared threshold.",
        "verification_evidence": [
            {
                "kind": "canary",
                "uri": "artifact://canary/display-20.json",
                "sha256": "a" * 64,
            }
        ],
        "expected_content_sha256": proposal["content_sha256"],
    }
    values.update(overrides)
    return values


@pytest.fixture
def verification_setup(tmp_path):
    repo = tmp_path / "anima-mcp"
    files = {
        "pyproject.toml": '[project]\nname = "anima-mcp"\nversion = "9.9.9"\n',
        "src/anima_mcp/display/eras/test_era.py": "def draw():\n    return None\n",
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

    def system(actor_id: str | None) -> SelfIterationSystem:
        return SelfIterationSystem(
            repo_root=repo,
            ledger_path=ledger,
            clock=clock,
            provenance_provider=_provenance_provider(actor_id),
            verifier_key_provider=registry,
        )

    return SimpleNamespace(
        clock=clock,
        registry=registry,
        proposer_key=proposer_key,
        verifier_key=verifier_key,
        other_key=other_key,
        proposer=system("proposer-1"),
        verifier=system("verifier-1"),
        other=system("verifier-2"),
        unauthenticated=system(None),
        ledger=ledger,
    )


def _sign_and_record(setup, proposal, challenge, *, system=None, key=None):
    system = system or setup.verifier
    key = key or setup.verifier_key
    signature = sign_attestation(challenge["attestation"], key)
    return system.record_verification(
        proposal_id=proposal["id"],
        challenge_id=challenge["challenge_id"],
        signature=signature,
    )


class TestSignedVerification:
    def test_verification_evaluator_is_a_protected_surface(self, verification_setup):
        boundary = verification_setup.proposer.classify_target(
            "src/anima_mcp/self_iteration_verification.py"
        )
        assert boundary["boundary"] == "protected_core"
        assert boundary["risk_floor"] == "high"

    def test_schema_v2_migration_binds_authenticated_proposer_identity(
        self, verification_setup
    ):
        setup = verification_setup
        proposal = setup.proposer.propose(**_proposal_args())
        ledger = json.loads(setup.ledger.read_text())
        ledger["schema_version"] = 2
        ledger.pop("verification_contract")
        ledger_proposal = ledger["proposals"][0]
        ledger_proposal.pop("proposer_identity")
        ledger_proposal.pop("content_sha256")
        setup.ledger.write_text(json.dumps(ledger))

        migrated = setup.verifier.list_proposals(proposal_id=proposal["id"])[
            "proposals"
        ][0]
        on_disk = json.loads(setup.ledger.read_text())

        assert migrated["proposer_identity"]["id"] == "proposer-1"
        assert len(migrated["content_sha256"]) == 64
        assert migrated["events"][-2]["type"] == "verification_schema_migrated"
        assert migrated["events"][-1]["type"] == "sandbox_schema_migrated"
        assert on_disk["schema_version"] == 4

    def test_valid_independent_attestation_enables_priority_only(
        self, verification_setup
    ):
        setup = verification_setup
        proposal = setup.proposer.propose(**_proposal_args())
        challenge = setup.verifier.prepare_verification(**_verification_args(proposal))

        assert challenge["attestation"]["proposer_identity"]["id"] == "proposer-1"
        assert challenge["attestation"]["verifier_identity"]["id"] == "verifier-1"
        assert (
            challenge["attestation"]["proposal_content_sha256"]
            == proposal["content_sha256"]
        )
        assert base64.urlsafe_b64decode(challenge["signing_input_b64"]) == (
            canonical_json_bytes(challenge["attestation"])
        )

        updated = _sign_and_record(setup, proposal, challenge)
        state = updated["verification_state"]

        assert state["status"] == "verified"
        assert state["effective_weight"] == 1.0
        assert state["priority_eligible"] is True
        assert state["automation_eligible"] is False
        assert state["authority_eligible"] is False
        assert updated["trust_policy"]["effective_weight"] == 0.0
        assert updated["events"][-1]["authority_granted"] is False
        assert (
            setup.verifier.verification_status(proposal_id=proposal["id"])[
                "verification_state"
            ]["status"]
            == "verified"
        )

        on_disk = setup.ledger.read_text()
        encoded_secret = base64.urlsafe_b64encode(setup.verifier_key.secret).decode()
        assert encoded_secret not in json.dumps(challenge)
        assert encoded_secret not in on_disk
        assert "verification_state" not in on_disk

    def test_self_verification_and_unauthenticated_actors_are_refused(
        self, verification_setup, tmp_path
    ):
        setup = verification_setup
        proposal = setup.proposer.propose(**_proposal_args())

        with pytest.raises(SelfIterationError, match="may not verify its own"):
            setup.proposer.prepare_verification(**_verification_args(proposal))
        with pytest.raises(SelfIterationError, match="lacks authenticated actor"):
            setup.unauthenticated.prepare_verification(**_verification_args(proposal))

        unauthenticated_ledger = tmp_path / "unauthenticated.json"
        unauthenticated_proposer = SelfIterationSystem(
            repo_root=setup.proposer.repo_root,
            ledger_path=unauthenticated_ledger,
            clock=setup.clock,
            provenance_provider=_provenance_provider(None),
            verifier_key_provider=setup.registry,
        )
        verifier = SelfIterationSystem(
            repo_root=setup.proposer.repo_root,
            ledger_path=unauthenticated_ledger,
            clock=setup.clock,
            provenance_provider=_provenance_provider("verifier-1"),
            verifier_key_provider=setup.registry,
        )
        unauthenticated_proposal = unauthenticated_proposer.propose(**_proposal_args())
        with pytest.raises(SelfIterationError, match="lacks authenticated actor"):
            verifier.prepare_verification(
                **_verification_args(unauthenticated_proposal)
            )

    def test_bad_signature_does_not_consume_challenge_but_replay_is_refused(
        self, verification_setup
    ):
        setup = verification_setup
        proposal = setup.proposer.propose(**_proposal_args())
        challenge = setup.verifier.prepare_verification(**_verification_args(proposal))

        with pytest.raises(SelfIterationError, match="signature is invalid"):
            setup.verifier.record_verification(
                proposal_id=proposal["id"],
                challenge_id=challenge["challenge_id"],
                signature="0" * 64,
            )
        assert [
            event
            for event in setup.verifier.list_proposals(proposal_id=proposal["id"])[
                "proposals"
            ][0]["events"]
            if event["type"] == "verification_attested"
        ] == []

        _sign_and_record(setup, proposal, challenge)
        with pytest.raises(SelfIterationError, match="already been used"):
            _sign_and_record(setup, proposal, challenge)

    def test_challenge_cannot_be_substituted_across_proposals(self, verification_setup):
        setup = verification_setup
        first = setup.proposer.propose(**_proposal_args())
        second = setup.proposer.propose(
            **_proposal_args(observation="A different observed behavior.")
        )
        challenge = setup.verifier.prepare_verification(**_verification_args(first))
        signature = sign_attestation(challenge["attestation"], setup.verifier_key)

        with pytest.raises(SelfIterationError, match="issued verification challenge"):
            setup.verifier.record_verification(
                proposal_id=second["id"],
                challenge_id=challenge["challenge_id"],
                signature=signature,
            )
        assert (
            _sign_and_record(setup, first, challenge)["verification_state"]["status"]
            == "verified"
        )

    def test_parallel_challenge_cannot_bypass_one_active_verdict_rule(
        self, verification_setup
    ):
        setup = verification_setup
        proposal = setup.proposer.propose(**_proposal_args())
        first = setup.verifier.prepare_verification(**_verification_args(proposal))
        second = setup.verifier.prepare_verification(
            **_verification_args(
                proposal,
                verification_statement="A concurrently prepared second verdict.",
            )
        )

        _sign_and_record(setup, proposal, first)
        with pytest.raises(SelfIterationError, match="active verdict"):
            _sign_and_record(setup, proposal, second)

    def test_stale_proposal_digest_is_refused_after_challenge(self, verification_setup):
        setup = verification_setup
        proposal = setup.proposer.propose(**_proposal_args())
        challenge = setup.verifier.prepare_verification(**_verification_args(proposal))
        ledger = json.loads(setup.ledger.read_text())
        ledger_proposal = ledger["proposals"][0]
        ledger_proposal["observation"] = "Locally altered immutable content."
        ledger_proposal["content_sha256"] = proposal_content_sha256(ledger_proposal)
        setup.ledger.write_text(json.dumps(ledger))

        with pytest.raises(SelfIterationError, match="digest is stale"):
            _sign_and_record(setup, proposal, challenge)

    def test_verifier_identity_must_own_the_challenge(self, verification_setup):
        setup = verification_setup
        proposal = setup.proposer.propose(**_proposal_args())
        challenge = setup.verifier.prepare_verification(**_verification_args(proposal))
        signature = sign_attestation(challenge["attestation"], setup.verifier_key)

        with pytest.raises(SelfIterationError, match="does not own"):
            setup.other.record_verification(
                proposal_id=proposal["id"],
                challenge_id=challenge["challenge_id"],
                signature=signature,
            )

    def test_challenge_and_verdict_expiry_fail_closed(self, verification_setup):
        setup = verification_setup
        proposal = setup.proposer.propose(**_proposal_args())
        challenge = setup.verifier.prepare_verification(
            **_verification_args(
                proposal,
                expires_at=(setup.clock.value + timedelta(hours=1)).isoformat(),
            )
        )
        _sign_and_record(setup, proposal, challenge)
        setup.clock.advance(hours=2)
        state = setup.verifier.verification_status(proposal_id=proposal["id"])[
            "verification_state"
        ]
        assert state["status"] == "expired"
        assert state["effective_weight"] == 0.0

        second = setup.proposer.propose(
            **_proposal_args(observation="A second expiring challenge.")
        )
        second_challenge = setup.verifier.prepare_verification(
            **_verification_args(second)
        )
        setup.clock.advance(minutes=10)
        with pytest.raises(SelfIterationError, match="challenge has expired"):
            _sign_and_record(setup, second, second_challenge)

    def test_rejection_and_owner_revocation_remain_zero_weight(
        self, verification_setup
    ):
        setup = verification_setup
        proposal = setup.proposer.propose(**_proposal_args())
        rejection = setup.verifier.prepare_verification(
            **_verification_args(
                proposal,
                verification_decision="rejected",
                verification_statement="The canary did not reproduce the claimed gain.",
            )
        )
        rejected = _sign_and_record(setup, proposal, rejection)
        assert rejected["verification_state"]["status"] == "rejected"
        assert rejected["verification_state"]["effective_weight"] == 0.0

        with pytest.raises(SelfIterationError, match="original verifier"):
            setup.other.prepare_verification(
                **_verification_args(
                    rejected,
                    verification_decision="revoke",
                    verification_statement="Attempted foreign revocation.",
                    target_attestation_id=rejection["attestation_id"],
                )
            )

        revocation = setup.verifier.prepare_verification(
            **_verification_args(
                rejected,
                verification_decision="revoke",
                verification_statement="The evidence artifact was withdrawn.",
                target_attestation_id=rejection["attestation_id"],
            )
        )
        revoked = _sign_and_record(setup, proposal, revocation)
        assert revoked["verification_state"]["status"] == "revoked"
        assert revoked["verification_state"]["effective_weight"] == 0.0

    def test_conflict_or_missing_historical_key_fails_closed(self, verification_setup):
        setup = verification_setup
        proposal = setup.proposer.propose(**_proposal_args())
        verified_challenge = setup.verifier.prepare_verification(
            **_verification_args(proposal)
        )
        verified = _sign_and_record(setup, proposal, verified_challenge)

        rejected_challenge = setup.other.prepare_verification(
            **_verification_args(
                verified,
                verification_decision="rejected",
                verification_statement="A second canary contradicted the first.",
                verification_evidence=[
                    {
                        "kind": "test",
                        "uri": "artifact://canary/contradiction.json",
                        "sha256": "b" * 64,
                    }
                ],
            )
        )
        conflicted = _sign_and_record(
            setup,
            proposal,
            rejected_challenge,
            system=setup.other,
            key=setup.other_key,
        )
        assert conflicted["verification_state"]["status"] == "conflicted"
        assert conflicted["verification_state"]["effective_weight"] == 0.0

        setup.registry.keys.pop(("verifier-1", "key-v"))
        state = setup.other.verification_status(proposal_id=proposal["id"])[
            "verification_state"
        ]
        assert state["status"] == "invalid"
        assert state["effective_weight"] == 0.0
        assert state["invalid_attestations"][0]["reason"] == (
            "verifier key is unavailable"
        )

    def test_tampered_recorded_signature_is_derived_as_invalid(
        self, verification_setup
    ):
        setup = verification_setup
        proposal = setup.proposer.propose(**_proposal_args())
        challenge = setup.verifier.prepare_verification(**_verification_args(proposal))
        _sign_and_record(setup, proposal, challenge)
        ledger = json.loads(setup.ledger.read_text())
        ledger["proposals"][0]["events"][-1]["signature"]["value"] = "0" * 64
        setup.ledger.write_text(json.dumps(ledger))

        state = setup.verifier.verification_status(proposal_id=proposal["id"])[
            "verification_state"
        ]
        assert state["status"] == "invalid"
        assert state["priority_eligible"] is False

    def test_unsupported_unbound_proposal_fields_stop_ledger_use(
        self, verification_setup
    ):
        setup = verification_setup
        proposal = setup.proposer.propose(**_proposal_args())
        ledger = json.loads(setup.ledger.read_text())
        ledger["proposals"][0]["priority_override"] = True
        setup.ledger.write_text(json.dumps(ledger))
        tampered = setup.ledger.read_text()

        with pytest.raises(SelfIterationError, match="unsupported unbound fields"):
            setup.verifier.verification_status(proposal_id=proposal["id"])
        assert setup.ledger.read_text() == tampered


def test_environment_key_registry_supports_rotation_without_exposing_secret(
    monkeypatch,
):
    current_secret = b"c" * 32
    prior_secret = b"h" * 32
    monkeypatch.setenv(
        VERIFIER_KEYS_ENV,
        json.dumps(
            {
                "verifier-1": {
                    "active_key_id": "current",
                    "keys": {
                        "current": base64.urlsafe_b64encode(current_secret)
                        .decode()
                        .rstrip("="),
                        "prior": base64.urlsafe_b64encode(prior_secret)
                        .decode()
                        .rstrip("="),
                    },
                }
            }
        ),
    )

    current = verifier_key_from_env("verifier-1")
    prior = verifier_key_from_env("verifier-1", "prior")
    assert current is not None and current.key_id == "current"
    assert prior is not None and prior.key_id == "prior"
    assert "secret=" not in repr(current)

    monkeypatch.setenv(VERIFIER_KEYS_ENV, json.dumps({"verifier-1": "bad"}))
    with pytest.raises(VerificationError) as exc_info:
        verifier_key_from_env("verifier-1")
    assert "cccc" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_handler_completes_signed_verification(verification_setup, monkeypatch):
    setup = verification_setup
    proposal = setup.proposer.propose(**_proposal_args())
    monkeypatch.setattr(
        "anima_mcp.handlers.self_iteration.get_self_iteration_system",
        lambda: setup.verifier,
    )
    from anima_mcp.handlers.self_iteration import handle_self_iteration

    prepared = parse_result(
        await handle_self_iteration(
            {"action": "prepare_verification", **_verification_args(proposal)}
        )
    )
    challenge = prepared["challenge"]
    signature = sign_attestation(challenge["attestation"], setup.verifier_key)
    recorded = parse_result(
        await handle_self_iteration(
            {
                "action": "record_verification",
                "proposal_id": proposal["id"],
                "challenge_id": challenge["challenge_id"],
                "signature": signature,
            }
        )
    )
    status = parse_result(
        await handle_self_iteration(
            {"action": "verification_status", "proposal_id": proposal["id"]}
        )
    )

    assert prepared["success"] is True
    assert recorded["proposal"]["verification_state"]["status"] == "verified"
    assert status["verification_state"]["status"] == "verified"
