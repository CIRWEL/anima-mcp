"""Externally approved candidate execution in a fail-closed Docker boundary.

Candidate code is never evaluated in the Anima server process.  This module
materializes a clean, read-only repository snapshot in a temporary directory
and invokes a locally available, digest-pinned container image with a fixed
test profile.  There is deliberately no host-execution fallback, caller-
supplied command, image pull/build path, source apply path, or Git mutation.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import re
import signal
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Protocol

from .self_iteration_verification import (
    SIGNATURE_ALGORITHM,
    VerificationError,
    VerifierKey,
    VerifierKeyProvider,
    canonical_json_bytes,
    parse_utc_timestamp,
)

EXECUTION_CONTRACT_SCHEMA = "anima.self_iteration.execution_contract.v1"
EXECUTION_APPROVAL_SCHEMA = "anima.self_iteration.execution_approval.v1"
EXECUTION_RESULT_SCHEMA = "anima.self_iteration.execution_result.v1"
EXECUTION_PROFILE_SCHEMA = "anima.self_iteration.execution_profile.v1"
EXECUTION_RUNNER_SCHEMA = "anima.self_iteration.docker_runner.v1"

APPROVAL_DOMAIN = b"anima.self_iteration.execution_approval.v1\x00"
RESULT_DOMAIN = b"anima.self_iteration.execution_result.v1\x00"
APPROVAL_VALIDITY = timedelta(minutes=10)

RUNNER_IMAGE_ENV = "ANIMA_SELF_ITERATION_RUNNER_IMAGE"
RUNNER_DOCKER_SOCKET_ENV = "ANIMA_SELF_ITERATION_DOCKER_SOCKET"
RUNNER_DOCKER_BINARY_ENV = "ANIMA_SELF_ITERATION_DOCKER_BINARY"
RUNNER_SIGNER_ID_ENV = "ANIMA_SELF_ITERATION_RUNNER_SIGNER_ID"

MAX_TRACKED_FILE_BYTES = 8 * 1024 * 1024
MAX_TRACKED_TOTAL_BYTES = 64 * 1024 * 1024
MAX_TRACKED_FILES = 10_000
MAX_CAPTURE_BYTES = 64 * 1024
MAX_CONTROL_OUTPUT_BYTES = 256 * 1024
MAX_CONTROL_STREAM_BYTES = 1024 * 1024

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,400}@sha256:[0-9a-f]{64}$")
_CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_CHALLENGE_ID_RE = re.compile(r"^sixc-[0-9a-f]{32}$")
_APPROVAL_ID_RE = re.compile(r"^sixa-[0-9a-f]{32}$")
_EXECUTION_ID_RE = re.compile(r"^six-[0-9a-f]{32}$")
_ATTESTATION_ID_RE = re.compile(r"^sia-[0-9a-f]{32}$")
_EVALUATION_ID_RE = re.compile(r"^sie-[0-9a-f]{32}$")


class ExecutionError(ValueError):
    """Raised when approval, isolation, or signed-result validation fails."""


@dataclass(frozen=True)
class ExecutionProfile:
    """One server-owned command and its immutable resource envelope."""

    profile_id: str
    version: int
    allowed_path_prefix: str
    entrypoint: str
    arguments: tuple[str, ...]
    timeout_seconds: int
    memory_bytes: int
    cpus: float
    pids_limit: int
    nofile_limit: int
    tmpfs_bytes: int
    max_output_bytes: int
    max_stream_bytes: int

    def supports(self, paths: list[str]) -> bool:
        return bool(paths) and all(
            path.startswith(self.allowed_path_prefix)
            and path.endswith(".py")
            and "/" not in path[len(self.allowed_path_prefix) :]
            for path in paths
        )

    def public_record(self) -> dict[str, Any]:
        return {
            "schema": EXECUTION_PROFILE_SCHEMA,
            "profile_id": self.profile_id,
            "version": self.version,
            "allowed_path_prefix": self.allowed_path_prefix,
            "entrypoint": self.entrypoint,
            "arguments": list(self.arguments),
            "resources": {
                "timeout_seconds": self.timeout_seconds,
                "memory_bytes": self.memory_bytes,
                "cpus": self.cpus,
                "pids_limit": self.pids_limit,
                "nofile_limit": self.nofile_limit,
                "tmpfs_bytes": self.tmpfs_bytes,
                "max_output_bytes": self.max_output_bytes,
                "max_stream_bytes": self.max_stream_bytes,
            },
            "caller_supplied_command_allowed": False,
        }


DISPLAY_ERA_TEST_PROFILE = ExecutionProfile(
    profile_id="display_era_pytest_v1",
    version=1,
    allowed_path_prefix="src/anima_mcp/display/eras/",
    entrypoint="/usr/local/bin/python",
    arguments=(
        "-m",
        "pytest",
        "-q",
        "--disable-warnings",
        "--maxfail=1",
        "-p",
        "no:cacheprovider",
        "tests/test_art_era.py",
        "tests/test_era_registry.py",
        "tests/test_gestural_era.py",
        "tests/test_resonance_era.py",
        "tests/test_drawing_earned_completion.py",
    ),
    timeout_seconds=180,
    memory_bytes=512 * 1024 * 1024,
    cpus=1.0,
    pids_limit=128,
    nofile_limit=256,
    tmpfs_bytes=64 * 1024 * 1024,
    max_output_bytes=MAX_CAPTURE_BYTES,
    max_stream_bytes=4 * 1024 * 1024,
)

EXECUTION_PROFILES = {DISPLAY_ERA_TEST_PROFILE.profile_id: DISPLAY_ERA_TEST_PROFILE}


def execution_profile(profile_id: Any) -> ExecutionProfile:
    if not isinstance(profile_id, str) or profile_id not in EXECUTION_PROFILES:
        raise ExecutionError(
            "execution_profile must be one of: " + ", ".join(sorted(EXECUTION_PROFILES))
        )
    return EXECUTION_PROFILES[profile_id]


def execution_contract() -> dict[str, Any]:
    """Return the public, immutable Phase 4 boundary."""
    return {
        "schema": EXECUTION_CONTRACT_SCHEMA,
        "approval_schema": EXECUTION_APPROVAL_SCHEMA,
        "result_schema": EXECUTION_RESULT_SCHEMA,
        "backend": "docker_local_digest_pinned",
        "host_execution_fallback": False,
        "image_pull_or_build_allowed": False,
        "caller_supplied_image_allowed": False,
        "caller_supplied_command_allowed": False,
        "clean_committed_source_required": True,
        "passing_recorded_static_evaluation_required": True,
        "authenticated_external_approver_required": True,
        "approver_must_differ_from_proposer": True,
        "approver_must_differ_from_active_verifiers": True,
        "approval_signature_algorithm": SIGNATURE_ALGORITHM,
        "approval_validity_seconds": int(APPROVAL_VALIDITY.total_seconds()),
        "dedicated_result_signer_required": True,
        "result_signature_algorithm": SIGNATURE_ALGORITHM,
        "one_time_execution_claim_required": True,
        "network_mode": "none",
        "root_filesystem_read_only": True,
        "source_mount_read_only": True,
        "capabilities_dropped": "all",
        "no_new_privileges": True,
        "secrets_forwarded": False,
        "profiles": [
            EXECUTION_PROFILES[key].public_record()
            for key in sorted(EXECUTION_PROFILES)
        ],
        "live_source_writes": False,
        "git_mutations": False,
        "automatic_apply": False,
        "automatic_merge": False,
        "automatic_deploy": False,
        "authority_granted": False,
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.lower()):
        raise ExecutionError(f"{field} must be exactly 64 hexadecimal characters")
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
        raise ExecutionError(f"{field} identity is malformed")
    return {
        "kind": value["kind"],
        "id": value["id"],
        "issuer": value.get("issuer"),
    }


def _source_fingerprint(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {
        "revision",
        "manifest_sha256",
    }:
        raise ExecutionError("execution proposal source fingerprint is malformed")
    revision = value.get("revision")
    if not isinstance(revision, str) or not re.fullmatch(
        r"[0-9a-f]{40,64}", revision.lower()
    ):
        raise ExecutionError(
            "isolated execution requires a full committed source revision"
        )
    return {
        "revision": revision.lower(),
        "manifest_sha256": _require_sha256(
            value.get("manifest_sha256"), "source_fingerprint.manifest_sha256"
        ),
    }


def _profile_digest(profile: ExecutionProfile) -> str:
    return _sha256(canonical_json_bytes(profile.public_record()))


def _runner_contract() -> dict[str, Any]:
    return {
        "schema": EXECUTION_RUNNER_SCHEMA,
        "backend": "docker",
        "local_unix_socket_required": True,
        "image_reference_digest_required": True,
        "pull_policy": "never",
        "network": "none",
        "root_read_only": True,
        "source_read_only": True,
        "tmpfs_only_writable_runtime": True,
        "declared_image_volumes_allowed": False,
        "healthcheck": "disabled",
        "container_environment": "server_owned_allowlist",
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges=true"],
        "ipc": "none",
        "cgroup_namespace": "private",
        "user": "65534:65534",
        "secrets_forwarded": False,
        "docker_socket_mounted": False,
        "host_pid_namespace": False,
        "host_network_namespace": False,
        "host_execution_fallback": False,
    }


def isolation_contract_sha256() -> str:
    """Return the digest bound into runner identities and result records."""
    return _sha256(canonical_json_bytes(_runner_contract()))


def build_execution_approval(
    *,
    proposal_id: str,
    proposal_content_sha256: str,
    source_fingerprint: dict[str, Any],
    active_attestation_ids: list[str],
    candidate_id: str,
    candidate_sha256: str,
    evaluation_id: str,
    evaluation_sha256: str,
    approver_identity: dict[str, Any],
    approval_key_id: str,
    runner_identity: dict[str, Any],
    profile: ExecutionProfile,
    source_snapshot: dict[str, Any],
    result_signer_id: str,
    result_signer_key_id: str,
    issued_at: datetime,
) -> dict[str, Any]:
    """Build the canonical plan an external approver must sign."""
    if issued_at.tzinfo is None:
        raise ExecutionError("execution approval time must be timezone-aware")
    issued = issued_at.astimezone(timezone.utc)
    challenge_id = f"sixc-{uuid.uuid4().hex}"
    approval_id = f"sixa-{uuid.uuid4().hex}"
    approval = {
        "schema": EXECUTION_APPROVAL_SCHEMA,
        "approval_id": approval_id,
        "challenge_id": challenge_id,
        "proposal_id": proposal_id,
        "proposal_content_sha256": _require_sha256(
            proposal_content_sha256, "proposal_content_sha256"
        ),
        "source_fingerprint": _source_fingerprint(source_fingerprint),
        "active_attestation_ids": sorted(active_attestation_ids),
        "candidate_id": candidate_id,
        "candidate_sha256": _require_sha256(candidate_sha256, "candidate_sha256"),
        "evaluation_id": evaluation_id,
        "evaluation_sha256": _require_sha256(evaluation_sha256, "evaluation_sha256"),
        "approver_identity": _identity(approver_identity, "approver"),
        "approval_key_id": approval_key_id,
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "runner_identity": copy.deepcopy(runner_identity),
        "runner_contract_sha256": _sha256(canonical_json_bytes(_runner_contract())),
        "profile": profile.public_record(),
        "profile_sha256": _profile_digest(profile),
        "source_snapshot": copy.deepcopy(source_snapshot),
        "result_signer": {
            "id": result_signer_id,
            "key_id": result_signer_key_id,
            "algorithm": SIGNATURE_ALGORITHM,
            "assurance": "symmetric_mac_server_verifiable",
        },
        "issued_at": issued.isoformat().replace("+00:00", "Z"),
        "challenge_expires_at": (issued + APPROVAL_VALIDITY)
        .isoformat()
        .replace("+00:00", "Z"),
        "nonce": uuid.uuid4().hex,
        "execution_claims_authority": False,
    }
    validate_execution_approval(approval)
    return approval


def execution_approval_sha256(approval: dict[str, Any]) -> str:
    """Digest one fully validated, unsigned execution approval plan."""
    validated = validate_execution_approval(approval)
    return _sha256(canonical_json_bytes(validated))


def validate_execution_approval(value: Any) -> dict[str, Any]:
    required = {
        "schema",
        "approval_id",
        "challenge_id",
        "proposal_id",
        "proposal_content_sha256",
        "source_fingerprint",
        "active_attestation_ids",
        "candidate_id",
        "candidate_sha256",
        "evaluation_id",
        "evaluation_sha256",
        "approver_identity",
        "approval_key_id",
        "signature_algorithm",
        "runner_identity",
        "runner_contract_sha256",
        "profile",
        "profile_sha256",
        "source_snapshot",
        "result_signer",
        "issued_at",
        "challenge_expires_at",
        "nonce",
        "execution_claims_authority",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ExecutionError("execution approval fields are malformed")
    if value.get("schema") != EXECUTION_APPROVAL_SCHEMA:
        raise ExecutionError("execution approval schema is malformed")
    if not isinstance(value.get("approval_id"), str) or not _APPROVAL_ID_RE.fullmatch(
        value["approval_id"]
    ):
        raise ExecutionError("execution approval identifier is malformed")
    if not isinstance(value.get("challenge_id"), str) or not _CHALLENGE_ID_RE.fullmatch(
        value["challenge_id"]
    ):
        raise ExecutionError("execution challenge identifier is malformed")
    if not isinstance(value.get("proposal_id"), str) or not re.fullmatch(
        r"[A-Za-z0-9._:-]{1,100}", value["proposal_id"]
    ):
        raise ExecutionError("execution approval proposal is malformed")
    _require_sha256(value.get("proposal_content_sha256"), "proposal_content_sha256")
    _require_sha256(value.get("candidate_sha256"), "candidate_sha256")
    _require_sha256(value.get("evaluation_sha256"), "evaluation_sha256")
    _require_sha256(value.get("runner_contract_sha256"), "runner_contract_sha256")
    _require_sha256(value.get("profile_sha256"), "profile_sha256")
    if value.get("runner_contract_sha256") != _sha256(
        canonical_json_bytes(_runner_contract())
    ):
        raise ExecutionError("execution runner contract binding is malformed")
    if not isinstance(value.get("candidate_id"), str) or not re.fullmatch(
        r"sip-[0-9a-f]{32}", value["candidate_id"]
    ):
        raise ExecutionError("execution candidate identifier is malformed")
    if not isinstance(
        value.get("evaluation_id"), str
    ) or not _EVALUATION_ID_RE.fullmatch(value["evaluation_id"]):
        raise ExecutionError("execution evaluation identifier is malformed")
    attestation_ids = value.get("active_attestation_ids")
    if (
        not isinstance(attestation_ids, list)
        or not attestation_ids
        or attestation_ids != sorted(attestation_ids)
        or len(set(attestation_ids)) != len(attestation_ids)
        or any(
            not isinstance(item, str) or not _ATTESTATION_ID_RE.fullmatch(item)
            for item in attestation_ids
        )
    ):
        raise ExecutionError("execution attestation binding is malformed")
    _identity(value.get("approver_identity"), "approver")
    if (
        not isinstance(value.get("approval_key_id"), str)
        or not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", value["approval_key_id"])
        or value.get("signature_algorithm") != SIGNATURE_ALGORITHM
    ):
        raise ExecutionError("execution approval signing configuration is malformed")
    fingerprint = _source_fingerprint(value.get("source_fingerprint"))
    profile_record = value.get("profile")
    if not isinstance(profile_record, dict):
        raise ExecutionError("execution profile is malformed")
    profile = execution_profile(profile_record.get("profile_id"))
    if profile_record != profile.public_record() or value.get(
        "profile_sha256"
    ) != _profile_digest(profile):
        raise ExecutionError("execution profile binding is malformed")
    validate_runner_identity(value.get("runner_identity"))
    snapshot = validate_source_snapshot(value.get("source_snapshot"))
    if snapshot["revision"] != fingerprint["revision"] or not profile.supports(
        snapshot["candidate_paths"]
    ):
        raise ExecutionError("execution source snapshot is outside its fixed profile")
    result_signer = value.get("result_signer")
    if (
        not isinstance(result_signer, dict)
        or set(result_signer) != {"id", "key_id", "algorithm", "assurance"}
        or not isinstance(result_signer.get("id"), str)
        or not re.fullmatch(r"[A-Za-z0-9._:@/-]{1,300}", result_signer["id"])
        or not isinstance(result_signer.get("key_id"), str)
        or not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", result_signer["key_id"])
        or result_signer.get("algorithm") != SIGNATURE_ALGORITHM
        or result_signer.get("assurance") != "symmetric_mac_server_verifiable"
    ):
        raise ExecutionError("execution result signer binding is malformed")
    try:
        issued = parse_utc_timestamp(value.get("issued_at"), "issued_at")
        expires = parse_utc_timestamp(
            value.get("challenge_expires_at"), "challenge_expires_at"
        )
    except VerificationError as exc:
        raise ExecutionError(str(exc)) from exc
    if expires - issued != APPROVAL_VALIDITY:
        raise ExecutionError("execution approval validity window is malformed")
    if not isinstance(value.get("nonce"), str) or not re.fullmatch(
        r"[0-9a-f]{32}", value["nonce"]
    ):
        raise ExecutionError("execution approval nonce is malformed")
    if value.get("execution_claims_authority") is not False:
        raise ExecutionError("execution approval grants forbidden authority")
    return copy.deepcopy(value)


def approval_signing_input_b64(approval: dict[str, Any]) -> str:
    validate_execution_approval(approval)
    payload = APPROVAL_DOMAIN + canonical_json_bytes(approval)
    return base64.urlsafe_b64encode(payload).decode("ascii")


def sign_execution_approval(approval: dict[str, Any], key: VerifierKey) -> str:
    validate_execution_approval(approval)
    if (
        key.verifier_id != approval["approver_identity"]["id"]
        or key.key_id != approval["approval_key_id"]
    ):
        raise ExecutionError("execution approval signing key does not match its plan")
    return hmac.new(
        key.secret,
        APPROVAL_DOMAIN + canonical_json_bytes(approval),
        hashlib.sha256,
    ).hexdigest()


def verify_execution_approval_signature(
    approval: dict[str, Any], signature: str, key: VerifierKey
) -> bool:
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        return False
    approver_identity = approval.get("approver_identity")
    if (
        not isinstance(approver_identity, dict)
        or key.verifier_id != approver_identity.get("id")
        or key.key_id != approval.get("approval_key_id")
    ):
        return False
    expected = sign_execution_approval(approval, key)
    return hmac.compare_digest(expected, signature)


def approval_signature_record(
    approval: dict[str, Any], signature: Any
) -> dict[str, str]:
    """Build the durable public record of an approver's verified MAC."""
    validate_execution_approval(approval)
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise ExecutionError("execution approval signature is malformed")
    return {
        "algorithm": SIGNATURE_ALGORITHM,
        "approver_id": approval["approver_identity"]["id"],
        "key_id": approval["approval_key_id"],
        "value": signature,
        "assurance": "symmetric_mac_server_verifiable",
    }


def validate_runner_identity(value: Any) -> dict[str, Any]:
    required = {
        "schema",
        "backend",
        "image_reference",
        "image_id",
        "repo_digest",
        "os",
        "architecture",
        "declared_volumes",
        "healthcheck_policy",
        "runner_contract_sha256",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("schema") != EXECUTION_RUNNER_SCHEMA
        or value.get("backend") != "docker"
        or not isinstance(value.get("image_reference"), str)
        or not _IMAGE_RE.fullmatch(value["image_reference"])
        or value.get("repo_digest") != value.get("image_reference")
        or not isinstance(value.get("image_id"), str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", value["image_id"])
        or value.get("os") != "linux"
        or not isinstance(value.get("architecture"), str)
        or not value["architecture"]
        or value.get("declared_volumes") != []
        or value.get("healthcheck_policy") != "disabled"
        or value.get("runner_contract_sha256")
        != _sha256(canonical_json_bytes(_runner_contract()))
    ):
        raise ExecutionError("Docker runner identity is malformed")
    return copy.deepcopy(value)


def validate_source_snapshot(value: Any) -> dict[str, Any]:
    required = {
        "revision",
        "tracked_file_count",
        "tracked_total_bytes",
        "baseline_tree_sha256",
        "candidate_tree_sha256",
        "candidate_paths",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or not isinstance(value.get("revision"), str)
        or not re.fullmatch(r"[0-9a-f]{40,64}", value["revision"])
        or isinstance(value.get("tracked_file_count"), bool)
        or not isinstance(value.get("tracked_file_count"), int)
        or not 1 <= value["tracked_file_count"] <= MAX_TRACKED_FILES
        or isinstance(value.get("tracked_total_bytes"), bool)
        or not isinstance(value.get("tracked_total_bytes"), int)
        or not 0 < value["tracked_total_bytes"] <= MAX_TRACKED_TOTAL_BYTES
    ):
        raise ExecutionError("execution source snapshot is malformed")
    _require_sha256(value.get("baseline_tree_sha256"), "baseline_tree_sha256")
    _require_sha256(value.get("candidate_tree_sha256"), "candidate_tree_sha256")
    paths = value.get("candidate_paths")
    if (
        not isinstance(paths, list)
        or not paths
        or paths != sorted(paths)
        or len(set(paths)) != len(paths)
        or any(
            not isinstance(path, str) or _normalize_tracked_path(path) != path
            for path in paths
        )
    ):
        raise ExecutionError("execution candidate path snapshot is malformed")
    return copy.deepcopy(value)


@dataclass(frozen=True)
class CapturedProcess:
    returncode: int | None
    timed_out: bool
    output_limit_exceeded: bool
    stdout: str
    stderr: str
    stdout_bytes: int
    stderr_bytes: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_truncated: bool
    stderr_truncated: bool


class IsolationRunner(Protocol):
    def probe(self) -> dict[str, Any]: ...

    def run(
        self,
        *,
        workspace: Path,
        profile: ExecutionProfile,
        expected_identity: dict[str, Any],
    ) -> dict[str, Any]: ...


def _decode_capture(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _run_bounded_process(
    command: list[str],
    *,
    timeout: int,
    capture_limit: int,
    output_limit: int,
    environment: dict[str, str],
) -> CapturedProcess:
    """Run a trusted host control command while bounding untrusted output."""
    if capture_limit < 0 or output_limit < capture_limit:
        raise ExecutionError("process output limits are malformed")
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            start_new_session=True,
        )
    except OSError as exc:
        raise ExecutionError("Docker control process could not be started") from exc
    captures: dict[str, dict[str, Any]] = {}
    output_limit_reached = threading.Event()
    total_lock = threading.Lock()
    combined_total = 0

    def drain(name: str, stream: Any) -> None:
        nonlocal combined_total
        digest = hashlib.sha256()
        kept = bytearray()
        total = 0
        while True:
            if output_limit_reached.is_set():
                break
            chunk = stream.read(8192)
            if not chunk:
                break
            with total_lock:
                remaining_output = output_limit - combined_total
                accepted = chunk[: max(0, remaining_output)]
                combined_total += len(accepted)
                if len(accepted) < len(chunk):
                    output_limit_reached.set()
            digest.update(accepted)
            total += len(accepted)
            remaining = capture_limit - len(kept)
            if remaining > 0:
                kept.extend(accepted[:remaining])
            if len(accepted) < len(chunk):
                break
        captures[name] = {
            "kept": bytes(kept),
            "total": total,
            "sha256": digest.hexdigest(),
        }

    assert process.stdout is not None
    assert process.stderr is not None
    threads = [
        threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    timed_out = False
    output_limited = False
    deadline = time.monotonic() + timeout
    returncode: int | None = None
    while returncode is None:
        returncode = process.poll()
        if returncode is not None:
            break
        if output_limit_reached.wait(timeout=0.05):
            output_limited = True
            break
        if time.monotonic() >= deadline:
            timed_out = True
            break
    if timed_out or output_limited:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            process.kill()
        returncode = None
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise ExecutionError("Docker control process did not terminate") from exc
    for thread in threads:
        thread.join(timeout=5)
    if any(thread.is_alive() for thread in threads):
        raise ExecutionError("Docker output capture did not terminate cleanly")
    output_limited = output_limited or output_limit_reached.is_set()
    stdout = captures["stdout"]
    stderr = captures["stderr"]
    return CapturedProcess(
        returncode=returncode,
        timed_out=timed_out,
        output_limit_exceeded=output_limited,
        stdout=_decode_capture(stdout["kept"]),
        stderr=_decode_capture(stderr["kept"]),
        stdout_bytes=stdout["total"],
        stderr_bytes=stderr["total"],
        stdout_sha256=stdout["sha256"],
        stderr_sha256=stderr["sha256"],
        stdout_truncated=output_limited or stdout["total"] > len(stdout["kept"]),
        stderr_truncated=output_limited or stderr["total"] > len(stderr["kept"]),
    )


class DockerIsolationRunner:
    """Invoke only a local digest-pinned image with a fixed Docker envelope."""

    def __init__(
        self,
        *,
        image_reference: str | None,
        docker_socket: str,
        docker_binary: str | None = None,
        socket_check: bool = True,
        process_runner: Callable[..., CapturedProcess] = _run_bounded_process,
    ) -> None:
        self.image_reference = image_reference
        self.docker_socket = docker_socket
        self.docker_binary = docker_binary
        self.socket_check = socket_check
        self._process_runner = process_runner

    @classmethod
    def from_environment(cls) -> DockerIsolationRunner:
        return cls(
            image_reference=os.environ.get(RUNNER_IMAGE_ENV),
            docker_socket=os.environ.get(
                RUNNER_DOCKER_SOCKET_ENV, "/var/run/docker.sock"
            ),
            docker_binary=os.environ.get(RUNNER_DOCKER_BINARY_ENV),
        )

    def _binary(self) -> str:
        configured = self.docker_binary
        if configured is not None:
            path = Path(configured)
            if not path.is_absolute():
                raise ExecutionError(
                    f"{RUNNER_DOCKER_BINARY_ENV} must be an absolute path"
                )
            resolved = path.resolve(strict=False)
            if not resolved.is_file() or not os.access(resolved, os.X_OK):
                raise ExecutionError("configured Docker binary is unavailable")
            return str(resolved)
        discovered = shutil.which("docker")
        if not discovered:
            raise ExecutionError("Docker CLI is unavailable; execution is disabled")
        return str(Path(discovered).resolve())

    def _socket_uri(self) -> str:
        raw = self.docker_socket
        path_text = raw[7:] if raw.startswith("unix://") else raw
        path = Path(path_text)
        if not path.is_absolute() or "\x00" in path_text:
            raise ExecutionError("Docker socket must be an absolute local Unix socket")
        if self.socket_check:
            try:
                mode = path.stat().st_mode
            except OSError as exc:
                raise ExecutionError(
                    "local Docker socket is unavailable; execution is disabled"
                ) from exc
            if not stat.S_ISSOCK(mode):
                raise ExecutionError("configured Docker endpoint is not a Unix socket")
        return f"unix://{path}"

    @staticmethod
    def _environment() -> dict[str, str]:
        return {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        }

    def _base_command(self) -> list[str]:
        return [self._binary(), "--host", self._socket_uri()]

    def _control(self, arguments: list[str], *, timeout: int = 15) -> CapturedProcess:
        result = self._process_runner(
            [*self._base_command(), *arguments],
            timeout=timeout,
            capture_limit=MAX_CONTROL_OUTPUT_BYTES,
            output_limit=MAX_CONTROL_STREAM_BYTES,
            environment=self._environment(),
        )
        if result.timed_out or result.output_limit_exceeded:
            raise ExecutionError("Docker control command exceeded its resource limit")
        return result

    def probe(self) -> dict[str, Any]:
        image = self.image_reference
        if not isinstance(image, str) or not _IMAGE_RE.fullmatch(image):
            raise ExecutionError(
                f"{RUNNER_IMAGE_ENV} must name a digest-pinned local image"
            )
        result = self._control(["image", "inspect", image])
        if result.returncode != 0:
            raise ExecutionError(
                "digest-pinned runner image is not locally available; pulling is disabled"
            )
        try:
            records = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ExecutionError(
                "Docker image inspection returned malformed JSON"
            ) from exc
        if not isinstance(records, list) or len(records) != 1:
            raise ExecutionError("Docker image inspection returned an ambiguous result")
        record = records[0]
        repo_digests = record.get("RepoDigests") if isinstance(record, dict) else None
        config = record.get("Config") if isinstance(record, dict) else None
        if not isinstance(config, dict):
            raise ExecutionError("Docker image inspection omitted its configuration")
        volumes = config.get("Volumes")
        if volumes is not None and volumes != {}:
            raise ExecutionError(
                "Docker runner image declares writable volumes; execution is disabled"
            )
        identity = {
            "schema": EXECUTION_RUNNER_SCHEMA,
            "backend": "docker",
            "image_reference": image,
            "image_id": record.get("Id") if isinstance(record, dict) else None,
            "repo_digest": (
                image
                if isinstance(repo_digests, list) and image in repo_digests
                else None
            ),
            "os": record.get("Os") if isinstance(record, dict) else None,
            "architecture": (
                record.get("Architecture") if isinstance(record, dict) else None
            ),
            "declared_volumes": [],
            "healthcheck_policy": "disabled",
            "runner_contract_sha256": _sha256(canonical_json_bytes(_runner_contract())),
        }
        return validate_runner_identity(identity)

    def build_create_command(
        self,
        *,
        workspace: Path,
        profile: ExecutionProfile,
        image_identity: dict[str, Any],
        container_name: str,
    ) -> list[str]:
        identity = validate_runner_identity(image_identity)
        resolved_workspace = workspace.resolve(strict=True)
        if (
            not resolved_workspace.is_dir()
            or "," in str(resolved_workspace)
            or "\n" in str(resolved_workspace)
        ):
            raise ExecutionError("execution workspace path is not mount-safe")
        if not re.fullmatch(r"anima-si-[0-9a-f]{24}", container_name):
            raise ExecutionError("generated container name is malformed")
        memory = str(profile.memory_bytes)
        tmpfs = "rw,noexec,nosuid,nodev,mode=1777,size=" + str(profile.tmpfs_bytes)
        return [
            *self._base_command(),
            "create",
            "--pull=never",
            "--name",
            container_name,
            "--hostname",
            "anima-candidate",
            "--network=none",
            "--ipc=none",
            "--cgroupns=private",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges=true",
            "--user=65534:65534",
            "--workdir=/workspace",
            "--memory=" + memory,
            "--memory-swap=" + memory,
            "--cpus=" + str(profile.cpus),
            "--pids-limit=" + str(profile.pids_limit),
            "--ulimit=nofile="
            + str(profile.nofile_limit)
            + ":"
            + str(profile.nofile_limit),
            "--ulimit=nproc=" + str(profile.pids_limit) + ":" + str(profile.pids_limit),
            "--ulimit=core=0:0",
            "--stop-timeout=1",
            "--log-driver=none",
            "--no-healthcheck",
            "--tmpfs=/tmp:" + tmpfs,
            "--mount=type=bind,src="
            + str(resolved_workspace)
            + ",dst=/workspace,readonly",
            "--env=HOME=/tmp",
            "--env=TMPDIR=/tmp",
            "--env=PATH=/usr/local/bin:/usr/bin:/bin",
            "--env=LANG=C.UTF-8",
            "--env=LC_ALL=C.UTF-8",
            "--env=PYTHONDONTWRITEBYTECODE=1",
            "--env=PYTHONHASHSEED=0",
            "--env=PYTHONPATH=/workspace/src",
            "--env=NO_PROXY=*",
            "--entrypoint=" + profile.entrypoint,
            identity["image_reference"],
            *profile.arguments,
        ]

    def run(
        self,
        *,
        workspace: Path,
        profile: ExecutionProfile,
        expected_identity: dict[str, Any],
    ) -> dict[str, Any]:
        current_identity = self.probe()
        if current_identity != validate_runner_identity(expected_identity):
            raise ExecutionError("Docker runner identity changed after approval")
        container_name = f"anima-si-{uuid.uuid4().hex[:24]}"
        container_id: str | None = None
        cleanup_reference: str | None = None
        capture: CapturedProcess | None = None
        state: dict[str, Any] = {}
        cleanup_error: str | None = None
        inspect_error = False
        started_at = time.monotonic()
        try:
            create_command = self.build_create_command(
                workspace=workspace,
                profile=profile,
                image_identity=current_identity,
                container_name=container_name,
            )
            cleanup_reference = container_name
            created = self._process_runner(
                create_command,
                timeout=30,
                capture_limit=MAX_CONTROL_OUTPUT_BYTES,
                output_limit=MAX_CONTROL_STREAM_BYTES,
                environment=self._environment(),
            )
            if created.timed_out or created.output_limit_exceeded:
                raise ExecutionError(
                    "Docker container creation exceeded its resource limit"
                )
            if created.returncode != 0:
                raise ExecutionError("Docker refused to create the isolated container")
            raw_container_id = created.stdout.strip()
            if not _CONTAINER_ID_RE.fullmatch(raw_container_id):
                raise ExecutionError("Docker returned a malformed container identifier")
            container_id = raw_container_id
            cleanup_reference = container_id
            capture = self._process_runner(
                [*self._base_command(), "start", "--attach", container_id],
                timeout=profile.timeout_seconds,
                capture_limit=profile.max_output_bytes,
                output_limit=profile.max_stream_bytes,
                environment=self._environment(),
            )
            try:
                inspected = self._control(
                    ["container", "inspect", container_id], timeout=10
                )
            except ExecutionError:
                inspect_error = True
            else:
                if inspected.returncode == 0:
                    try:
                        records = json.loads(inspected.stdout)
                    except json.JSONDecodeError:
                        records = []
                    if isinstance(records, list) and len(records) == 1:
                        raw_state = records[0].get("State")
                        if isinstance(raw_state, dict):
                            state = raw_state
                else:
                    inspect_error = True
        finally:
            if cleanup_reference is not None:
                try:
                    removed = self._control(
                        ["container", "rm", "--force", cleanup_reference], timeout=10
                    )
                except ExecutionError:
                    cleanup_error = "Docker could not confirm container removal"
                else:
                    if removed.returncode != 0:
                        cleanup_error = "Docker could not confirm container removal"
        duration_ms = int((time.monotonic() - started_at) * 1000)
        assert capture is not None
        started = bool(
            isinstance(state.get("StartedAt"), str)
            and not state["StartedAt"].startswith("0001-01-01")
        )
        exit_code = state.get("ExitCode")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            exit_code = None
        if inspect_error or cleanup_error or not started:
            outcome = "runner_error"
        elif capture.output_limit_exceeded:
            outcome = "output_limit_exceeded"
        elif capture.timed_out:
            outcome = "timed_out"
        elif exit_code is None:
            outcome = "runner_error"
        elif exit_code == 0:
            outcome = "passed"
        else:
            outcome = "failed"
        return {
            "outcome": outcome,
            "container_started": started,
            "timed_out": capture.timed_out,
            "output_limit_exceeded": capture.output_limit_exceeded,
            "exit_code": exit_code,
            "oom_killed": state.get("OOMKilled") is True,
            "duration_ms": duration_ms,
            "stdout": {
                "captured": capture.stdout,
                "bytes": capture.stdout_bytes,
                "sha256": capture.stdout_sha256,
                "truncated": capture.stdout_truncated,
            },
            "stderr": {
                "captured": capture.stderr,
                "bytes": capture.stderr_bytes,
                "sha256": capture.stderr_sha256,
                "truncated": capture.stderr_truncated,
            },
            "cleanup_confirmed": cleanup_error is None,
            "runner_identity": current_identity,
            "isolation_contract_sha256": _sha256(
                canonical_json_bytes(_runner_contract())
            ),
        }


def _normalize_tracked_path(value: str) -> str:
    raw = value.replace("\\", "/")
    if (
        not raw
        or "\x00" in raw
        or raw.startswith("/")
        or any(part in {"", ".", ".."} for part in raw.split("/"))
    ):
        raise ExecutionError("Git returned an unsafe tracked path")
    return str(PurePosixPath(raw))


class SourceWorkspaceBuilder:
    """Build an ephemeral snapshot from a clean tracked worktree."""

    @staticmethod
    def _git(
        repo_root: Path, *arguments: str, input_bytes: bytes | None = None
    ) -> bytes:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_root), *arguments],
                stdin=subprocess.DEVNULL if input_bytes is None else None,
                input=input_bytes,
                capture_output=True,
                timeout=15,
                check=False,
                env={
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                },
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExecutionError("Git source snapshot is unavailable") from exc
        if result.returncode != 0:
            raise ExecutionError("Git source snapshot command failed")
        return result.stdout

    def _tracked(
        self,
        *,
        repo_root: Path,
        expected_revision: str,
    ) -> list[tuple[str, Path, bytes]]:
        root = repo_root.resolve(strict=True)
        revision = self._git(root, "rev-parse", "HEAD").decode().strip().lower()
        if revision != expected_revision.lower():
            raise ExecutionError("source revision changed after execution approval")
        status_output = self._git(
            root, "status", "--porcelain", "--untracked-files=normal", "-z"
        )
        if status_output:
            raise ExecutionError("isolated execution requires a clean source worktree")
        raw_entries = self._git(root, "ls-tree", "-rz", "--full-tree", revision).split(
            b"\x00"
        )
        entries: list[tuple[str, str]] = []
        for raw_entry in raw_entries:
            if not raw_entry:
                continue
            try:
                header, raw_path = raw_entry.split(b"\t", 1)
                mode, object_type, object_id = header.decode("ascii").split(" ")
                relative = _normalize_tracked_path(raw_path.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ExecutionError("Git returned a malformed tree entry") from exc
            if (
                mode not in {"100644", "100755"}
                or object_type != "blob"
                or not re.fullmatch(r"[0-9a-f]{40,64}", object_id)
            ):
                raise ExecutionError(
                    f"tracked source must contain regular files only: {relative}"
                )
            entries.append((relative, object_id))
        if not 1 <= len(entries) <= MAX_TRACKED_FILES:
            raise ExecutionError(
                "tracked source file count exceeds the execution limit"
            )
        if len({relative for relative, _object_id in entries}) != len(entries):
            raise ExecutionError("Git returned duplicate tracked paths")

        object_input = b"".join(
            object_id.encode("ascii") + b"\n" for _relative, object_id in entries
        )
        check_output = self._git(
            root,
            "cat-file",
            "--batch-check=%(objectname) %(objecttype) %(objectsize)",
            input_bytes=object_input,
        ).splitlines()
        if len(check_output) != len(entries):
            raise ExecutionError("Git object size inspection is incomplete")
        sizes: list[int] = []
        total = 0
        for (relative, expected_id), raw_check in zip(
            entries, check_output, strict=True
        ):
            try:
                object_id, object_type, raw_size = raw_check.decode("ascii").split(" ")
                size = int(raw_size)
            except (UnicodeDecodeError, ValueError) as exc:
                raise ExecutionError("Git object size inspection is malformed") from exc
            if object_id != expected_id or object_type != "blob" or size < 0:
                raise ExecutionError("Git object identity changed during inspection")
            if size > MAX_TRACKED_FILE_BYTES:
                raise ExecutionError(
                    f"tracked source file exceeds the execution limit: {relative}"
                )
            total += size
            if total > MAX_TRACKED_TOTAL_BYTES:
                raise ExecutionError("tracked source exceeds the execution size limit")
            sizes.append(size)

        batch = self._git(root, "cat-file", "--batch", input_bytes=object_input)
        records: list[tuple[str, Path, bytes]] = []
        offset = 0
        for (relative, expected_id), expected_size in zip(entries, sizes, strict=True):
            newline = batch.find(b"\n", offset)
            if newline < 0:
                raise ExecutionError("Git object stream is truncated")
            try:
                object_id, object_type, raw_size = (
                    batch[offset:newline].decode("ascii").split(" ")
                )
                size = int(raw_size)
            except (UnicodeDecodeError, ValueError) as exc:
                raise ExecutionError("Git object stream header is malformed") from exc
            start = newline + 1
            end = start + size
            if (
                object_id != expected_id
                or object_type != "blob"
                or size != expected_size
                or end >= len(batch)
                or batch[end : end + 1] != b"\n"
            ):
                raise ExecutionError("Git object stream binding is malformed")
            records.append((relative, root / relative, batch[start:end]))
            offset = end + 1
        if offset != len(batch):
            raise ExecutionError("Git object stream contains trailing data")
        final_revision = self._git(root, "rev-parse", "HEAD").decode().strip().lower()
        final_status = self._git(
            root, "status", "--porcelain", "--untracked-files=normal", "-z"
        )
        if final_revision != revision or final_status:
            raise ExecutionError("source changed while its execution snapshot was read")
        return records

    @staticmethod
    def _fingerprint_records(
        records: list[tuple[str, Path, bytes]],
        *,
        expected_revision: str,
        candidate_manifest: dict[str, Any],
        candidate_contents: dict[str, bytes],
    ) -> dict[str, Any]:
        candidate_metadata = {
            item["path"]: item
            for item in candidate_manifest.get("files", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        if (
            not isinstance(candidate_manifest.get("files"), list)
            or len(candidate_metadata) != len(candidate_manifest["files"])
            or set(candidate_metadata) != set(candidate_contents)
        ):
            raise ExecutionError("candidate execution material is inconsistent")
        baseline = hashlib.sha256()
        candidate = hashlib.sha256()
        total = 0
        tracked_paths: set[str] = set()
        for relative, _path, data in records:
            tracked_paths.add(relative)
            total += len(data)
            base_digest = _sha256(data)
            replacement = candidate_contents.get(relative)
            if replacement is not None:
                metadata = candidate_metadata[relative]
                if metadata.get("base_sha256") != base_digest:
                    raise ExecutionError(f"candidate base digest is stale: {relative}")
                candidate_digest = _sha256(replacement)
                if metadata.get("candidate_sha256") != candidate_digest:
                    raise ExecutionError(
                        f"candidate replacement digest is malformed: {relative}"
                    )
            else:
                candidate_digest = base_digest
            for digest, selected in (
                (baseline, base_digest),
                (candidate, candidate_digest),
            ):
                digest.update(relative.encode("utf-8"))
                digest.update(b"\x00")
                digest.update(selected.encode("ascii"))
                digest.update(b"\n")
        if set(candidate_contents) - tracked_paths:
            raise ExecutionError(
                "candidate target is not tracked in the approved revision"
            )
        snapshot = {
            "revision": expected_revision.lower(),
            "tracked_file_count": len(records),
            "tracked_total_bytes": total,
            "baseline_tree_sha256": baseline.hexdigest(),
            "candidate_tree_sha256": candidate.hexdigest(),
            "candidate_paths": sorted(candidate_contents),
        }
        return validate_source_snapshot(snapshot)

    def fingerprint(
        self,
        *,
        repo_root: Path,
        expected_revision: str,
        candidate_manifest: dict[str, Any],
        candidate_contents: dict[str, bytes],
    ) -> dict[str, Any]:
        records = self._tracked(
            repo_root=repo_root, expected_revision=expected_revision
        )
        return self._fingerprint_records(
            records,
            expected_revision=expected_revision,
            candidate_manifest=candidate_manifest,
            candidate_contents=candidate_contents,
        )

    @contextmanager
    def materialize(
        self,
        *,
        repo_root: Path,
        expected_revision: str,
        candidate_manifest: dict[str, Any],
        candidate_contents: dict[str, bytes],
        expected_snapshot: dict[str, Any],
    ) -> Iterator[Path]:
        records = self._tracked(
            repo_root=repo_root, expected_revision=expected_revision
        )
        snapshot = self._fingerprint_records(
            records,
            expected_revision=expected_revision,
            candidate_manifest=candidate_manifest,
            candidate_contents=candidate_contents,
        )
        if snapshot != validate_source_snapshot(expected_snapshot):
            raise ExecutionError("source snapshot changed after execution approval")
        temporary = Path(tempfile.mkdtemp(prefix="anima-self-iteration-exec-"))
        workspace = temporary / "workspace"
        try:
            workspace.mkdir(mode=0o755)
            for relative, _path, data in records:
                destination = workspace / relative
                destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                destination.write_bytes(candidate_contents.get(relative, data))
            for path in sorted(
                workspace.rglob("*"), key=lambda item: len(item.parts), reverse=True
            ):
                path.chmod(0o555 if path.is_dir() else 0o444)
            workspace.chmod(0o555)
            temporary.chmod(0o755)
            yield workspace
        finally:
            if temporary.exists() and temporary.name.startswith(
                "anima-self-iteration-exec-"
            ):
                for path in temporary.rglob("*"):
                    try:
                        path.chmod(0o700 if path.is_dir() else 0o600)
                    except OSError:
                        pass
                shutil.rmtree(temporary, ignore_errors=True)


def build_signed_execution_result(
    *,
    approval: dict[str, Any],
    approval_signature: str,
    approval_key: VerifierKey,
    runner_receipt: dict[str, Any],
    started_at: str,
    finished_at: str,
    signer_key: VerifierKey,
) -> dict[str, Any]:
    validate_execution_approval(approval)
    if (
        approval_key.verifier_id != approval["approver_identity"]["id"]
        or approval_key.key_id != approval["approval_key_id"]
        or not verify_execution_approval_signature(
            approval, approval_signature, approval_key
        )
    ):
        raise ExecutionError("execution result received an invalid approval signature")
    expected_signer = approval["result_signer"]
    if (
        signer_key.verifier_id != expected_signer["id"]
        or signer_key.key_id != expected_signer["key_id"]
    ):
        raise ExecutionError("execution result signer does not match its approval")
    runner_identity = validate_runner_identity(runner_receipt.get("runner_identity"))
    if runner_identity != approval["runner_identity"]:
        raise ExecutionError("execution result runner does not match its approval")
    execution_id = f"six-{uuid.uuid4().hex}"
    outcome = runner_receipt.get("outcome")
    if outcome not in {
        "passed",
        "failed",
        "timed_out",
        "output_limit_exceeded",
        "runner_error",
    }:
        raise ExecutionError("isolated runner returned an unsupported outcome")
    record: dict[str, Any] = {
        "schema": EXECUTION_RESULT_SCHEMA,
        "execution_id": execution_id,
        "approval": copy.deepcopy(approval),
        "approval_signature": approval_signature_record(approval, approval_signature),
        "approval_id": approval["approval_id"],
        "approval_sha256": execution_approval_sha256(approval),
        "challenge_id": approval["challenge_id"],
        "proposal_id": approval["proposal_id"],
        "proposal_content_sha256": approval["proposal_content_sha256"],
        "candidate_id": approval["candidate_id"],
        "candidate_sha256": approval["candidate_sha256"],
        "evaluation_id": approval["evaluation_id"],
        "evaluation_sha256": approval["evaluation_sha256"],
        "source_snapshot": copy.deepcopy(approval["source_snapshot"]),
        "profile": copy.deepcopy(approval["profile"]),
        "runner_identity": runner_identity,
        "isolation_contract_sha256": runner_receipt.get("isolation_contract_sha256"),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": runner_receipt.get("duration_ms"),
        "outcome": outcome,
        "container_started": runner_receipt.get("container_started") is True,
        "timed_out": runner_receipt.get("timed_out") is True,
        "output_limit_exceeded": runner_receipt.get("output_limit_exceeded") is True,
        "exit_code": runner_receipt.get("exit_code"),
        "oom_killed": runner_receipt.get("oom_killed") is True,
        "stdout": copy.deepcopy(runner_receipt.get("stdout")),
        "stderr": copy.deepcopy(runner_receipt.get("stderr")),
        "cleanup_confirmed": runner_receipt.get("cleanup_confirmed") is True,
        "isolated_execution": True,
        "execution_performed": runner_receipt.get("container_started") is True,
        "tests_executed": runner_receipt.get("container_started") is True,
        "live_source_writes": False,
        "eligible_for_external_review": outcome == "passed",
        "eligible_for_apply": False,
        "authority_granted": False,
    }
    _validate_unsigned_result(record)
    record["result_sha256"] = _sha256(canonical_json_bytes(record))
    signed_payload = canonical_json_bytes(record)
    record["signature"] = {
        "algorithm": SIGNATURE_ALGORITHM,
        "signer_id": signer_key.verifier_id,
        "key_id": signer_key.key_id,
        "value": hmac.new(
            signer_key.secret,
            RESULT_DOMAIN + signed_payload,
            hashlib.sha256,
        ).hexdigest(),
        "assurance": "symmetric_mac_server_verifiable",
    }
    return record


def _validate_output(value: Any, field: str) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {"captured", "bytes", "sha256", "truncated"}
        or not isinstance(value.get("captured"), str)
        or len(value["captured"].encode("utf-8")) > MAX_CAPTURE_BYTES * 3
        or isinstance(value.get("bytes"), bool)
        or not isinstance(value.get("bytes"), int)
        or value["bytes"] < 0
        or not isinstance(value.get("truncated"), bool)
    ):
        raise ExecutionError(f"execution {field} capture is malformed")
    if (
        len(value["captured"].encode("utf-8"))
        > min(value["bytes"], MAX_CAPTURE_BYTES) * 3
    ):
        raise ExecutionError(f"execution {field} capture exceeds its byte count")
    _require_sha256(value.get("sha256"), f"{field}.sha256")
    if value["bytes"] == 0 and (
        value["captured"] != "" or value["sha256"] != hashlib.sha256(b"").hexdigest()
    ):
        raise ExecutionError(f"execution {field} empty capture is inconsistent")


def _validate_unsigned_result(record: Any) -> None:
    required = {
        "schema",
        "execution_id",
        "approval",
        "approval_signature",
        "approval_id",
        "approval_sha256",
        "challenge_id",
        "proposal_id",
        "proposal_content_sha256",
        "candidate_id",
        "candidate_sha256",
        "evaluation_id",
        "evaluation_sha256",
        "source_snapshot",
        "profile",
        "runner_identity",
        "isolation_contract_sha256",
        "started_at",
        "finished_at",
        "duration_ms",
        "outcome",
        "container_started",
        "timed_out",
        "output_limit_exceeded",
        "exit_code",
        "oom_killed",
        "stdout",
        "stderr",
        "cleanup_confirmed",
        "isolated_execution",
        "execution_performed",
        "tests_executed",
        "live_source_writes",
        "eligible_for_external_review",
        "eligible_for_apply",
        "authority_granted",
    }
    if (
        not isinstance(record, dict)
        or set(record) != required
        or record.get("schema") != EXECUTION_RESULT_SCHEMA
        or not isinstance(record.get("execution_id"), str)
        or not _EXECUTION_ID_RE.fullmatch(record["execution_id"])
        or not isinstance(record.get("approval_id"), str)
        or not _APPROVAL_ID_RE.fullmatch(record["approval_id"])
        or not isinstance(record.get("challenge_id"), str)
        or not _CHALLENGE_ID_RE.fullmatch(record["challenge_id"])
        or not isinstance(record.get("proposal_id"), str)
        or not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", record["proposal_id"])
        or not isinstance(record.get("candidate_id"), str)
        or not re.fullmatch(r"sip-[0-9a-f]{32}", record["candidate_id"])
        or not isinstance(record.get("evaluation_id"), str)
        or not _EVALUATION_ID_RE.fullmatch(record["evaluation_id"])
        or record.get("outcome")
        not in {
            "passed",
            "failed",
            "timed_out",
            "output_limit_exceeded",
            "runner_error",
        }
        or record.get("isolated_execution") is not True
        or record.get("live_source_writes") is not False
        or record.get("eligible_for_apply") is not False
        or record.get("authority_granted") is not False
        or record.get("eligible_for_external_review")
        is not (record.get("outcome") == "passed")
        or record.get("execution_performed")
        is not (record.get("container_started") is True)
        or record.get("tests_executed") is not (record.get("container_started") is True)
        or any(
            not isinstance(record.get(field), bool)
            for field in (
                "container_started",
                "timed_out",
                "output_limit_exceeded",
                "oom_killed",
                "cleanup_confirmed",
                "isolated_execution",
                "execution_performed",
                "tests_executed",
                "live_source_writes",
                "eligible_for_external_review",
                "eligible_for_apply",
                "authority_granted",
            )
        )
        or isinstance(record.get("duration_ms"), bool)
        or not isinstance(record.get("duration_ms"), int)
        or record["duration_ms"] < 0
    ):
        raise ExecutionError("execution result violates its containment contract")
    approval = validate_execution_approval(record.get("approval"))
    raw_approval_signature = record.get("approval_signature")
    approval_signature_value = (
        raw_approval_signature.get("value")
        if isinstance(raw_approval_signature, dict)
        else None
    )
    if (
        raw_approval_signature
        != approval_signature_record(approval, approval_signature_value)
        or record.get("approval_id") != approval["approval_id"]
        or record.get("approval_sha256") != execution_approval_sha256(approval)
        or record.get("challenge_id") != approval["challenge_id"]
        or record.get("proposal_id") != approval["proposal_id"]
        or record.get("proposal_content_sha256") != approval["proposal_content_sha256"]
        or record.get("candidate_id") != approval["candidate_id"]
        or record.get("candidate_sha256") != approval["candidate_sha256"]
        or record.get("evaluation_id") != approval["evaluation_id"]
        or record.get("evaluation_sha256") != approval["evaluation_sha256"]
        or record.get("source_snapshot") != approval["source_snapshot"]
        or record.get("profile") != approval["profile"]
        or record.get("runner_identity") != approval["runner_identity"]
    ):
        raise ExecutionError("execution result approval binding is malformed")
    outcome = record["outcome"]
    started = record["container_started"]
    timed_out = record["timed_out"]
    output_limited = record["output_limit_exceeded"]
    cleanup_confirmed = record["cleanup_confirmed"]
    exit_code = record.get("exit_code")
    if timed_out and output_limited:
        raise ExecutionError("execution result has conflicting termination reasons")
    if outcome == "passed" and not (
        started
        and not timed_out
        and not output_limited
        and exit_code == 0
        and cleanup_confirmed
        and record["oom_killed"] is False
    ):
        raise ExecutionError("passing execution result is internally inconsistent")
    if outcome == "failed" and not (
        started
        and not timed_out
        and not output_limited
        and isinstance(exit_code, int)
        and not isinstance(exit_code, bool)
        and exit_code != 0
        and cleanup_confirmed
    ):
        raise ExecutionError("failed execution result is internally inconsistent")
    if outcome == "timed_out" and not (
        started and timed_out and not output_limited and cleanup_confirmed
    ):
        raise ExecutionError("timed-out execution result is internally inconsistent")
    if outcome == "output_limit_exceeded" and not (
        started and output_limited and not timed_out and cleanup_confirmed
    ):
        raise ExecutionError(
            "output-limited execution result is internally inconsistent"
        )
    for field in (
        "approval_sha256",
        "proposal_content_sha256",
        "candidate_sha256",
        "evaluation_sha256",
        "isolation_contract_sha256",
    ):
        _require_sha256(record.get(field), field)
    if record.get("isolation_contract_sha256") != _sha256(
        canonical_json_bytes(_runner_contract())
    ):
        raise ExecutionError("execution result isolation binding is malformed")
    validate_source_snapshot(record.get("source_snapshot"))
    validate_runner_identity(record.get("runner_identity"))
    profile_record = record.get("profile")
    if not isinstance(profile_record, dict):
        raise ExecutionError("execution result profile is malformed")
    profile = execution_profile(profile_record.get("profile_id"))
    if profile_record != profile.public_record():
        raise ExecutionError("execution result profile binding is malformed")
    _validate_output(record.get("stdout"), "stdout")
    _validate_output(record.get("stderr"), "stderr")
    stdout = record["stdout"]
    stderr = record["stderr"]
    if any(
        stream["truncated"]
        is not (
            stream["bytes"] > profile.max_output_bytes
            or record["output_limit_exceeded"]
        )
        for stream in (stdout, stderr)
    ):
        raise ExecutionError("execution output truncation marker is inconsistent")
    combined_output = stdout["bytes"] + stderr["bytes"]
    if (
        record["output_limit_exceeded"] and combined_output != profile.max_stream_bytes
    ) or (
        not record["output_limit_exceeded"]
        and combined_output > profile.max_stream_bytes
    ):
        raise ExecutionError("execution output limit marker is inconsistent")
    try:
        started = parse_utc_timestamp(record.get("started_at"), "started_at")
        finished = parse_utc_timestamp(record.get("finished_at"), "finished_at")
    except VerificationError as exc:
        raise ExecutionError(str(exc)) from exc
    if finished < started:
        raise ExecutionError("execution result time range is malformed")
    if exit_code is not None and (
        isinstance(exit_code, bool) or not isinstance(exit_code, int)
    ):
        raise ExecutionError("execution result exit code is malformed")


def validate_signed_execution_result(
    value: Any, key_provider: VerifierKeyProvider
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "execution_id",
        "approval",
        "approval_signature",
        "approval_id",
        "approval_sha256",
        "challenge_id",
        "proposal_id",
        "proposal_content_sha256",
        "candidate_id",
        "candidate_sha256",
        "evaluation_id",
        "evaluation_sha256",
        "source_snapshot",
        "profile",
        "runner_identity",
        "isolation_contract_sha256",
        "started_at",
        "finished_at",
        "duration_ms",
        "outcome",
        "container_started",
        "timed_out",
        "output_limit_exceeded",
        "exit_code",
        "oom_killed",
        "stdout",
        "stderr",
        "cleanup_confirmed",
        "isolated_execution",
        "execution_performed",
        "tests_executed",
        "live_source_writes",
        "eligible_for_external_review",
        "eligible_for_apply",
        "authority_granted",
        "result_sha256",
        "signature",
    }:
        raise ExecutionError("signed execution result fields are malformed")
    unsigned = copy.deepcopy(value)
    signature = unsigned.pop("signature")
    result_digest = unsigned.pop("result_sha256")
    _validate_unsigned_result(unsigned)
    _require_sha256(result_digest, "result_sha256")
    expected_digest = _sha256(canonical_json_bytes(unsigned))
    if result_digest != expected_digest:
        raise ExecutionError("execution result digest is invalid")
    approval = unsigned["approval"]
    recorded_approval_signature = unsigned["approval_signature"]
    try:
        approval_key = key_provider(
            recorded_approval_signature["approver_id"],
            recorded_approval_signature["key_id"],
        )
    except Exception as exc:
        raise ExecutionError(
            "execution approval signing key registry is unavailable"
        ) from exc
    if (
        not isinstance(approval_key, VerifierKey)
        or approval_key.verifier_id != recorded_approval_signature["approver_id"]
        or approval_key.key_id != recorded_approval_signature["key_id"]
        or not verify_execution_approval_signature(
            approval, recorded_approval_signature["value"], approval_key
        )
    ):
        raise ExecutionError("recorded execution approval signature is invalid")
    if (
        not isinstance(signature, dict)
        or set(signature)
        != {
            "algorithm",
            "signer_id",
            "key_id",
            "value",
            "assurance",
        }
        or signature.get("algorithm") != SIGNATURE_ALGORITHM
        or signature.get("assurance") != "symmetric_mac_server_verifiable"
        or not isinstance(signature.get("signer_id"), str)
        or not re.fullmatch(r"[A-Za-z0-9._:@/-]{1,300}", signature["signer_id"])
        or not isinstance(signature.get("key_id"), str)
        or not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", signature["key_id"])
        or not isinstance(signature.get("value"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", signature["value"])
    ):
        raise ExecutionError("execution result signature is malformed")
    expected_result_signer = unsigned["approval"]["result_signer"]
    if (
        signature["signer_id"] != expected_result_signer["id"]
        or signature["key_id"] != expected_result_signer["key_id"]
    ):
        raise ExecutionError("execution result signer does not match its approval")
    try:
        key = key_provider(signature["signer_id"], signature["key_id"])
    except Exception as exc:
        raise ExecutionError(
            "execution result signing key registry is unavailable"
        ) from exc
    if (
        not isinstance(key, VerifierKey)
        or key.verifier_id != signature["signer_id"]
        or key.key_id != signature["key_id"]
    ):
        raise ExecutionError("execution result signing key is unavailable")
    expected = hmac.new(
        key.secret,
        RESULT_DOMAIN
        + canonical_json_bytes({**unsigned, "result_sha256": result_digest}),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature["value"]):
        raise ExecutionError("execution result signature is invalid")
    return copy.deepcopy(value)


__all__ = [
    "APPROVAL_VALIDITY",
    "DISPLAY_ERA_TEST_PROFILE",
    "DockerIsolationRunner",
    "EXECUTION_APPROVAL_SCHEMA",
    "EXECUTION_CONTRACT_SCHEMA",
    "EXECUTION_PROFILES",
    "EXECUTION_RESULT_SCHEMA",
    "ExecutionError",
    "ExecutionProfile",
    "IsolationRunner",
    "RUNNER_SIGNER_ID_ENV",
    "SourceWorkspaceBuilder",
    "approval_signature_record",
    "approval_signing_input_b64",
    "build_execution_approval",
    "build_signed_execution_result",
    "execution_contract",
    "execution_profile",
    "isolation_contract_sha256",
    "sign_execution_approval",
    "validate_execution_approval",
    "validate_runner_identity",
    "validate_signed_execution_result",
    "validate_source_snapshot",
    "verify_execution_approval_signature",
]
