"""Tests for bounded code self-awareness and the iteration proposal ledger."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from anima_mcp.self_iteration import (
    PROVENANCE_SCHEMA,
    SelfIterationError,
    SelfIterationSystem,
)
from conftest import parse_result


@pytest.fixture
def source_repo(tmp_path):
    root = tmp_path / "anima-mcp"
    files = {
        "pyproject.toml": '[project]\nname = "anima-mcp"\nversion = "9.9.9"\n',
        "README.md": "# Test creature\n",
        "src/anima_mcp/sample.py": (
            '"""Example source module."""\n'
            "import json\n\n"
            "class Creature:\n"
            '    """A test creature."""\n'
            "    pass\n\n"
            "async def awaken():\n"
            '    """Wake the creature."""\n'
            "    return True\n"
        ),
        "src/anima_mcp/identity/store.py": "class IdentityStore:\n    pass\n",
        "src/anima_mcp/display/eras/test_era.py": "def draw():\n    return None\n",
        "tests/test_sample.py": "def test_sample():\n    assert True\n",
        "docs/guide.md": "# Guide\n",
        ".env": "SECRET=never-inspect\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


@pytest.fixture
def system(source_repo, tmp_path):
    fixed_now = datetime(2026, 8, 11, 21, 30, tzinfo=timezone.utc)

    def provenance_provider(recorded_at):
        return {
            "schema": PROVENANCE_SCHEMA,
            "recorded_by": "anima-mcp-test-server",
            "recorded_at": recorded_at,
            "transport": {"kind": "test", "server_observed": True},
            "authentication": {"method": "none", "verified": False},
            "actor": None,
            "session": {"present": False, "verified": False},
            "trust": {},
        }

    return SelfIterationSystem(
        repo_root=source_repo,
        ledger_path=tmp_path / "state" / "self_iteration.json",
        clock=lambda: fixed_now,
        provenance_provider=provenance_provider,
    )


def _proposal_args(**overrides):
    values = {
        "observation": "The geometric era repeats the same mark after convergence.",
        "hypothesis": "Varying the bounded era seed will reduce repeated marks.",
        "expected_outcome": "Duplicate mark rate falls below ten percent over twenty drawings.",
        "evidence": ["8 of the last 20 drawings repeated the same mark"],
        "target_paths": ["src/anima_mcp/display/eras/test_era.py"],
        "verification": ["Compare duplicate mark rate across twenty canary drawings"],
        "risk": "low",
    }
    values.update(overrides)
    return values


class TestSourceAwareness:
    def test_overview_reports_fingerprint_architecture_and_hard_capabilities(
        self, system
    ):
        overview = system.inspect()

        assert overview["autonomy_level"] == "externally_approved_isolated_execution"
        assert overview["source"]["available"] is True
        assert overview["source"]["manifest"]["file_count"] == 7
        assert len(overview["source"]["manifest"]["sha256"]) == 64
        assert {
            item["name"] for item in overview["source"]["manifest"]["architecture"]
        } >= {
            "identity",
            "expression",
            "interface",
        }
        assert overview["capabilities"]["inspect_structure"] is True
        assert overview["capabilities"]["accept_caller_supplied_provenance"] is False
        assert overview["capabilities"]["weight_unverified_ledger_claims"] is False
        assert overview["capabilities"]["prepare_signed_verification"] is True
        assert overview["capabilities"]["construct_quarantined_patch_artifacts"] is True
        assert overview["capabilities"]["run_nonexecuting_static_evaluation"] is True
        assert (
            overview["capabilities"]["verification_grants_implementation_authority"]
            is False
        )
        assert overview["capabilities"]["write_source"] is False
        assert overview["capabilities"]["execute_proposal_text"] is False
        assert overview["capabilities"]["execute_candidate_code"] is True
        assert overview["capabilities"]["execute_tests"] is True
        assert overview["capabilities"]["execute_candidate_code_on_host"] is False
        assert (
            overview["capabilities"]["execute_candidate_code_in_pinned_container"]
            is True
        )
        assert overview["capabilities"]["deploy"] is False

    def test_optional_file_manifest_is_bounded(self, system):
        overview = system.inspect(include_files=True, file_limit=2)
        manifest = overview["source"]["manifest"]

        assert len(manifest["files"]) == 2
        assert manifest["files_truncated"] is True
        assert all("sha256" in item for item in manifest["files"])

    def test_python_path_inspection_returns_structure_not_source(self, system):
        result = system.inspect(path="src/anima_mcp/sample.py")

        assert result["source_body_included"] is False
        assert result["structure"]["module_summary"] == "Example source module."
        assert [item["name"] for item in result["structure"]["symbols"]] == [
            "Creature",
            "awaken",
        ]
        assert result["structure"]["imports"] == ["json"]
        assert "Example source module" not in json.dumps(result.get("source"))

    @pytest.mark.parametrize(
        "path",
        ["../outside.py", "/tmp/outside.py", ".env", "src//anima_mcp/sample.py"],
    )
    def test_path_inspection_rejects_escape_sensitive_and_ambiguous_paths(
        self, system, path
    ):
        with pytest.raises(SelfIterationError):
            system.inspect(path=path)

    def test_boundaries_distinguish_candidate_review_and_protected_core(self, system):
        candidate = system.classify_target("src/anima_mcp/display/eras/test_era.py")
        review = system.classify_target("src/anima_mcp/sample.py")
        protected = system.classify_target("src/anima_mcp/identity/store.py")

        assert candidate["boundary"] == "bounded_candidate"
        assert candidate["auto_implementation_eligible"] is True
        assert review["boundary"] == "human_review_required"
        assert review["auto_implementation_eligible"] is False
        assert protected["boundary"] == "protected_core"
        assert protected["risk_floor"] == "high"


class TestProposalLedger:
    def test_complete_iteration_round_trip_never_writes_repository(
        self, system, source_repo
    ):
        before = {
            path.relative_to(source_repo): path.read_bytes()
            for path in source_repo.rglob("*")
            if path.is_file()
        }

        proposal = system.propose(**_proposal_args())
        system.record_outcome(
            proposal_id=proposal["id"],
            decision="inconclusive",
            observed_outcome="The canary window was too short.",
            evidence=["Only two drawings completed"],
            implementation_ref="deployment:canary-1",
            claimed_measurement_source="self_observation",
        )

        after = {
            path.relative_to(source_repo): path.read_bytes()
            for path in source_repo.rglob("*")
            if path.is_file()
        }
        assert after == before

    def test_proposal_persists_evidence_fingerprint_and_no_mutation_claim(self, system):
        proposal = system.propose(**_proposal_args())

        assert proposal["id"].startswith("si-20260811-")
        assert proposal["status"] == "ready_for_isolated_implementation"
        assert proposal["risk"]["effective"] == "low"
        assert "source" not in proposal
        assert proposal["source_claim"] == {
            "field": "claimed_source",
            "value": "self_observation",
            "epistemic_status": "caller_claimed",
            "verified": False,
            "authority_granted": False,
        }
        assert proposal["provenance"]["recorded_by"] == "anima-mcp-test-server"
        assert proposal["provenance"]["trust"]["claims_verified"] is False
        assert proposal["provenance"]["trust"]["evidence_verified"] is False
        assert proposal["provenance"]["integrity"]["tamper_evident"] is False
        assert proposal["provenance"]["integrity"]["cryptographically_signed"] is False
        assert proposal["trust_policy"]["effective_weight"] == 0.0
        assert proposal["trust_policy"]["priority_eligible"] is False
        assert proposal["trust_policy"]["automation_eligible"] is False
        assert proposal["trust_policy"]["authority_eligible"] is False
        assert len(proposal["code_fingerprint"]["manifest_sha256"]) == 64
        assert len(proposal["content_sha256"]) == 64
        assert proposal["verification_state"]["status"] == "unverified"
        assert proposal["verification_state"]["effective_weight"] == 0.0
        assert proposal["implementation_policy"]["source_writes_performed"] is False
        assert proposal["implementation_policy"]["commands_executed"] is False
        assert (
            proposal["implementation_policy"]["provenance_authorizes_execution"]
            is False
        )
        assert system.ledger_path.exists()

        loaded = system.list_proposals(proposal_id=proposal["id"])
        assert loaded["count"] == 1
        assert loaded["proposals"][0]["hypothesis"] == proposal["hypothesis"]

    def test_server_receipt_identifies_actor_without_verifying_claims_or_session(
        self, source_repo, tmp_path, monkeypatch
    ):
        raw_session = "opaque-session-secret"
        raw_token = "opaque-bearer-secret"
        monkeypatch.setattr(
            "anima_mcp.self_iteration._current_request_headers",
            lambda: {"mcp-session-id": raw_session},
        )
        monkeypatch.setattr(
            "anima_mcp.self_iteration._current_access_token",
            lambda: SimpleNamespace(
                token=raw_token,
                subject="operator-7",
                client_id="anima-client",
                scopes=["write", "read"],
                claims={"iss": "https://auth.example.test"},
            ),
        )
        system = SelfIterationSystem(
            repo_root=source_repo,
            ledger_path=tmp_path / "authenticated-ledger.json",
            clock=lambda: datetime(2026, 8, 11, 21, 30, tzinfo=timezone.utc),
        )

        proposal = system.propose(**_proposal_args(claimed_source="governance"))
        provenance = proposal["provenance"]

        assert provenance["actor"] == {
            "kind": "oauth_subject",
            "id": "operator-7",
            "client_id": "anima-client",
            "issuer": "https://auth.example.test",
            "scopes": ["read", "write"],
            "verified": True,
        }
        assert provenance["authentication"]["verified"] is True
        assert (
            provenance["session"]["identifier_sha256"]
            == hashlib.sha256(raw_session.encode("utf-8")).hexdigest()
        )
        assert provenance["session"]["verified"] is False
        assert provenance["trust"]["actor_authenticated"] is True
        assert provenance["trust"]["claims_verified"] is False
        assert provenance["trust"]["evidence_verified"] is False
        assert provenance["integrity"]["tamper_evident"] is False
        serialized = json.dumps(proposal)
        assert raw_session not in serialized
        assert raw_token not in serialized

    def test_server_receipt_cannot_upgrade_claim_truth_or_authority(
        self, source_repo, tmp_path
    ):
        def overclaiming_provider(recorded_at):
            return {
                "schema": PROVENANCE_SCHEMA,
                "recorded_by": "overclaiming-test-provider",
                "recorded_at": recorded_at,
                "authentication": {"verified": True},
                "actor": {"id": "operator-7", "verified": True},
                "integrity": {
                    "tamper_evident": True,
                    "cryptographically_signed": True,
                },
                "trust": {
                    "claims_verified": True,
                    "evidence_verified": True,
                    "weighting_eligible": True,
                    "authority_eligible": True,
                },
            }

        system = SelfIterationSystem(
            repo_root=source_repo,
            ledger_path=tmp_path / "overclaiming-ledger.json",
            provenance_provider=overclaiming_provider,
        )

        proposal = system.propose(**_proposal_args())

        assert proposal["provenance"]["trust"]["claims_verified"] is False
        assert proposal["provenance"]["trust"]["evidence_verified"] is False
        assert proposal["provenance"]["trust"]["weighting_eligible"] is False
        assert proposal["provenance"]["trust"]["authority_eligible"] is False
        assert proposal["provenance"]["integrity"]["tamper_evident"] is False
        assert proposal["provenance"]["integrity"]["cryptographically_signed"] is False
        assert proposal["trust_policy"]["effective_weight"] == 0.0

    def test_schema_v1_migrates_labels_to_legacy_unverified_claims(self, system):
        legacy = {
            "schema_version": 1,
            "proposals": [
                {
                    "id": "si-legacy",
                    "created_at": "2026-08-10T10:00:00Z",
                    "source": "governance",
                    "status": "retained",
                    "evidence": ["caller-authored evidence"],
                    "events": [
                        {
                            "type": "proposed",
                            "at": "2026-08-10T10:00:00Z",
                        },
                        {
                            "type": "outcome_recorded",
                            "at": "2026-08-10T11:00:00Z",
                            "measurement_source": "automated_test",
                            "evidence": ["caller-authored outcome evidence"],
                        },
                    ],
                }
            ],
        }
        system.ledger_path.parent.mkdir(parents=True)
        system.ledger_path.write_text(json.dumps(legacy))

        result = system.list_proposals(proposal_id="si-legacy")
        proposal = result["proposals"][0]
        outcome = proposal["events"][1]
        migration = proposal["events"][2]
        verification_migration = proposal["events"][3]
        sandbox_migration = proposal["events"][4]
        execution_migration = proposal["events"][5]

        assert "source" not in proposal
        assert proposal["source_claim"]["value"] == "governance"
        assert proposal["source_claim"]["epistemic_status"] == "caller_claimed_legacy"
        assert proposal["source_claim"]["verified"] is False
        assert proposal["provenance"]["trust"]["classification"] == "legacy_unverified"
        assert proposal["provenance"]["recorded_at_verified"] is False
        assert proposal["trust_policy"]["effective_weight"] == 0.0
        assert "measurement_source" not in outcome
        assert outcome["measurement_source_claim"]["value"] == "automated_test"
        assert outcome["measurement_source_claim"]["verified"] is False
        assert outcome["provenance"]["trust"]["classification"] == "legacy_unverified"
        assert migration["type"] == "provenance_migrated"
        assert migration["authority_granted"] is False
        assert verification_migration["type"] == "verification_schema_migrated"
        assert verification_migration["authority_granted"] is False
        assert sandbox_migration["type"] == "sandbox_schema_migrated"
        assert sandbox_migration["authority_granted"] is False
        assert execution_migration["type"] == "execution_schema_migrated"
        assert execution_migration["authority_granted"] is False
        assert proposal["proposer_identity"] is None
        assert proposal["verification_state"]["status"] == "unverified"

        on_disk = json.loads(system.ledger_path.read_text())
        assert on_disk["schema_version"] == 5
        assert on_disk["provenance_contract"]["unverified_effective_weight"] == 0.0
        assert on_disk["verification_contract"]["verified_priority_eligible"] is True
        assert on_disk["migrations"] == [
            {
                "type": "schema_migration",
                "at": "2026-08-11T21:30:00Z",
                "from_schema": 1,
                "to_schema": 2,
                "classification": "legacy_unverified",
            },
            {
                "type": "schema_migration",
                "at": "2026-08-11T21:30:00Z",
                "from_schema": 2,
                "to_schema": 3,
                "classification": "verification_requires_signed_attestation",
            },
            {
                "type": "schema_migration",
                "at": "2026-08-11T21:30:00Z",
                "from_schema": 3,
                "to_schema": 4,
                "classification": "quarantined_patch_static_evaluation_only",
            },
            {
                "type": "schema_migration",
                "at": "2026-08-11T21:30:00Z",
                "from_schema": 4,
                "to_schema": 5,
                "classification": "externally_approved_isolated_execution_only",
            },
        ]

        migrated_once = system.ledger_path.read_text()
        system.list_proposals(proposal_id="si-legacy")
        assert system.ledger_path.read_text() == migrated_once
        assert system.inspect()["ledger"]["legacy_unverified_count"] == 1

    def test_protected_target_raises_boundary_risk_and_requires_review(self, system):
        proposal = system.propose(
            **_proposal_args(target_paths=["tests/test_sample.py"], risk="low")
        )

        assert proposal["status"] == "protected_review_required"
        assert proposal["risk"] == {
            "self_assessed": "low",
            "boundary_floor": "high",
            "effective": "high",
        }
        assert proposal["boundaries"][0]["auto_implementation_eligible"] is False

    def test_default_surface_routes_to_human_review(self, system):
        proposal = system.propose(
            **_proposal_args(target_paths=["src/anima_mcp/sample.py"])
        )
        assert proposal["status"] == "human_review_required"
        assert proposal["risk"]["effective"] == "medium"

    @pytest.mark.parametrize(
        "override, message",
        [
            ({"evidence": []}, "evidence"),
            ({"verification": []}, "verification"),
            ({"target_paths": ["../escape.py"]}, "path"),
            ({"target_paths": ["docs/guide.md", "docs/guide.md"]}, "duplicates"),
            ({"risk": "unchecked"}, "risk"),
        ],
    )
    def test_invalid_proposals_are_not_persisted(self, system, override, message):
        with pytest.raises(SelfIterationError, match=message):
            system.propose(**_proposal_args(**override))
        assert system.list_proposals()["count"] == 0

    def test_record_outcome_appends_evidence_and_closes_loop(self, system):
        proposal = system.propose(**_proposal_args())

        updated = system.record_outcome(
            proposal_id=proposal["id"],
            decision="keep",
            observed_outcome="Duplicate mark rate fell to five percent.",
            evidence=["1 duplicate in 20 canary drawings"],
            implementation_ref="commit:abc123",
            claimed_measurement_source="automated_test",
        )

        assert updated["status"] == "retained"
        assert [event["type"] for event in updated["events"]] == [
            "proposed",
            "outcome_recorded",
        ]
        assert updated["events"][-1]["decision"] == "keep"
        assert updated["events"][-1]["implementation_ref"] == "commit:abc123"
        assert "measurement_source" not in updated["events"][-1]
        assert updated["events"][-1]["measurement_source_claim"] == {
            "field": "claimed_measurement_source",
            "value": "automated_test",
            "epistemic_status": "caller_claimed",
            "verified": False,
            "authority_granted": False,
        }
        assert updated["events"][-1]["trust_policy"]["effective_weight"] == 0.0
        assert updated["events"][-1]["provenance"]["trust"]["claims_verified"] is False

    def test_unknown_outcome_proposal_is_rejected(self, system):
        with pytest.raises(SelfIterationError, match="proposal not found"):
            system.record_outcome(
                proposal_id="si-missing",
                decision="revert",
                observed_outcome="The canary regressed.",
                evidence=["Regression test failed"],
                implementation_ref="deployment:missing",
            )

    @pytest.mark.parametrize(
        "override, message",
        [
            ({"implementation_ref": None}, "implementation_ref"),
            (
                {"claimed_measurement_source": "unverified_oracle"},
                "claimed_measurement_source",
            ),
        ],
    )
    def test_outcome_requires_implementation_link_and_known_provenance(
        self, system, override, message
    ):
        proposal = system.propose(**_proposal_args())
        arguments = {
            "proposal_id": proposal["id"],
            "decision": "inconclusive",
            "observed_outcome": "The observation window was too short.",
            "evidence": ["Only two canary drawings completed"],
            "implementation_ref": "deployment:canary-1",
        }
        arguments.update(override)

        with pytest.raises(SelfIterationError, match=message):
            system.record_outcome(**arguments)

    def test_corrupt_ledger_is_never_silently_overwritten(self, system):
        system.ledger_path.parent.mkdir(parents=True)
        system.ledger_path.write_text("not-json")

        inspection = system.inspect()
        with pytest.raises(SelfIterationError, match="refusing to overwrite"):
            system.propose(**_proposal_args())
        assert "refusing to overwrite" in inspection["ledger"]["error"]
        assert inspection["source"]["available"] is True
        assert system.ledger_path.read_text() == "not-json"

    def test_tampered_v2_trust_bits_fail_closed_without_overwrite(self, system):
        proposal = system.propose(**_proposal_args())
        tampered = json.loads(system.ledger_path.read_text())
        tampered["proposals"][0]["provenance"]["trust"]["claims_verified"] = True
        system.ledger_path.write_text(json.dumps(tampered))
        tampered_text = system.ledger_path.read_text()

        inspection = system.inspect()
        with pytest.raises(SelfIterationError, match="zero-trust contract"):
            system.record_outcome(
                proposal_id=proposal["id"],
                decision="inconclusive",
                observed_outcome="No trusted conclusion is available.",
                evidence=["The ledger trust bit was modified"],
                implementation_ref="audit:tamper-detected",
            )

        assert "zero-trust contract" in inspection["ledger"]["error"]
        assert inspection["ledger"]["writes_allowed"] is False
        assert system.ledger_path.read_text() == tampered_text


@pytest.mark.asyncio
class TestSelfIterationHandler:
    async def test_handler_exposes_inspect_and_propose_without_execution(
        self, system, monkeypatch
    ):
        monkeypatch.setattr(
            "anima_mcp.handlers.self_iteration.get_self_iteration_system",
            lambda: system,
        )
        from anima_mcp.handlers.self_iteration import handle_self_iteration

        inspection = parse_result(await handle_self_iteration({"action": "inspect"}))
        proposed = parse_result(
            await handle_self_iteration({"action": "propose", **_proposal_args()})
        )

        assert inspection["capabilities"]["write_source"] is False
        assert proposed["success"] is True
        assert (
            proposed["proposal"]["implementation_policy"]["commands_executed"] is False
        )

    async def test_handler_treats_legacy_source_and_spoofed_provenance_as_inert(
        self, system, monkeypatch
    ):
        monkeypatch.setattr(
            "anima_mcp.handlers.self_iteration.get_self_iteration_system",
            lambda: system,
        )
        from anima_mcp.handlers.self_iteration import handle_self_iteration

        result = parse_result(
            await handle_self_iteration(
                {
                    "action": "propose",
                    **_proposal_args(),
                    "source": "governance",
                    "provenance": {
                        "recorded_by": "caller",
                        "trust": {"claims_verified": True},
                    },
                }
            )
        )

        assert result["deprecated_fields"] == {"source": "claimed_source"}
        assert result["proposal"]["source_claim"]["value"] == "governance"
        assert result["proposal"]["provenance"]["recorded_by"] == (
            "anima-mcp-test-server"
        )
        assert result["proposal"]["provenance"]["trust"]["claims_verified"] is False

    async def test_handler_rejects_conflicting_claim_aliases(self, system, monkeypatch):
        monkeypatch.setattr(
            "anima_mcp.handlers.self_iteration.get_self_iteration_system",
            lambda: system,
        )
        from anima_mcp.handlers.self_iteration import handle_self_iteration

        result = parse_result(
            await handle_self_iteration(
                {
                    "action": "propose",
                    **_proposal_args(),
                    "claimed_source": "self_observation",
                    "source": "governance",
                }
            )
        )

        assert "must not conflict" in result["error"]
        assert system.list_proposals()["count"] == 0

    async def test_handler_returns_contract_error_for_unknown_action(
        self, system, monkeypatch
    ):
        monkeypatch.setattr(
            "anima_mcp.handlers.self_iteration.get_self_iteration_system",
            lambda: system,
        )
        from anima_mcp.handlers.self_iteration import handle_self_iteration

        result = parse_result(
            await handle_self_iteration({"action": "rewrite_live_files"})
        )

        assert "error" in result
        assert "rewrite_live_files" in result["error"]
        assert "propose" in result["allowed_actions"]


def test_tool_registry_exposes_only_bounded_self_iteration_actions():
    from anima_mcp.tool_registry import HANDLERS, TOOLS

    tool = next(item for item in TOOLS if item.name == "self_iteration")
    actions = tool.inputSchema["properties"]["action"]["enum"]
    properties = tool.inputSchema["properties"]

    assert actions == [
        "inspect",
        "propose",
        "list",
        "prepare_verification",
        "record_verification",
        "verification_status",
        "construct_patch",
        "evaluate_patch",
        "patch_status",
        "prepare_execution",
        "execute_candidate",
        "execution_status",
        "record_outcome",
    ]
    assert "implement" not in actions
    assert "deploy" not in actions
    assert "claimed_source" in properties
    assert "source" not in properties
    assert "claimed_measurement_source" in properties
    assert "measurement_source" not in properties
    assert "provenance" not in properties
    assert properties["verification_evidence"]["items"]["additionalProperties"] is False
    assert properties["signature"]["pattern"] == "^[0-9a-fA-F]{64}$"
    assert properties["changes"]["maxItems"] == 3
    assert properties["changes"]["items"]["additionalProperties"] is False
    assert properties["candidate_id"]["pattern"] == "^sip-[0-9a-f]{32}$"
    assert properties["execution_profile_id"]["enum"] == ["display_era_pytest_v1"]
    assert properties["include_output"]["default"] is False
    assert "self_iteration" in HANDLERS


@pytest.mark.asyncio
async def test_lumen_context_can_include_compact_code_awareness(system, monkeypatch):
    monkeypatch.setattr(
        "anima_mcp.self_iteration.get_self_iteration_system",
        lambda: system,
    )
    monkeypatch.setattr("anima_mcp.accessors._get_store", lambda: None)
    monkeypatch.setattr(
        "anima_mcp.accessors._get_sensors",
        lambda: SimpleNamespace(is_pi=lambda: False),
    )
    monkeypatch.setattr(
        "anima_mcp.accessors._get_readings_and_anima",
        lambda: (None, None),
    )

    from anima_mcp.handlers.workflows import handle_get_lumen_context

    result = parse_result(await handle_get_lumen_context({"include": ["code"]}))

    assert result["code"]["autonomy_level"] == (
        "externally_approved_isolated_execution"
    )
    assert result["code"]["source"]["available"] is True
    assert result["code"]["capabilities"]["write_source"] is False
    assert result["code"]["boundary_summary"]["protected_surface_count"] > 0
