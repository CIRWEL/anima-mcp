"""Tests for bounded code self-awareness and the iteration proposal ledger."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from anima_mcp.self_iteration import SelfIterationError, SelfIterationSystem
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
    return SelfIterationSystem(
        repo_root=source_repo,
        ledger_path=tmp_path / "state" / "self_iteration.json",
        clock=lambda: fixed_now,
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

        assert overview["autonomy_level"] == "proposal_only"
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
        assert overview["capabilities"]["write_source"] is False
        assert overview["capabilities"]["execute_proposal_text"] is False
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
            measurement_source="self_observation",
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
        assert len(proposal["code_fingerprint"]["manifest_sha256"]) == 64
        assert proposal["implementation_policy"]["source_writes_performed"] is False
        assert proposal["implementation_policy"]["commands_executed"] is False
        assert system.ledger_path.exists()

        loaded = system.list_proposals(proposal_id=proposal["id"])
        assert loaded["count"] == 1
        assert loaded["proposals"][0]["hypothesis"] == proposal["hypothesis"]

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
            measurement_source="automated_test",
        )

        assert updated["status"] == "retained"
        assert [event["type"] for event in updated["events"]] == [
            "proposed",
            "outcome_recorded",
        ]
        assert updated["events"][-1]["decision"] == "keep"
        assert updated["events"][-1]["implementation_ref"] == "commit:abc123"
        assert updated["events"][-1]["measurement_source"] == "automated_test"

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
            ({"measurement_source": "unverified_oracle"}, "measurement_source"),
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

    assert actions == ["inspect", "propose", "list", "record_outcome"]
    assert "implement" not in actions
    assert "deploy" not in actions
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

    assert result["code"]["autonomy_level"] == "proposal_only"
    assert result["code"]["source"]["available"] is True
    assert result["code"]["capabilities"]["write_source"] is False
    assert result["code"]["boundary_summary"]["protected_surface_count"] > 0
