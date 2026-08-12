"""Signed transient-canary protocol for externally supervised evaluation.

Anima can request one fixed canary evaluation over a local Unix socket. The
external supervisor owns activation, measurement, and baseline restoration.
This module exposes no shell, service-control, push, merge, or persistent
activation primitive.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import re
import socket
import stat
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from .self_iteration_verification import (
    SIGNATURE_ALGORITHM,
    VerificationError,
    VerifierKey,
    VerifierKeyProvider,
    canonical_json_bytes,
    parse_utc_timestamp,
)

CANARY_CONTRACT_SCHEMA = "anima.self_iteration.canary_contract.v1"
CANARY_PROFILE_SCHEMA = "anima.self_iteration.canary_profile.v1"
CANARY_SUPERVISOR_SCHEMA = "anima.self_iteration.canary_supervisor.v1"
CANARY_APPROVAL_SCHEMA = "anima.self_iteration.canary_approval.v1"
CANARY_REQUEST_SCHEMA = "anima.self_iteration.canary_request.v1"
CANARY_RESULT_SCHEMA = "anima.self_iteration.canary_result.v1"

CANARY_APPROVAL_DOMAIN = b"anima.self_iteration.canary_approval.v1\x00"
CANARY_RESULT_DOMAIN = b"anima.self_iteration.canary_result.v1\x00"
CANARY_VALIDITY = timedelta(minutes=10)

CANARY_SOCKET_ENV = "ANIMA_SELF_ITERATION_CANARY_SOCKET"
CANARY_SIGNER_ID_ENV = "ANIMA_SELF_ITERATION_CANARY_SUPERVISOR_SIGNER_ID"

MAX_CANARY_MESSAGE_BYTES = 1024 * 1024
CANARY_CONNECT_TIMEOUT_SECONDS = 5
CANARY_RESULT_TIMEOUT_SECONDS = 240

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OBJECT_ID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_CHALLENGE_ID_RE = re.compile(r"^sicc-[0-9a-f]{32}$")
_CANARY_ID_RE = re.compile(r"^sican-[0-9a-f]{32}$")
_RESULT_ID_RE = re.compile(r"^sicr-[0-9a-f]{32}$")


class CanaryError(ValueError):
    """Raised when a canary plan, result, or supervisor violates its contract."""


class CanarySupervisor(Protocol):
    def probe(self) -> dict[str, Any]: ...

    def evaluate(
        self,
        *,
        approval: dict[str, Any],
        approval_signature: str,
        requested_at: str,
    ) -> dict[str, Any]: ...


def canary_contract() -> dict[str, Any]:
    return {
        "schema": CANARY_CONTRACT_SCHEMA,
        "approval_schema": CANARY_APPROVAL_SCHEMA,
        "result_schema": CANARY_RESULT_SCHEMA,
        "transport": "local_unix_socket_only",
        "reviewed_application_required": True,
        "authenticated_distinct_canary_reviewer_required": True,
        "approval_validity_seconds": int(CANARY_VALIDITY.total_seconds()),
        "one_time_canary_claim_required": True,
        "fixed_profile_only": True,
        "external_supervisor_required": True,
        "dedicated_supervisor_result_signer_required": True,
        "transient_activation_only": True,
        "baseline_restore_required": True,
        "persistent_activation_allowed": False,
        "arbitrary_command_allowed": False,
        "shell_allowed": False,
        "service_control_allowed": False,
        "push_allowed": False,
        "merge_allowed": False,
        "deploy_allowed": False,
        "authority_granted": False,
    }


def canary_profile() -> dict[str, Any]:
    return {
        "schema": CANARY_PROFILE_SCHEMA,
        "profile_id": "lumen_transient_canary_v1",
        "observation_seconds": 120,
        "result_timeout_seconds": CANARY_RESULT_TIMEOUT_SECONDS,
        "activation_mode": "external_transient_candidate",
        "health_checks": [
            "mcp_health",
            "broker_state_freshness",
            "display_heartbeat",
        ],
        "baseline_restore_required": True,
        "retain_candidate_when_healthy": False,
        "persistent_activation_allowed": False,
        "caller_parameters_allowed": False,
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.lower()):
        raise CanaryError(f"{field} must be exactly 64 hexadecimal characters")
    return value.lower()


def _require_object_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _OBJECT_ID_RE.fullmatch(value.lower()):
        raise CanaryError(f"{field} is not a full Git object identifier")
    return value.lower()


def _identity(value: Any, field: str) -> dict[str, str | None]:
    if (
        not isinstance(value, dict)
        or set(value) != {"kind", "id", "issuer"}
        or not isinstance(value.get("kind"), str)
        or not isinstance(value.get("id"), str)
        or not value["id"].strip()
        or (
            value.get("issuer") is not None and not isinstance(value.get("issuer"), str)
        )
    ):
        raise CanaryError(f"{field} identity is malformed")
    return {
        "kind": value["kind"],
        "id": value["id"],
        "issuer": value.get("issuer"),
    }


def validate_supervisor_identity(value: Any) -> dict[str, Any]:
    required = {
        "schema",
        "backend",
        "protocol_version",
        "supervisor_id",
        "result_signer",
        "profile",
        "local_transport",
        "transient_activation_only",
        "baseline_restore_required",
        "persistent_activation_allowed",
        "arbitrary_command_allowed",
        "shell_allowed",
        "service_control_allowed",
        "push_allowed",
        "merge_allowed",
    }
    signer = value.get("result_signer") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("schema") != CANARY_SUPERVISOR_SCHEMA
        or value.get("backend") != "external_unix_socket_supervisor"
        or value.get("protocol_version") != 1
        or not isinstance(value.get("supervisor_id"), str)
        or not re.fullmatch(r"[A-Za-z0-9._:@/-]{1,300}", value["supervisor_id"])
        or not isinstance(signer, dict)
        or set(signer) != {"id", "key_id", "algorithm", "assurance"}
        or signer.get("id") != value.get("supervisor_id")
        or not isinstance(signer.get("key_id"), str)
        or not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", signer["key_id"])
        or signer.get("algorithm") != SIGNATURE_ALGORITHM
        or signer.get("assurance") != "symmetric_mac_server_verifiable"
        or value.get("profile") != canary_profile()
        or value.get("local_transport") != "unix_socket"
        or value.get("transient_activation_only") is not True
        or value.get("baseline_restore_required") is not True
        or value.get("persistent_activation_allowed") is not False
        or value.get("arbitrary_command_allowed") is not False
        or value.get("shell_allowed") is not False
        or value.get("service_control_allowed") is not False
        or value.get("push_allowed") is not False
        or value.get("merge_allowed") is not False
    ):
        raise CanaryError("canary supervisor identity is malformed")
    return copy.deepcopy(value)


def build_canary_approval(
    *,
    application_result: dict[str, Any],
    reviewer_identity: dict[str, Any],
    reviewer_key_id: str,
    supervisor_identity: dict[str, Any],
    issued_at: datetime,
) -> dict[str, Any]:
    if issued_at.tzinfo is None:
        raise CanaryError("canary approval time must be timezone-aware")
    result = copy.deepcopy(application_result)
    approval = result.get("approval") if isinstance(result, dict) else None
    if not isinstance(approval, dict):
        raise CanaryError("application result binding is malformed")
    if (
        result.get("eligible_for_canary_review") is not True
        or result.get("eligible_for_live_activation") is not False
        or result.get("branch_created") is not True
        or result.get("pushed") is not False
        or result.get("merged") is not False
        or result.get("deployed") is not False
        or result.get("authority_granted") is not False
    ):
        raise CanaryError("application result is not eligible for canary review")
    _require_sha256(result.get("result_sha256"), "application result")
    _require_object_id(result.get("parent_revision"), "canary baseline revision")
    _require_object_id(result.get("commit_oid"), "canary candidate commit")
    _require_object_id(result.get("tree_oid"), "canary candidate tree")
    if not isinstance(reviewer_key_id, str) or not re.fullmatch(
        r"[A-Za-z0-9._:-]{1,100}", reviewer_key_id
    ):
        raise CanaryError("canary reviewer key is malformed")
    issued = issued_at.astimezone(timezone.utc)
    record = {
        "schema": CANARY_APPROVAL_SCHEMA,
        "canary_id": f"sican-{uuid.uuid4().hex}",
        "challenge_id": f"sicc-{uuid.uuid4().hex}",
        "proposal_id": result["proposal_id"],
        "proposal_content_sha256": result["proposal_content_sha256"],
        "candidate_id": result["candidate_id"],
        "candidate_sha256": result["candidate_sha256"],
        "execution_id": result["execution_id"],
        "execution_result_sha256": result["execution_result_sha256"],
        "application_id": result["application_id"],
        "application_result_id": result["application_result_id"],
        "application_result_sha256": result["result_sha256"],
        "application_approval_sha256": result["application_approval_sha256"],
        "application_reviewer_identity": copy.deepcopy(approval["reviewer_identity"]),
        "application_result_signer_id": result["signature"]["signer_id"],
        "target_ref": result["target_ref"],
        "baseline_revision": result["parent_revision"],
        "candidate_commit_oid": result["commit_oid"],
        "candidate_tree_oid": result["tree_oid"],
        "reviewer_identity": _identity(reviewer_identity, "canary reviewer"),
        "reviewer_key_id": reviewer_key_id,
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "supervisor_identity": validate_supervisor_identity(supervisor_identity),
        "profile": canary_profile(),
        "issued_at": issued.isoformat().replace("+00:00", "Z"),
        "challenge_expires_at": (issued + CANARY_VALIDITY)
        .isoformat()
        .replace("+00:00", "Z"),
        "nonce": uuid.uuid4().hex,
        "transient_activation_only": True,
        "baseline_restore_required": True,
        "persistent_activation_allowed": False,
        "authority_granted": False,
    }
    validate_canary_approval(record)
    return record


def validate_canary_approval(value: Any) -> dict[str, Any]:
    required = {
        "schema",
        "canary_id",
        "challenge_id",
        "proposal_id",
        "proposal_content_sha256",
        "candidate_id",
        "candidate_sha256",
        "execution_id",
        "execution_result_sha256",
        "application_id",
        "application_result_id",
        "application_result_sha256",
        "application_approval_sha256",
        "application_reviewer_identity",
        "application_result_signer_id",
        "target_ref",
        "baseline_revision",
        "candidate_commit_oid",
        "candidate_tree_oid",
        "reviewer_identity",
        "reviewer_key_id",
        "signature_algorithm",
        "supervisor_identity",
        "profile",
        "issued_at",
        "challenge_expires_at",
        "nonce",
        "transient_activation_only",
        "baseline_restore_required",
        "persistent_activation_allowed",
        "authority_granted",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise CanaryError("canary approval fields are malformed")
    if (
        value.get("schema") != CANARY_APPROVAL_SCHEMA
        or not isinstance(value.get("canary_id"), str)
        or not _CANARY_ID_RE.fullmatch(value["canary_id"])
        or not isinstance(value.get("challenge_id"), str)
        or not _CHALLENGE_ID_RE.fullmatch(value["challenge_id"])
        or not isinstance(value.get("proposal_id"), str)
        or not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", value["proposal_id"])
        or not isinstance(value.get("candidate_id"), str)
        or not re.fullmatch(r"sip-[0-9a-f]{32}", value["candidate_id"])
        or not isinstance(value.get("execution_id"), str)
        or not re.fullmatch(r"six-[0-9a-f]{32}", value["execution_id"])
        or not isinstance(value.get("application_id"), str)
        or not re.fullmatch(r"siap-[0-9a-f]{32}", value["application_id"])
        or not isinstance(value.get("application_result_id"), str)
        or not re.fullmatch(r"siar-[0-9a-f]{32}", value["application_result_id"])
        or value.get("signature_algorithm") != SIGNATURE_ALGORITHM
        or value.get("profile") != canary_profile()
        or value.get("transient_activation_only") is not True
        or value.get("baseline_restore_required") is not True
        or value.get("persistent_activation_allowed") is not False
        or value.get("authority_granted") is not False
    ):
        raise CanaryError("canary approval identity or boundary is malformed")
    for field in (
        "proposal_content_sha256",
        "candidate_sha256",
        "execution_result_sha256",
        "application_result_sha256",
        "application_approval_sha256",
    ):
        _require_sha256(value.get(field), field)
    baseline = _require_object_id(value.get("baseline_revision"), "baseline revision")
    commit_oid = _require_object_id(
        value.get("candidate_commit_oid"), "candidate commit"
    )
    tree_oid = _require_object_id(value.get("candidate_tree_oid"), "candidate tree")
    if len({len(baseline), len(commit_oid), len(tree_oid)}) != 1:
        raise CanaryError("canary Git object formats are inconsistent")
    target_ref = value.get("target_ref")
    if target_ref != f"refs/heads/anima/self-iteration/{value['candidate_id']}":
        raise CanaryError("canary target ref is malformed")
    _identity(value.get("application_reviewer_identity"), "application reviewer")
    _identity(value.get("reviewer_identity"), "canary reviewer")
    if not isinstance(
        value.get("application_result_signer_id"), str
    ) or not re.fullmatch(
        r"[A-Za-z0-9._:@/-]{1,300}", value["application_result_signer_id"]
    ):
        raise CanaryError("application result signer is malformed")
    if not isinstance(value.get("reviewer_key_id"), str) or not re.fullmatch(
        r"[A-Za-z0-9._:-]{1,100}", value["reviewer_key_id"]
    ):
        raise CanaryError("canary reviewer key is malformed")
    supervisor = validate_supervisor_identity(value.get("supervisor_identity"))
    if supervisor["profile"] != value["profile"]:
        raise CanaryError("canary supervisor profile binding is malformed")
    try:
        issued = parse_utc_timestamp(value.get("issued_at"), "issued_at")
        expires = parse_utc_timestamp(
            value.get("challenge_expires_at"), "challenge_expires_at"
        )
    except VerificationError as exc:
        raise CanaryError(str(exc)) from exc
    if expires - issued != CANARY_VALIDITY:
        raise CanaryError("canary approval validity is malformed")
    if not isinstance(value.get("nonce"), str) or not re.fullmatch(
        r"[0-9a-f]{32}", value["nonce"]
    ):
        raise CanaryError("canary approval nonce is malformed")
    return copy.deepcopy(value)


def canary_approval_sha256(approval: dict[str, Any]) -> str:
    return _sha256(canonical_json_bytes(validate_canary_approval(approval)))


def canary_signing_input_b64(approval: dict[str, Any]) -> str:
    payload = CANARY_APPROVAL_DOMAIN + canonical_json_bytes(
        validate_canary_approval(approval)
    )
    return base64.urlsafe_b64encode(payload).decode("ascii")


def sign_canary_approval(approval: dict[str, Any], key: VerifierKey) -> str:
    validated = validate_canary_approval(approval)
    if (
        key.verifier_id != validated["reviewer_identity"]["id"]
        or key.key_id != validated["reviewer_key_id"]
    ):
        raise CanaryError("canary signing key does not match its approval")
    return hmac.new(
        key.secret,
        CANARY_APPROVAL_DOMAIN + canonical_json_bytes(validated),
        hashlib.sha256,
    ).hexdigest()


def verify_canary_approval_signature(
    approval: dict[str, Any], signature: Any, key: VerifierKey
) -> bool:
    if not isinstance(signature, str) or not _SHA256_RE.fullmatch(signature):
        return False
    try:
        expected = sign_canary_approval(approval, key)
    except CanaryError:
        return False
    return hmac.compare_digest(expected, signature)


def canary_signature_record(approval: dict[str, Any], signature: Any) -> dict[str, str]:
    validated = validate_canary_approval(approval)
    if not isinstance(signature, str) or not _SHA256_RE.fullmatch(signature):
        raise CanaryError("canary approval signature is malformed")
    return {
        "algorithm": SIGNATURE_ALGORITHM,
        "reviewer_id": validated["reviewer_identity"]["id"],
        "key_id": validated["reviewer_key_id"],
        "value": signature,
        "assurance": "symmetric_mac_server_verifiable",
    }


def build_canary_request(
    *, approval: dict[str, Any], approval_signature: str, requested_at: str
) -> dict[str, Any]:
    validated = validate_canary_approval(approval)
    try:
        requested = parse_utc_timestamp(requested_at, "requested_at")
        issued = parse_utc_timestamp(validated["issued_at"], "issued_at")
        expires = parse_utc_timestamp(
            validated["challenge_expires_at"], "challenge_expires_at"
        )
    except VerificationError as exc:
        raise CanaryError(str(exc)) from exc
    if requested < issued or requested > expires:
        raise CanaryError("canary request is outside its approval window")
    record = {
        "schema": CANARY_REQUEST_SCHEMA,
        "action": "evaluate_transient_canary",
        "approval": copy.deepcopy(validated),
        "approval_signature": canary_signature_record(validated, approval_signature),
        "requested_at": requested_at,
        "persistent_activation_allowed": False,
        "authority_granted": False,
    }
    record["request_sha256"] = _sha256(canonical_json_bytes(record))
    return record


def validate_canary_request(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "action",
        "approval",
        "approval_signature",
        "requested_at",
        "persistent_activation_allowed",
        "authority_granted",
        "request_sha256",
    }:
        raise CanaryError("canary request fields are malformed")
    raw_signature = value.get("approval_signature")
    if not isinstance(raw_signature, dict):
        raise CanaryError("canary request approval signature is malformed")
    signature_value = raw_signature.get("value")
    if not isinstance(signature_value, str):
        raise CanaryError("canary request approval signature is malformed")
    unsigned = copy.deepcopy(value)
    digest = unsigned.pop("request_sha256")
    rebuilt = build_canary_request(
        approval=unsigned["approval"],
        approval_signature=signature_value,
        requested_at=unsigned["requested_at"],
    )
    if (
        value.get("schema") != CANARY_REQUEST_SCHEMA
        or value.get("action") != "evaluate_transient_canary"
        or value.get("persistent_activation_allowed") is not False
        or value.get("authority_granted") is not False
        or digest != rebuilt["request_sha256"]
        or value != rebuilt
    ):
        raise CanaryError("canary request binding is malformed")
    return copy.deepcopy(value)


def _validate_health_checks(value: Any, *, outcome: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise CanaryError("canary health checks are malformed")
    allowed_names = canary_profile()["health_checks"]
    names: list[str] = []
    checks: list[dict[str, Any]] = []
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item)
            != {"name", "status", "duration_ms", "evidence_sha256", "summary"}
            or item.get("name") not in allowed_names
            or item.get("status") not in {"passed", "failed", "error", "timed_out"}
            or isinstance(item.get("duration_ms"), bool)
            or not isinstance(item.get("duration_ms"), int)
            or not 0 <= item["duration_ms"] <= CANARY_RESULT_TIMEOUT_SECONDS * 1000
            or not isinstance(item.get("summary"), str)
            or not item["summary"]
            or len(item["summary"]) > 500
        ):
            raise CanaryError("canary health check is malformed")
        _require_sha256(item.get("evidence_sha256"), "canary health evidence")
        names.append(item["name"])
        checks.append(copy.deepcopy(item))
    if len(names) != len(set(names)):
        raise CanaryError("canary health checks are duplicated")
    if outcome == "passed" and (
        sorted(names) != sorted(allowed_names)
        or any(item["status"] != "passed" for item in checks)
    ):
        raise CanaryError("passing canary lacks all passing health checks")
    return checks


def validate_canary_result_shape(value: Any) -> dict[str, Any]:
    required = {
        "schema",
        "canary_result_id",
        "approval",
        "approval_signature",
        "request_sha256",
        "canary_id",
        "challenge_id",
        "proposal_id",
        "candidate_id",
        "application_result_id",
        "application_result_sha256",
        "supervisor_identity",
        "profile",
        "target_ref",
        "baseline_revision",
        "candidate_commit_oid",
        "started_at",
        "finished_at",
        "outcome",
        "activation_performed",
        "health_checks",
        "baseline_restore_attempted",
        "baseline_restored",
        "live_revision_after",
        "persistent_activation_retained",
        "recommended_decision",
        "eligible_for_merge_review",
        "eligible_for_live_activation",
        "authority_granted",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise CanaryError("canary result fields are malformed")
    approval = validate_canary_approval(value.get("approval"))
    _require_sha256(value.get("request_sha256"), "canary request")
    raw_signature = value.get("approval_signature")
    signature_value = (
        raw_signature.get("value") if isinstance(raw_signature, dict) else None
    )
    outcome = value.get("outcome")
    if outcome not in {
        "passed",
        "failed",
        "activation_failed",
        "timed_out",
        "supervisor_error",
        "rollback_failed",
    }:
        raise CanaryError("canary outcome is malformed")
    checks = _validate_health_checks(value.get("health_checks"), outcome=outcome)
    activation_performed = value.get("activation_performed")
    restore_attempted = value.get("baseline_restore_attempted")
    baseline_restored = value.get("baseline_restored")
    if (
        value.get("schema") != CANARY_RESULT_SCHEMA
        or not isinstance(value.get("canary_result_id"), str)
        or not _RESULT_ID_RE.fullmatch(value["canary_result_id"])
        or raw_signature != canary_signature_record(approval, signature_value)
        or value.get("canary_id") != approval["canary_id"]
        or value.get("challenge_id") != approval["challenge_id"]
        or value.get("proposal_id") != approval["proposal_id"]
        or value.get("candidate_id") != approval["candidate_id"]
        or value.get("application_result_id") != approval["application_result_id"]
        or value.get("application_result_sha256")
        != approval["application_result_sha256"]
        or value.get("supervisor_identity") != approval["supervisor_identity"]
        or value.get("profile") != approval["profile"]
        or value.get("target_ref") != approval["target_ref"]
        or value.get("baseline_revision") != approval["baseline_revision"]
        or value.get("candidate_commit_oid") != approval["candidate_commit_oid"]
        or not isinstance(activation_performed, bool)
        or not isinstance(restore_attempted, bool)
        or not isinstance(baseline_restored, bool)
        or value.get("persistent_activation_retained") is not False
        or value.get("eligible_for_live_activation") is not False
        or value.get("authority_granted") is not False
    ):
        raise CanaryError("canary result violates its containment contract")
    expected_decision = (
        "keep_candidate_for_merge_review"
        if outcome == "passed" and baseline_restored
        else (
            "operator_recovery_required"
            if outcome == "rollback_failed" or not baseline_restored
            else "reject_candidate"
        )
    )
    eligible = outcome == "passed" and baseline_restored
    if (
        value.get("recommended_decision") != expected_decision
        or value.get("eligible_for_merge_review") is not eligible
        or (
            outcome in {"passed", "failed", "timed_out", "rollback_failed"}
            and activation_performed is not True
        )
        or (outcome == "activation_failed" and activation_performed is not False)
        or (activation_performed and restore_attempted is not True)
        or (
            outcome == "rollback_failed"
            and (restore_attempted is not True or baseline_restored is not False)
        )
        or (
            activation_performed
            and outcome != "rollback_failed"
            and baseline_restored is not True
        )
        or (
            outcome in {"failed", "timed_out"}
            and (not checks or all(item["status"] == "passed" for item in checks))
        )
        or (eligible and (restore_attempted is not True or not checks))
    ):
        raise CanaryError("canary result decision or rollback binding is malformed")
    live_after = value.get("live_revision_after")
    if live_after is not None:
        _require_object_id(live_after, "post-canary live revision")
    if baseline_restored and live_after != approval["baseline_revision"]:
        raise CanaryError("restored canary does not report the baseline revision")
    try:
        started = parse_utc_timestamp(value.get("started_at"), "started_at")
        finished = parse_utc_timestamp(value.get("finished_at"), "finished_at")
        issued = parse_utc_timestamp(approval["issued_at"], "issued_at")
        expires = parse_utc_timestamp(
            approval["challenge_expires_at"], "challenge_expires_at"
        )
    except VerificationError as exc:
        raise CanaryError(str(exc)) from exc
    if (
        started < issued
        or started > expires + timedelta(seconds=30)
        or finished < started
        or finished - started > timedelta(seconds=CANARY_RESULT_TIMEOUT_SECONDS)
    ):
        raise CanaryError("canary result timestamps are malformed")
    return copy.deepcopy(value)


def build_signed_canary_result(
    *,
    request: dict[str, Any],
    supervisor_receipt: dict[str, Any],
    signer_key: VerifierKey,
) -> dict[str, Any]:
    validated_request = validate_canary_request(request)
    approval = validated_request["approval"]
    signer = approval["supervisor_identity"]["result_signer"]
    if signer_key.verifier_id != signer["id"] or signer_key.key_id != signer["key_id"]:
        raise CanaryError("canary result signer does not match its approval")
    expected_receipt = {
        "started_at",
        "finished_at",
        "outcome",
        "activation_performed",
        "health_checks",
        "baseline_restore_attempted",
        "baseline_restored",
        "live_revision_after",
    }
    if (
        not isinstance(supervisor_receipt, dict)
        or set(supervisor_receipt) != expected_receipt
    ):
        raise CanaryError("canary supervisor receipt is malformed")
    outcome = supervisor_receipt["outcome"]
    baseline_restored = supervisor_receipt["baseline_restored"] is True
    record = {
        "schema": CANARY_RESULT_SCHEMA,
        "canary_result_id": f"sicr-{uuid.uuid4().hex}",
        "approval": copy.deepcopy(approval),
        "approval_signature": copy.deepcopy(validated_request["approval_signature"]),
        "request_sha256": validated_request["request_sha256"],
        "canary_id": approval["canary_id"],
        "challenge_id": approval["challenge_id"],
        "proposal_id": approval["proposal_id"],
        "candidate_id": approval["candidate_id"],
        "application_result_id": approval["application_result_id"],
        "application_result_sha256": approval["application_result_sha256"],
        "supervisor_identity": copy.deepcopy(approval["supervisor_identity"]),
        "profile": copy.deepcopy(approval["profile"]),
        "target_ref": approval["target_ref"],
        "baseline_revision": approval["baseline_revision"],
        "candidate_commit_oid": approval["candidate_commit_oid"],
        "started_at": supervisor_receipt.get("started_at"),
        "finished_at": supervisor_receipt.get("finished_at"),
        "outcome": outcome,
        "activation_performed": supervisor_receipt.get("activation_performed"),
        "health_checks": copy.deepcopy(supervisor_receipt.get("health_checks")),
        "baseline_restore_attempted": supervisor_receipt.get(
            "baseline_restore_attempted"
        ),
        "baseline_restored": baseline_restored,
        "live_revision_after": supervisor_receipt.get("live_revision_after"),
        "persistent_activation_retained": False,
        "recommended_decision": (
            "keep_candidate_for_merge_review"
            if outcome == "passed" and baseline_restored
            else (
                "operator_recovery_required"
                if outcome == "rollback_failed" or not baseline_restored
                else "reject_candidate"
            )
        ),
        "eligible_for_merge_review": outcome == "passed" and baseline_restored,
        "eligible_for_live_activation": False,
        "authority_granted": False,
    }
    validate_canary_result_shape(record)
    record["result_sha256"] = _sha256(canonical_json_bytes(record))
    payload = canonical_json_bytes(record)
    record["signature"] = {
        "algorithm": SIGNATURE_ALGORITHM,
        "signer_id": signer_key.verifier_id,
        "key_id": signer_key.key_id,
        "value": hmac.new(
            signer_key.secret,
            CANARY_RESULT_DOMAIN + payload,
            hashlib.sha256,
        ).hexdigest(),
        "assurance": "symmetric_mac_server_verifiable",
    }
    return record


def validate_signed_canary_result(
    value: Any, key_provider: VerifierKeyProvider
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        *_canary_result_shape_fields(),
        "result_sha256",
        "signature",
    }:
        raise CanaryError("signed canary result fields are malformed")
    unsigned = copy.deepcopy(value)
    signature = unsigned.pop("signature")
    result_digest = unsigned.pop("result_sha256")
    validate_canary_result_shape(unsigned)
    _require_sha256(result_digest, "canary result")
    if result_digest != _sha256(canonical_json_bytes(unsigned)):
        raise CanaryError("canary result digest is invalid")
    approval = unsigned["approval"]
    approval_signature = unsigned["approval_signature"]
    try:
        reviewer_key = key_provider(
            approval_signature["reviewer_id"], approval_signature["key_id"]
        )
    except Exception as exc:
        raise CanaryError("canary reviewer key registry is unavailable") from exc
    if not isinstance(
        reviewer_key, VerifierKey
    ) or not verify_canary_approval_signature(
        approval, approval_signature["value"], reviewer_key
    ):
        raise CanaryError("recorded canary approval signature is invalid")
    if (
        not isinstance(signature, dict)
        or set(signature) != {"algorithm", "signer_id", "key_id", "value", "assurance"}
        or signature.get("algorithm") != SIGNATURE_ALGORITHM
        or signature.get("assurance") != "symmetric_mac_server_verifiable"
        or not isinstance(signature.get("value"), str)
        or not _SHA256_RE.fullmatch(signature["value"])
    ):
        raise CanaryError("canary result signature is malformed")
    expected_signer = approval["supervisor_identity"]["result_signer"]
    if (
        signature.get("signer_id") != expected_signer["id"]
        or signature.get("key_id") != expected_signer["key_id"]
    ):
        raise CanaryError("canary result signer does not match its approval")
    try:
        signer_key = key_provider(signature["signer_id"], signature["key_id"])
    except Exception as exc:
        raise CanaryError("canary result signing key registry is unavailable") from exc
    if (
        not isinstance(signer_key, VerifierKey)
        or signer_key.verifier_id != signature["signer_id"]
        or signer_key.key_id != signature["key_id"]
    ):
        raise CanaryError("canary result signing key is unavailable")
    expected = hmac.new(
        signer_key.secret,
        CANARY_RESULT_DOMAIN
        + canonical_json_bytes({**unsigned, "result_sha256": result_digest}),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature["value"]):
        raise CanaryError("canary result signature is invalid")
    return copy.deepcopy(value)


def _canary_result_shape_fields() -> set[str]:
    return {
        "schema",
        "canary_result_id",
        "approval",
        "approval_signature",
        "request_sha256",
        "canary_id",
        "challenge_id",
        "proposal_id",
        "candidate_id",
        "application_result_id",
        "application_result_sha256",
        "supervisor_identity",
        "profile",
        "target_ref",
        "baseline_revision",
        "candidate_commit_oid",
        "started_at",
        "finished_at",
        "outcome",
        "activation_performed",
        "health_checks",
        "baseline_restore_attempted",
        "baseline_restored",
        "live_revision_after",
        "persistent_activation_retained",
        "recommended_decision",
        "eligible_for_merge_review",
        "eligible_for_live_activation",
        "authority_granted",
    }


class UnixSocketCanarySupervisor:
    """Fixed JSON-lines client for a separately managed local supervisor."""

    def __init__(self, socket_path: str | None) -> None:
        self.socket_path = socket_path

    @classmethod
    def from_environment(cls) -> UnixSocketCanarySupervisor:
        return cls(os.environ.get(CANARY_SOCKET_ENV))

    def _path(self) -> Path:
        if not isinstance(self.socket_path, str) or not self.socket_path:
            raise CanaryError(
                f"{CANARY_SOCKET_ENV} must name an absolute local Unix socket"
            )
        raw = Path(self.socket_path)
        if not raw.is_absolute() or raw.is_symlink():
            raise CanaryError(
                "canary supervisor socket must be absolute and not a symlink"
            )
        try:
            metadata = raw.stat()
            resolved = raw.resolve(strict=True)
        except OSError as exc:
            raise CanaryError("canary supervisor socket is unavailable") from exc
        if not stat.S_ISSOCK(metadata.st_mode) or resolved != raw:
            raise CanaryError("canary supervisor path is not an exact Unix socket")
        return resolved

    def _call(self, request: dict[str, Any], *, timeout: int) -> dict[str, Any]:
        payload = canonical_json_bytes(request) + b"\n"
        if len(payload) > MAX_CANARY_MESSAGE_BYTES:
            raise CanaryError("canary supervisor request exceeds its size limit")
        path = self._path()
        response = bytearray()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(CANARY_CONNECT_TIMEOUT_SECONDS)
                client.connect(str(path))
                client.sendall(payload)
                client.settimeout(timeout)
                while True:
                    chunk = client.recv(65536)
                    if not chunk:
                        break
                    response.extend(chunk)
                    if len(response) > MAX_CANARY_MESSAGE_BYTES:
                        raise CanaryError(
                            "canary supervisor response exceeds its size limit"
                        )
                    if b"\n" in chunk:
                        break
        except (OSError, socket.timeout) as exc:
            raise CanaryError("canary supervisor request failed") from exc
        line, separator, remainder = bytes(response).partition(b"\n")
        if not separator or remainder or not line:
            raise CanaryError("canary supervisor response framing is malformed")
        try:
            decoded = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CanaryError("canary supervisor response is malformed") from exc
        if not isinstance(decoded, dict):
            raise CanaryError("canary supervisor response is malformed")
        return decoded

    def probe(self) -> dict[str, Any]:
        response = self._call(
            {
                "schema": CANARY_REQUEST_SCHEMA,
                "action": "probe",
                "profile": canary_profile(),
                "persistent_activation_allowed": False,
            },
            timeout=CANARY_CONNECT_TIMEOUT_SECONDS,
        )
        if (
            set(response) != {"schema", "ok", "identity"}
            or response.get("schema") != "anima.self_iteration.canary_probe_response.v1"
            or response.get("ok") is not True
        ):
            raise CanaryError("canary supervisor probe response is malformed")
        return validate_supervisor_identity(response.get("identity"))

    def evaluate(
        self,
        *,
        approval: dict[str, Any],
        approval_signature: str,
        requested_at: str,
    ) -> dict[str, Any]:
        request = build_canary_request(
            approval=approval,
            approval_signature=approval_signature,
            requested_at=requested_at,
        )
        response = self._call(request, timeout=CANARY_RESULT_TIMEOUT_SECONDS)
        if (
            set(response) != {"schema", "ok", "result"}
            or response.get("schema")
            != "anima.self_iteration.canary_evaluation_response.v1"
            or response.get("ok") is not True
        ):
            raise CanaryError("canary supervisor evaluation response is malformed")
        result = response.get("result")
        if not isinstance(result, dict):
            raise CanaryError("canary supervisor result is malformed")
        return result


__all__ = [
    "CANARY_SIGNER_ID_ENV",
    "CANARY_SOCKET_ENV",
    "CANARY_VALIDITY",
    "CanaryError",
    "CanarySupervisor",
    "UnixSocketCanarySupervisor",
    "build_canary_approval",
    "build_canary_request",
    "build_signed_canary_result",
    "canary_approval_sha256",
    "canary_contract",
    "canary_profile",
    "canary_signature_record",
    "canary_signing_input_b64",
    "sign_canary_approval",
    "validate_canary_approval",
    "validate_canary_request",
    "validate_signed_canary_result",
    "validate_supervisor_identity",
    "verify_canary_approval_signature",
]
