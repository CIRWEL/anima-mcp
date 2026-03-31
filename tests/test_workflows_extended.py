from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from conftest import parse_result


@pytest.mark.asyncio
async def test_unified_workflow_errors_when_store_missing():
    from anima_mcp.handlers.workflows import handle_unified_workflow

    with patch("anima_mcp.accessors._get_store", return_value=None):
        data = parse_result(await handle_unified_workflow({}))
    assert "error" in data


@pytest.mark.asyncio
async def test_unified_workflow_lists_available_templates_when_workflow_missing():
    from anima_mcp.handlers.workflows import handle_unified_workflow

    store = MagicMock()
    sensors = MagicMock()
    orchestrator = MagicMock()

    templates_instance = MagicMock()
    templates_instance.list_templates.return_value = [{"name": "t1"}, {"name": "t2"}]

    with patch("anima_mcp.accessors._get_store", return_value=store), \
         patch("anima_mcp.accessors._get_sensors", return_value=sensors), \
         patch("anima_mcp.workflow_orchestrator.get_orchestrator", return_value=orchestrator), \
         patch("anima_mcp.workflow_templates.WorkflowTemplates", return_value=templates_instance):
        data = parse_result(await handle_unified_workflow({}))

    assert "available_workflows" in data
    assert "available_templates" in data
    assert data["available_templates"] == ["t1", "t2"]


@pytest.mark.asyncio
async def test_unified_workflow_runs_template_when_found():
    from anima_mcp.handlers.workflows import handle_unified_workflow

    store = MagicMock()
    sensors = MagicMock()
    orchestrator = MagicMock()

    templates_instance = MagicMock()
    templates_instance.get_template.return_value = {"name": "my_template"}
    templates_instance.run = AsyncMock(return_value=SimpleNamespace(
        status=SimpleNamespace(value="success"),
        summary="ok",
        steps={"a": {"ok": True}},
        errors={},
    ))

    with patch("anima_mcp.accessors._get_store", return_value=store), \
         patch("anima_mcp.accessors._get_sensors", return_value=sensors), \
         patch("anima_mcp.workflow_orchestrator.get_orchestrator", return_value=orchestrator), \
         patch("anima_mcp.workflow_templates.WorkflowTemplates", return_value=templates_instance):
        data = parse_result(await handle_unified_workflow({"workflow": "my_template"}))

    assert data["status"] == "success"
    assert data["template"] == "my_template"
    assert data["steps"]["a"]["ok"] is True


@pytest.mark.asyncio
async def test_unified_workflow_unknown_workflow_suggests_alternatives():
    from anima_mcp.handlers.workflows import handle_unified_workflow

    store = MagicMock()
    sensors = MagicMock()
    orchestrator = MagicMock()

    templates_instance = MagicMock()
    templates_instance.get_template.return_value = None
    templates_instance.list_templates.return_value = [{"name": "t1"}]

    with patch("anima_mcp.accessors._get_store", return_value=store), \
         patch("anima_mcp.accessors._get_sensors", return_value=sensors), \
         patch("anima_mcp.workflow_orchestrator.get_orchestrator", return_value=orchestrator), \
         patch("anima_mcp.workflow_templates.WorkflowTemplates", return_value=templates_instance):
        data = parse_result(await handle_unified_workflow({"workflow": "nope"}))

    assert "error" in data
    assert "available_templates" in data
    assert data["available_templates"] == ["t1"]

