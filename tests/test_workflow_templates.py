"""Tests for WorkflowTemplates - pre-defined workflow patterns."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from anima_mcp.workflow_templates import WorkflowTemplate, WorkflowTemplates
from anima_mcp.workflow_orchestrator import (
    UnifiedWorkflowOrchestrator,
    WorkflowStep,
    WorkflowResult,
    WorkflowStatus,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def templates():
    mock_orchestrator = MagicMock(spec=UnifiedWorkflowOrchestrator)
    return WorkflowTemplates(mock_orchestrator)


# ---------------------------------------------------------------------------
# WorkflowTemplate dataclass
# ---------------------------------------------------------------------------

class TestWorkflowTemplateDataclass:
    def test_instantiation_with_defaults(self):
        step = WorkflowStep(name="s1", server="anima", tool="get_state", arguments={})
        t = WorkflowTemplate(name="test", description="A test", steps=[step])
        assert t.name == "test"
        assert t.description == "A test"
        assert t.steps == [step]
        assert t.parallel is False
        assert t.category == "general"

    def test_instantiation_with_overrides(self):
        step = WorkflowStep(name="s1", server="anima", tool="get_state", arguments={})
        t = WorkflowTemplate(
            name="custom",
            description="Custom template",
            steps=[step],
            parallel=True,
            category="health",
        )
        assert t.parallel is True
        assert t.category == "health"


# ---------------------------------------------------------------------------
# list_templates
# ---------------------------------------------------------------------------

class TestListTemplates:
    def test_returns_six_templates(self, templates):
        result = templates.list_templates()
        assert len(result) == 6

    def test_each_entry_has_required_keys(self, templates):
        required_keys = {"name", "description", "category", "steps", "parallel"}
        for entry in templates.list_templates():
            assert required_keys.issubset(entry.keys())

    def test_steps_count_is_int(self, templates):
        for entry in templates.list_templates():
            assert isinstance(entry["steps"], int)
            assert entry["steps"] >= 1

    def test_known_template_names(self, templates):
        names = {entry["name"] for entry in templates.list_templates()}
        expected = {
            "health_check",
            "full_system_check",
            "learning_check",
            "governance_check",
            "identity_check",
            "sensor_analysis",
        }
        assert names == expected


# ---------------------------------------------------------------------------
# get_template
# ---------------------------------------------------------------------------

class TestGetTemplate:
    def test_known_returns_workflow_template(self, templates):
        t = templates.get_template("health_check")
        assert isinstance(t, WorkflowTemplate)
        assert t.name == "health_check"

    def test_unknown_returns_none(self, templates):
        assert templates.get_template("nonexistent") is None

    def test_health_check_is_parallel(self, templates):
        t = templates.get_template("health_check")
        assert t.parallel is True

    def test_full_system_check_is_sequential(self, templates):
        t = templates.get_template("full_system_check")
        assert t.parallel is False


# ---------------------------------------------------------------------------
# get_template_info
# ---------------------------------------------------------------------------

class TestGetTemplateInfo:
    def test_known_returns_dict_with_steps_list(self, templates):
        info = templates.get_template_info("health_check")
        assert isinstance(info, dict)
        assert "steps" in info
        assert isinstance(info["steps"], list)
        for step in info["steps"]:
            assert "name" in step
            assert "server" in step
            assert "tool" in step
            assert "arguments" in step
            assert "depends_on" in step

    def test_unknown_returns_none(self, templates):
        assert templates.get_template_info("nonexistent") is None

    def test_info_matches_template(self, templates):
        info = templates.get_template_info("identity_check")
        assert info["name"] == "identity_check"
        assert info["category"] == "identity"
        assert len(info["steps"]) == 1


# ---------------------------------------------------------------------------
# run (async)
# ---------------------------------------------------------------------------

class TestRun:
    @pytest.mark.asyncio
    async def test_unknown_template_returns_failed(self, templates):
        result = await templates.run("unknown")
        assert isinstance(result, WorkflowResult)
        assert result.status == WorkflowStatus.FAILED
        assert "unknown" in result.errors.get("template", "").lower()

    @pytest.mark.asyncio
    async def test_known_template_calls_orchestrator(self, templates):
        expected_result = WorkflowResult(
            status=WorkflowStatus.SUCCESS,
            steps={"get_state": {}, "read_sensors": {}},
            errors={},
            summary="ok",
        )
        templates._orchestrator.execute_workflow = AsyncMock(return_value=expected_result)

        result = await templates.run("health_check")

        templates._orchestrator.execute_workflow.assert_awaited_once()
        call_kwargs = templates._orchestrator.execute_workflow.call_args
        assert call_kwargs.kwargs["parallel"] is True
        assert result.status == WorkflowStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_steps_passed_to_orchestrator(self, templates):
        expected_result = WorkflowResult(
            status=WorkflowStatus.SUCCESS,
            steps={},
            errors={},
            summary="ok",
        )
        templates._orchestrator.execute_workflow = AsyncMock(return_value=expected_result)

        await templates.run("identity_check")

        call_kwargs = templates._orchestrator.execute_workflow.call_args
        steps = call_kwargs.kwargs["steps"]
        assert len(steps) == 1
        assert steps[0].name == "get_identity"
        assert steps[0].server == "anima"
