"""MCP handler for bounded code self-awareness and iteration proposals."""

from __future__ import annotations

import json

from mcp.types import TextContent

from ..self_iteration import SelfIterationError, get_self_iteration_system


def _text(payload: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, indent=2))]


def _claimed_input(
    arguments: dict, *, current: str, legacy: str, default: str
) -> tuple[object, bool]:
    """Read a caller claim while keeping the former field as an inert alias."""
    if current in arguments and legacy in arguments:
        if arguments[current] != arguments[legacy]:
            raise SelfIterationError(
                f"{current} and deprecated {legacy} must not conflict"
            )
    if current in arguments:
        return arguments[current], False
    if legacy in arguments:
        return arguments[legacy], True
    return default, False


async def handle_self_iteration(arguments: dict) -> list[TextContent]:
    """Inspect source structure or update the proposal/outcome ledger.

    This handler intentionally has no implementation, command-execution, Git
    mutation, or deployment action.  Proposal fields remain inert JSON.
    """
    action = arguments.get("action", "inspect")
    system = get_self_iteration_system()

    try:
        if action == "inspect":
            return _text(
                system.inspect(
                    path=arguments.get("path"),
                    include_files=arguments.get("include_files", False) is True,
                    file_limit=arguments.get("file_limit", 100),
                )
            )

        if action == "propose":
            claimed_source, used_legacy_source = _claimed_input(
                arguments,
                current="claimed_source",
                legacy="source",
                default="self_observation",
            )
            proposal = system.propose(
                observation=arguments.get("observation"),
                hypothesis=arguments.get("hypothesis"),
                expected_outcome=arguments.get("expected_outcome"),
                evidence=arguments.get("evidence"),
                target_paths=arguments.get("target_paths"),
                verification=arguments.get("verification"),
                rollback_plan=arguments.get("rollback_plan"),
                risk=arguments.get("risk", "medium"),
                claimed_source=claimed_source,
            )
            response = {
                "success": True,
                "proposal": proposal,
                "next_step": (
                    "A caretaker or isolated coding runner may implement this on a branch. "
                    "The running creature made no source changes."
                ),
            }
            if used_legacy_source:
                response["deprecated_fields"] = {"source": "claimed_source"}
            return _text(response)

        if action == "list":
            return _text(
                system.list_proposals(
                    limit=arguments.get("limit", 10),
                    status=arguments.get("status"),
                    proposal_id=arguments.get("proposal_id"),
                )
            )

        if action == "record_outcome":
            claimed_measurement_source, used_legacy_measurement_source = _claimed_input(
                arguments,
                current="claimed_measurement_source",
                legacy="measurement_source",
                default="self_observation",
            )
            proposal = system.record_outcome(
                proposal_id=arguments.get("proposal_id"),
                decision=arguments.get("decision"),
                observed_outcome=arguments.get("observed_outcome"),
                evidence=arguments.get("evidence"),
                implementation_ref=arguments.get("implementation_ref"),
                claimed_measurement_source=claimed_measurement_source,
            )
            response = {"success": True, "proposal": proposal}
            if used_legacy_measurement_source:
                response["deprecated_fields"] = {
                    "measurement_source": "claimed_measurement_source"
                }
            return _text(response)

        return _text(
            {
                "error": f"unknown self_iteration action: {action}",
                "allowed_actions": ["inspect", "propose", "list", "record_outcome"],
            }
        )
    except SelfIterationError as exc:
        return _text({"error": str(exc), "action": action})
    except Exception as exc:
        return _text(
            {
                "error": f"self-iteration operation failed: {exc}",
                "action": action,
                "source_changes_performed": False,
            }
        )


__all__ = ["handle_self_iteration"]
