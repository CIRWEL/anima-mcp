"""Reviewed candidate application to a dedicated Git ref without checkout.

This boundary deliberately uses Git plumbing with a temporary index.  It may
write immutable Git objects and create one server-derived branch ref, but it
never changes the live worktree, invokes hooks, checks out code, executes the
candidate, pushes, merges, restarts a service, or deploys a release.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from .self_iteration_execution import validate_source_snapshot
from .self_iteration_verification import (
    SIGNATURE_ALGORITHM,
    VerificationError,
    VerifierKey,
    VerifierKeyProvider,
    canonical_json_bytes,
    parse_utc_timestamp,
)

APPLICATION_CONTRACT_SCHEMA = "anima.self_iteration.application_contract.v1"
APPLICATION_APPROVAL_SCHEMA = "anima.self_iteration.application_approval.v1"
APPLICATION_RESULT_SCHEMA = "anima.self_iteration.application_result.v1"
APPLICATION_BACKEND_SCHEMA = "anima.self_iteration.git_application_backend.v1"

APPLICATION_APPROVAL_DOMAIN = b"anima.self_iteration.application_approval.v1\x00"
APPLICATION_RESULT_DOMAIN = b"anima.self_iteration.application_result.v1\x00"
APPLICATION_VALIDITY = timedelta(minutes=10)

APPLICATION_SIGNER_ID_ENV = "ANIMA_SELF_ITERATION_APPLIER_SIGNER_ID"
APPLICATION_GIT_BINARY_ENV = "ANIMA_SELF_ITERATION_GIT_BINARY"

MAX_GIT_OUTPUT_BYTES = 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OBJECT_ID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_CANDIDATE_ID_RE = re.compile(r"^sip-[0-9a-f]{32}$")
_EXECUTION_ID_RE = re.compile(r"^six-[0-9a-f]{32}$")
_APPLICATION_ID_RE = re.compile(r"^siap-[0-9a-f]{32}$")
_CHALLENGE_ID_RE = re.compile(r"^siac-[0-9a-f]{32}$")
_RESULT_ID_RE = re.compile(r"^siar-[0-9a-f]{32}$")
_ATTESTATION_ID_RE = re.compile(r"^sia-[0-9a-f]{32}$")


class ApplicationError(ValueError):
    """Raised when reviewed application or Git containment fails."""


class ApplicationWriter(Protocol):
    def probe(
        self,
        *,
        repo_root: Path,
        expected_parent_revision: str,
        target_ref: str,
    ) -> dict[str, Any]: ...

    def apply(
        self,
        *,
        repo_root: Path,
        expected_identity: dict[str, Any],
        approval: dict[str, Any],
        candidate_manifest: dict[str, Any],
        candidate_contents: dict[str, bytes],
        applied_at: str,
    ) -> dict[str, Any]: ...

    def verify_result(self, *, repo_root: Path, result: dict[str, Any]) -> bool: ...


def application_contract() -> dict[str, Any]:
    """Return the immutable Phase 5 authority boundary."""
    return {
        "schema": APPLICATION_CONTRACT_SCHEMA,
        "approval_schema": APPLICATION_APPROVAL_SCHEMA,
        "result_schema": APPLICATION_RESULT_SCHEMA,
        "backend": "git_plumbing_dedicated_ref",
        "passing_signed_execution_required": True,
        "authenticated_external_reviewer_required": True,
        "reviewer_must_differ_from_all_prior_participants": True,
        "approval_validity_seconds": int(APPLICATION_VALIDITY.total_seconds()),
        "approval_signature_algorithm": SIGNATURE_ALGORITHM,
        "dedicated_result_signer_required": True,
        "one_time_application_claim_required": True,
        "clean_committed_source_required": True,
        "temporary_index_required": True,
        "checkout_allowed": False,
        "hooks_allowed": False,
        "working_tree_writes": False,
        "live_source_writes": False,
        "dedicated_ref_prefix": "refs/heads/anima/self-iteration/",
        "push_allowed": False,
        "merge_allowed": False,
        "restart_allowed": False,
        "deploy_allowed": False,
        "authority_granted": False,
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.lower()):
        raise ApplicationError(f"{field} must be exactly 64 hexadecimal characters")
    return value.lower()


def _require_object_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _OBJECT_ID_RE.fullmatch(value.lower()):
        raise ApplicationError(f"{field} is not a full Git object identifier")
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
        raise ApplicationError(f"{field} identity is malformed")
    return {
        "kind": value["kind"],
        "id": value["id"],
        "issuer": value.get("issuer"),
    }


def target_ref_for_candidate(candidate_id: str) -> str:
    if not isinstance(candidate_id, str) or not _CANDIDATE_ID_RE.fullmatch(
        candidate_id
    ):
        raise ApplicationError("application candidate identifier is malformed")
    return f"refs/heads/anima/self-iteration/{candidate_id}"


def commit_policy(proposal_id: str, candidate_id: str) -> dict[str, str]:
    if not isinstance(proposal_id, str) or not re.fullmatch(
        r"[A-Za-z0-9._:-]{1,100}", proposal_id
    ):
        raise ApplicationError("application proposal identifier is malformed")
    target_ref_for_candidate(candidate_id)
    return {
        "message": (
            f"self-iteration: apply {candidate_id}\n\n"
            f"Proposal: {proposal_id}\n"
            "Boundary: reviewed dedicated branch; not pushed, merged, or deployed"
        ),
        "author_name": "Lumen Self-Iteration",
        "author_email": "lumen-self-iteration@localhost",
        "committer_name": "Anima Application Boundary",
        "committer_email": "anima-application@localhost",
    }


def validate_git_identity(value: Any) -> dict[str, Any]:
    required = {
        "schema",
        "backend",
        "object_format",
        "git_version",
        "head_revision",
        "head_ref",
        "target_ref",
        "target_ref_absent",
        "worktree_clean",
        "hooks_policy",
        "checkout_performed",
        "working_tree_writes",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("schema") != APPLICATION_BACKEND_SCHEMA
        or value.get("backend") != "git_plumbing"
        or value.get("object_format") not in {"sha1", "sha256"}
        or not isinstance(value.get("git_version"), str)
        or not value["git_version"].startswith("git version ")
        or not isinstance(value.get("head_ref"), str)
        or not value["head_ref"]
        or value.get("target_ref_absent") is not True
        or value.get("worktree_clean") is not True
        or value.get("hooks_policy") != "disabled"
        or value.get("checkout_performed") is not False
        or value.get("working_tree_writes") is not False
    ):
        raise ApplicationError("Git application backend identity is malformed")
    _require_object_id(value.get("head_revision"), "git head revision")
    target_ref = value.get("target_ref")
    if not isinstance(target_ref, str) or not re.fullmatch(
        r"refs/heads/anima/self-iteration/sip-[0-9a-f]{32}", target_ref
    ):
        raise ApplicationError("Git application target ref is malformed")
    expected_length = 40 if value["object_format"] == "sha1" else 64
    if len(value["head_revision"]) != expected_length:
        raise ApplicationError("Git object format does not match the head revision")
    return copy.deepcopy(value)


def build_application_approval(
    *,
    proposal_id: str,
    proposal_content_sha256: str,
    source_fingerprint: dict[str, Any],
    active_attestation_ids: list[str],
    candidate_id: str,
    candidate_sha256: str,
    execution_id: str,
    execution_result_sha256: str,
    execution_approval_sha256: str,
    execution_finished_at: str,
    source_snapshot: dict[str, Any],
    reviewer_identity: dict[str, Any],
    reviewer_key_id: str,
    git_identity: dict[str, Any],
    result_signer_id: str,
    result_signer_key_id: str,
    issued_at: datetime,
) -> dict[str, Any]:
    """Build the exact, short-lived application plan a reviewer must sign."""
    if issued_at.tzinfo is None:
        raise ApplicationError("application approval time must be timezone-aware")
    issued = issued_at.astimezone(timezone.utc)
    snapshot = validate_source_snapshot(source_snapshot)
    target_ref = target_ref_for_candidate(candidate_id)
    approval = {
        "schema": APPLICATION_APPROVAL_SCHEMA,
        "application_id": f"siap-{uuid.uuid4().hex}",
        "challenge_id": f"siac-{uuid.uuid4().hex}",
        "proposal_id": proposal_id,
        "proposal_content_sha256": _require_sha256(
            proposal_content_sha256, "proposal_content_sha256"
        ),
        "source_fingerprint": copy.deepcopy(source_fingerprint),
        "active_attestation_ids": sorted(active_attestation_ids),
        "candidate_id": candidate_id,
        "candidate_sha256": _require_sha256(candidate_sha256, "candidate_sha256"),
        "execution_id": execution_id,
        "execution_result_sha256": _require_sha256(
            execution_result_sha256, "execution_result_sha256"
        ),
        "execution_approval_sha256": _require_sha256(
            execution_approval_sha256, "execution_approval_sha256"
        ),
        "execution_finished_at": execution_finished_at,
        "source_snapshot": snapshot,
        "reviewer_identity": _identity(reviewer_identity, "application reviewer"),
        "reviewer_key_id": reviewer_key_id,
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "git_identity": validate_git_identity(git_identity),
        "target_ref": target_ref,
        "expected_parent_revision": snapshot["revision"],
        "expected_candidate_tree_sha256": snapshot["candidate_tree_sha256"],
        "commit_policy": commit_policy(proposal_id, candidate_id),
        "result_signer": {
            "id": result_signer_id,
            "key_id": result_signer_key_id,
            "algorithm": SIGNATURE_ALGORITHM,
            "assurance": "symmetric_mac_server_verifiable",
        },
        "issued_at": issued.isoformat().replace("+00:00", "Z"),
        "challenge_expires_at": (issued + APPLICATION_VALIDITY)
        .isoformat()
        .replace("+00:00", "Z"),
        "nonce": uuid.uuid4().hex,
        "application_claims_authority": False,
    }
    validate_application_approval(approval)
    return approval


def validate_application_approval(value: Any) -> dict[str, Any]:
    required = {
        "schema",
        "application_id",
        "challenge_id",
        "proposal_id",
        "proposal_content_sha256",
        "source_fingerprint",
        "active_attestation_ids",
        "candidate_id",
        "candidate_sha256",
        "execution_id",
        "execution_result_sha256",
        "execution_approval_sha256",
        "execution_finished_at",
        "source_snapshot",
        "reviewer_identity",
        "reviewer_key_id",
        "signature_algorithm",
        "git_identity",
        "target_ref",
        "expected_parent_revision",
        "expected_candidate_tree_sha256",
        "commit_policy",
        "result_signer",
        "issued_at",
        "challenge_expires_at",
        "nonce",
        "application_claims_authority",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ApplicationError("application approval fields are malformed")
    if (
        value.get("schema") != APPLICATION_APPROVAL_SCHEMA
        or not isinstance(value.get("application_id"), str)
        or not _APPLICATION_ID_RE.fullmatch(value["application_id"])
        or not isinstance(value.get("challenge_id"), str)
        or not _CHALLENGE_ID_RE.fullmatch(value["challenge_id"])
        or not isinstance(value.get("proposal_id"), str)
        or not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", value["proposal_id"])
        or not isinstance(value.get("candidate_id"), str)
        or not _CANDIDATE_ID_RE.fullmatch(value["candidate_id"])
        or not isinstance(value.get("execution_id"), str)
        or not _EXECUTION_ID_RE.fullmatch(value["execution_id"])
        or value.get("signature_algorithm") != SIGNATURE_ALGORITHM
        or value.get("application_claims_authority") is not False
    ):
        raise ApplicationError("application approval identity is malformed")
    for field in (
        "proposal_content_sha256",
        "candidate_sha256",
        "execution_result_sha256",
        "execution_approval_sha256",
        "expected_candidate_tree_sha256",
    ):
        _require_sha256(value.get(field), field)
    fingerprint = value.get("source_fingerprint")
    if not isinstance(fingerprint, dict) or set(fingerprint) != {
        "revision",
        "manifest_sha256",
    }:
        raise ApplicationError("application source fingerprint is malformed")
    _require_object_id(fingerprint.get("revision"), "source revision")
    _require_sha256(fingerprint.get("manifest_sha256"), "source manifest")
    attestation_ids = value.get("active_attestation_ids")
    if (
        not isinstance(attestation_ids, list)
        or not attestation_ids
        or attestation_ids != sorted(attestation_ids)
        or len(attestation_ids) != len(set(attestation_ids))
        or any(
            not isinstance(item, str) or not _ATTESTATION_ID_RE.fullmatch(item)
            for item in attestation_ids
        )
    ):
        raise ApplicationError("application attestation binding is malformed")
    snapshot = validate_source_snapshot(value.get("source_snapshot"))
    git_identity = validate_git_identity(value.get("git_identity"))
    if (
        value.get("target_ref") != target_ref_for_candidate(value["candidate_id"])
        or git_identity["target_ref"] != value["target_ref"]
        or value.get("expected_parent_revision") != snapshot["revision"]
        or value["expected_parent_revision"] != fingerprint["revision"]
        or git_identity["head_revision"] != value["expected_parent_revision"]
        or value.get("expected_candidate_tree_sha256")
        != snapshot["candidate_tree_sha256"]
        or value.get("commit_policy")
        != commit_policy(value["proposal_id"], value["candidate_id"])
    ):
        raise ApplicationError("application source or Git binding is malformed")
    _identity(value.get("reviewer_identity"), "application reviewer")
    if not isinstance(value.get("reviewer_key_id"), str) or not re.fullmatch(
        r"[A-Za-z0-9._:-]{1,100}", value["reviewer_key_id"]
    ):
        raise ApplicationError("application reviewer key is malformed")
    signer = value.get("result_signer")
    if (
        not isinstance(signer, dict)
        or set(signer) != {"id", "key_id", "algorithm", "assurance"}
        or not isinstance(signer.get("id"), str)
        or not re.fullmatch(r"[A-Za-z0-9._:@/-]{1,300}", signer["id"])
        or not isinstance(signer.get("key_id"), str)
        or not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", signer["key_id"])
        or signer.get("algorithm") != SIGNATURE_ALGORITHM
        or signer.get("assurance") != "symmetric_mac_server_verifiable"
    ):
        raise ApplicationError("application result signer is malformed")
    try:
        finished = parse_utc_timestamp(
            value.get("execution_finished_at"), "execution_finished_at"
        )
        issued = parse_utc_timestamp(value.get("issued_at"), "issued_at")
        expires = parse_utc_timestamp(
            value.get("challenge_expires_at"), "challenge_expires_at"
        )
    except VerificationError as exc:
        raise ApplicationError(str(exc)) from exc
    if issued < finished or expires - issued != APPLICATION_VALIDITY:
        raise ApplicationError("application approval time binding is malformed")
    if not isinstance(value.get("nonce"), str) or not re.fullmatch(
        r"[0-9a-f]{32}", value["nonce"]
    ):
        raise ApplicationError("application approval nonce is malformed")
    return copy.deepcopy(value)


def application_approval_sha256(approval: dict[str, Any]) -> str:
    return _sha256(canonical_json_bytes(validate_application_approval(approval)))


def application_signing_input_b64(approval: dict[str, Any]) -> str:
    payload = APPLICATION_APPROVAL_DOMAIN + canonical_json_bytes(
        validate_application_approval(approval)
    )
    return base64.urlsafe_b64encode(payload).decode("ascii")


def sign_application_approval(approval: dict[str, Any], key: VerifierKey) -> str:
    validated = validate_application_approval(approval)
    if (
        key.verifier_id != validated["reviewer_identity"]["id"]
        or key.key_id != validated["reviewer_key_id"]
    ):
        raise ApplicationError("application signing key does not match its plan")
    return hmac.new(
        key.secret,
        APPLICATION_APPROVAL_DOMAIN + canonical_json_bytes(validated),
        hashlib.sha256,
    ).hexdigest()


def verify_application_approval_signature(
    approval: dict[str, Any], signature: Any, key: VerifierKey
) -> bool:
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        return False
    try:
        expected = sign_application_approval(approval, key)
    except ApplicationError:
        return False
    return hmac.compare_digest(expected, signature)


def application_signature_record(
    approval: dict[str, Any], signature: Any
) -> dict[str, str]:
    validated = validate_application_approval(approval)
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise ApplicationError("application approval signature is malformed")
    return {
        "algorithm": SIGNATURE_ALGORITHM,
        "reviewer_id": validated["reviewer_identity"]["id"],
        "key_id": validated["reviewer_key_id"],
        "value": signature,
        "assurance": "symmetric_mac_server_verifiable",
    }


@dataclass(frozen=True)
class GitCommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class GitPlumbingApplicationWriter:
    """Create one dedicated branch through a temporary Git index."""

    def __init__(self, *, git_binary: str | None = None) -> None:
        self.git_binary = git_binary

    @classmethod
    def from_environment(cls) -> GitPlumbingApplicationWriter:
        return cls(git_binary=os.environ.get(APPLICATION_GIT_BINARY_ENV))

    def _binary(self) -> str:
        if self.git_binary is not None:
            candidate = Path(self.git_binary)
            if not candidate.is_absolute():
                raise ApplicationError(
                    f"{APPLICATION_GIT_BINARY_ENV} must be an absolute path"
                )
            resolved = candidate.resolve(strict=False)
            if not resolved.is_file() or not os.access(resolved, os.X_OK):
                raise ApplicationError("configured Git binary is unavailable")
            return str(resolved)
        discovered = shutil.which("git")
        if not discovered:
            raise ApplicationError("Git is unavailable; application is disabled")
        return str(Path(discovered).resolve())

    @staticmethod
    def _environment(extra: dict[str, str] | None = None) -> dict[str, str]:
        environment = {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_LITERAL_PATHSPECS": "1",
        }
        if extra:
            environment.update(extra)
        return environment

    def _git(
        self,
        repo_root: Path,
        *arguments: str,
        input_bytes: bytes | None = None,
        extra_environment: dict[str, str] | None = None,
        accepted_codes: tuple[int, ...] = (0,),
        timeout: int = 20,
    ) -> GitCommandResult:
        command = [
            self._binary(),
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgSign=false",
            "-C",
            str(repo_root),
            *arguments,
        ]
        try:
            result = subprocess.run(
                command,
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                env=self._environment(extra_environment),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ApplicationError("Git application command failed to run") from exc
        if (
            len(result.stdout) > MAX_GIT_OUTPUT_BYTES
            or len(result.stderr) > MAX_GIT_OUTPUT_BYTES
        ):
            raise ApplicationError("Git application command exceeded its output limit")
        if result.returncode not in accepted_codes:
            raise ApplicationError("Git application command failed")
        return GitCommandResult(result.returncode, result.stdout, result.stderr)

    def probe(
        self,
        *,
        repo_root: Path,
        expected_parent_revision: str,
        target_ref: str,
    ) -> dict[str, Any]:
        root = repo_root.resolve(strict=True)
        expected = _require_object_id(
            expected_parent_revision, "expected parent revision"
        )
        if not re.fullmatch(
            r"refs/heads/anima/self-iteration/sip-[0-9a-f]{32}", target_ref
        ):
            raise ApplicationError("Git application target ref is malformed")
        top = self._git(root, "rev-parse", "--show-toplevel").stdout.decode().strip()
        if Path(top).resolve(strict=True) != root:
            raise ApplicationError("Git application repository root is ambiguous")
        head = (
            self._git(root, "rev-parse", "--verify", "HEAD^{commit}")
            .stdout.decode()
            .strip()
            .lower()
        )
        if head != expected:
            raise ApplicationError("Git HEAD changed after application review")
        status = self._git(
            root, "status", "--porcelain=v1", "-z", "--untracked-files=normal"
        ).stdout
        if status:
            raise ApplicationError(
                "reviewed application requires a clean source worktree"
            )
        head_ref_result = self._git(
            root,
            "symbolic-ref",
            "--quiet",
            "--short",
            "HEAD",
            accepted_codes=(0, 1),
        )
        head_ref = (
            head_ref_result.stdout.decode().strip()
            if head_ref_result.returncode == 0
            else "detached"
        )
        object_format = (
            self._git(root, "rev-parse", "--show-object-format").stdout.decode().strip()
        )
        existing = self._git(
            root,
            "show-ref",
            "--verify",
            "--quiet",
            target_ref,
            accepted_codes=(0, 1),
        )
        if existing.returncode == 0:
            raise ApplicationError("dedicated application branch already exists")
        version = self._git(root, "version").stdout.decode().strip()
        identity = {
            "schema": APPLICATION_BACKEND_SCHEMA,
            "backend": "git_plumbing",
            "object_format": object_format,
            "git_version": version,
            "head_revision": head,
            "head_ref": head_ref,
            "target_ref": target_ref,
            "target_ref_absent": True,
            "worktree_clean": True,
            "hooks_policy": "disabled",
            "checkout_performed": False,
            "working_tree_writes": False,
        }
        return validate_git_identity(identity)

    @staticmethod
    def _candidate_paths(
        candidate_manifest: dict[str, Any], candidate_contents: dict[str, bytes]
    ) -> list[str]:
        files = candidate_manifest.get("files")
        if not isinstance(files, list):
            raise ApplicationError("candidate application manifest is malformed")
        paths: list[str] = []
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ApplicationError("candidate application paths are inconsistent")
            paths.append(item["path"])
        if sorted(paths) != sorted(candidate_contents) or len(paths) != len(set(paths)):
            raise ApplicationError("candidate application paths are inconsistent")
        return sorted(paths)

    def apply(
        self,
        *,
        repo_root: Path,
        expected_identity: dict[str, Any],
        approval: dict[str, Any],
        candidate_manifest: dict[str, Any],
        candidate_contents: dict[str, bytes],
        applied_at: str,
    ) -> dict[str, Any]:
        validated = validate_application_approval(approval)
        identity = validate_git_identity(expected_identity)
        current = self.probe(
            repo_root=repo_root,
            expected_parent_revision=validated["expected_parent_revision"],
            target_ref=validated["target_ref"],
        )
        if current != identity or current != validated["git_identity"]:
            raise ApplicationError("Git application backend changed after review")
        paths = self._candidate_paths(candidate_manifest, candidate_contents)
        if paths != validated["source_snapshot"]["candidate_paths"]:
            raise ApplicationError("candidate paths changed after application review")
        try:
            parsed_applied_at = parse_utc_timestamp(applied_at, "applied_at")
        except VerificationError as exc:
            raise ApplicationError(str(exc)) from exc
        timestamp = parsed_applied_at.astimezone(timezone.utc).isoformat()
        root = repo_root.resolve(strict=True)
        temporary = Path(tempfile.mkdtemp(prefix="anima-self-iteration-apply-"))
        index_path = temporary / "index"
        index_environment = {"GIT_INDEX_FILE": str(index_path)}
        try:
            self._git(
                root,
                "read-tree",
                validated["expected_parent_revision"],
                extra_environment=index_environment,
            )
            for path in paths:
                staged = self._git(
                    root,
                    "ls-files",
                    "--stage",
                    "-z",
                    "--",
                    path,
                    extra_environment=index_environment,
                ).stdout
                match = re.fullmatch(
                    rb"(100644|100755) ([0-9a-f]{40}(?:[0-9a-f]{24})?) 0\t(.+)\x00",
                    staged,
                )
                if match is None or match.group(3).decode("utf-8") != path:
                    raise ApplicationError(
                        "candidate target is not one regular tracked file"
                    )
                mode = match.group(1).decode("ascii")
                blob = (
                    self._git(
                        root,
                        "hash-object",
                        "-w",
                        "--stdin",
                        input_bytes=candidate_contents[path],
                    )
                    .stdout.decode()
                    .strip()
                    .lower()
                )
                _require_object_id(blob, "candidate blob")
                self._git(
                    root,
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    mode,
                    blob,
                    path,
                    extra_environment=index_environment,
                )
            tree_oid = (
                self._git(root, "write-tree", extra_environment=index_environment)
                .stdout.decode()
                .strip()
                .lower()
            )
            _require_object_id(tree_oid, "application tree")
            policy = validated["commit_policy"]
            commit_environment = {
                "GIT_AUTHOR_NAME": policy["author_name"],
                "GIT_AUTHOR_EMAIL": policy["author_email"],
                "GIT_AUTHOR_DATE": timestamp,
                "GIT_COMMITTER_NAME": policy["committer_name"],
                "GIT_COMMITTER_EMAIL": policy["committer_email"],
                "GIT_COMMITTER_DATE": timestamp,
            }
            commit_oid = (
                self._git(
                    root,
                    "commit-tree",
                    tree_oid,
                    "-p",
                    validated["expected_parent_revision"],
                    input_bytes=(policy["message"] + "\n").encode("utf-8"),
                    extra_environment=commit_environment,
                )
                .stdout.decode()
                .strip()
                .lower()
            )
            _require_object_id(commit_oid, "application commit")
            zero = "0" * len(commit_oid)
            self._git(
                root,
                "update-ref",
                "--create-reflog",
                "-m",
                f"anima reviewed application {validated['application_id']}",
                validated["target_ref"],
                commit_oid,
                zero,
            )
            resolved = (
                self._git(root, "rev-parse", "--verify", validated["target_ref"])
                .stdout.decode()
                .strip()
                .lower()
            )
            head_after = (
                self._git(root, "rev-parse", "--verify", "HEAD^{commit}")
                .stdout.decode()
                .strip()
                .lower()
            )
            status_after = self._git(
                root, "status", "--porcelain=v1", "-z", "--untracked-files=normal"
            ).stdout
            if (
                resolved != commit_oid
                or head_after != validated["expected_parent_revision"]
                or status_after
            ):
                raise ApplicationError(
                    "Git application could not confirm its containment boundary"
                )
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        return {
            "backend": "git_plumbing",
            "object_format": identity["object_format"],
            "parent_revision": validated["expected_parent_revision"],
            "tree_oid": tree_oid,
            "commit_oid": commit_oid,
            "target_ref": validated["target_ref"],
            "branch_created": True,
            "checkout_performed": False,
            "hooks_executed": False,
            "working_tree_writes": False,
            "live_source_writes": False,
            "pushed": False,
            "merged": False,
            "deployed": False,
        }

    def verify_result(self, *, repo_root: Path, result: dict[str, Any]) -> bool:
        try:
            unsigned = copy.deepcopy(result)
            unsigned.pop("signature", None)
            unsigned.pop("result_sha256", None)
            validated = validate_application_result_shape(unsigned)
            root = repo_root.resolve(strict=True)
            commit_oid = (
                self._git(root, "rev-parse", "--verify", validated["target_ref"])
                .stdout.decode()
                .strip()
                .lower()
            )
            tree_oid = (
                self._git(root, "rev-parse", f"{commit_oid}^{{tree}}")
                .stdout.decode()
                .strip()
                .lower()
            )
            parent = (
                self._git(root, "rev-parse", f"{commit_oid}^")
                .stdout.decode()
                .strip()
                .lower()
            )
            status = self._git(
                root, "status", "--porcelain=v1", "-z", "--untracked-files=normal"
            ).stdout
        except (ApplicationError, OSError):
            return False
        return (
            commit_oid == validated["commit_oid"]
            and tree_oid == validated["tree_oid"]
            and parent == validated["parent_revision"]
            and not status
        )


def validate_application_result_shape(value: Any) -> dict[str, Any]:
    required = {
        "schema",
        "application_result_id",
        "approval",
        "approval_signature",
        "application_id",
        "application_approval_sha256",
        "challenge_id",
        "proposal_id",
        "proposal_content_sha256",
        "candidate_id",
        "candidate_sha256",
        "execution_id",
        "execution_result_sha256",
        "source_snapshot",
        "git_identity",
        "target_ref",
        "parent_revision",
        "tree_oid",
        "commit_oid",
        "applied_at",
        "commit_policy",
        "branch_created",
        "checkout_performed",
        "hooks_executed",
        "working_tree_writes",
        "live_source_writes",
        "pushed",
        "merged",
        "deployed",
        "eligible_for_canary_review",
        "eligible_for_live_activation",
        "authority_granted",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ApplicationError("application result fields are malformed")
    approval = validate_application_approval(value.get("approval"))
    raw_signature = value.get("approval_signature")
    signature_value = (
        raw_signature.get("value") if isinstance(raw_signature, dict) else None
    )
    if (
        value.get("schema") != APPLICATION_RESULT_SCHEMA
        or not isinstance(value.get("application_result_id"), str)
        or not _RESULT_ID_RE.fullmatch(value["application_result_id"])
        or raw_signature != application_signature_record(approval, signature_value)
        or value.get("application_id") != approval["application_id"]
        or value.get("application_approval_sha256")
        != application_approval_sha256(approval)
        or value.get("challenge_id") != approval["challenge_id"]
        or value.get("proposal_id") != approval["proposal_id"]
        or value.get("proposal_content_sha256") != approval["proposal_content_sha256"]
        or value.get("candidate_id") != approval["candidate_id"]
        or value.get("candidate_sha256") != approval["candidate_sha256"]
        or value.get("execution_id") != approval["execution_id"]
        or value.get("execution_result_sha256") != approval["execution_result_sha256"]
        or value.get("source_snapshot") != approval["source_snapshot"]
        or value.get("git_identity") != approval["git_identity"]
        or value.get("target_ref") != approval["target_ref"]
        or value.get("parent_revision") != approval["expected_parent_revision"]
        or value.get("commit_policy") != approval["commit_policy"]
        or value.get("branch_created") is not True
        or value.get("checkout_performed") is not False
        or value.get("hooks_executed") is not False
        or value.get("working_tree_writes") is not False
        or value.get("live_source_writes") is not False
        or value.get("pushed") is not False
        or value.get("merged") is not False
        or value.get("deployed") is not False
        or value.get("eligible_for_canary_review") is not True
        or value.get("eligible_for_live_activation") is not False
        or value.get("authority_granted") is not False
    ):
        raise ApplicationError("application result violates its containment contract")
    _require_object_id(value.get("tree_oid"), "application tree")
    _require_object_id(value.get("commit_oid"), "application commit")
    expected_length = 40 if approval["git_identity"]["object_format"] == "sha1" else 64
    if (
        len(value["tree_oid"]) != expected_length
        or len(value["commit_oid"]) != expected_length
    ):
        raise ApplicationError("application result object format is inconsistent")
    try:
        applied = parse_utc_timestamp(value.get("applied_at"), "applied_at")
        issued = parse_utc_timestamp(approval["issued_at"], "issued_at")
        expires = parse_utc_timestamp(
            approval["challenge_expires_at"], "challenge_expires_at"
        )
    except VerificationError as exc:
        raise ApplicationError(str(exc)) from exc
    if applied < issued or applied > expires:
        raise ApplicationError("application result time is outside its approval")
    return copy.deepcopy(value)


def build_signed_application_result(
    *,
    approval: dict[str, Any],
    approval_signature: str,
    approval_key: VerifierKey,
    writer_receipt: dict[str, Any],
    applied_at: str,
    signer_key: VerifierKey,
) -> dict[str, Any]:
    validated = validate_application_approval(approval)
    if not verify_application_approval_signature(
        validated, approval_signature, approval_key
    ):
        raise ApplicationError(
            "application result received an invalid approval signature"
        )
    expected_signer = validated["result_signer"]
    if (
        signer_key.verifier_id != expected_signer["id"]
        or signer_key.key_id != expected_signer["key_id"]
    ):
        raise ApplicationError("application result signer does not match its approval")
    expected_receipt = {
        "backend",
        "object_format",
        "parent_revision",
        "tree_oid",
        "commit_oid",
        "target_ref",
        "branch_created",
        "checkout_performed",
        "hooks_executed",
        "working_tree_writes",
        "live_source_writes",
        "pushed",
        "merged",
        "deployed",
    }
    if not isinstance(writer_receipt, dict) or set(writer_receipt) != expected_receipt:
        raise ApplicationError("Git application receipt is malformed")
    record = {
        "schema": APPLICATION_RESULT_SCHEMA,
        "application_result_id": f"siar-{uuid.uuid4().hex}",
        "approval": copy.deepcopy(validated),
        "approval_signature": application_signature_record(
            validated, approval_signature
        ),
        "application_id": validated["application_id"],
        "application_approval_sha256": application_approval_sha256(validated),
        "challenge_id": validated["challenge_id"],
        "proposal_id": validated["proposal_id"],
        "proposal_content_sha256": validated["proposal_content_sha256"],
        "candidate_id": validated["candidate_id"],
        "candidate_sha256": validated["candidate_sha256"],
        "execution_id": validated["execution_id"],
        "execution_result_sha256": validated["execution_result_sha256"],
        "source_snapshot": copy.deepcopy(validated["source_snapshot"]),
        "git_identity": copy.deepcopy(validated["git_identity"]),
        "target_ref": writer_receipt.get("target_ref"),
        "parent_revision": writer_receipt.get("parent_revision"),
        "tree_oid": writer_receipt.get("tree_oid"),
        "commit_oid": writer_receipt.get("commit_oid"),
        "applied_at": applied_at,
        "commit_policy": copy.deepcopy(validated["commit_policy"]),
        "branch_created": writer_receipt.get("branch_created") is True,
        "checkout_performed": writer_receipt.get("checkout_performed") is True,
        "hooks_executed": writer_receipt.get("hooks_executed") is True,
        "working_tree_writes": writer_receipt.get("working_tree_writes") is True,
        "live_source_writes": writer_receipt.get("live_source_writes") is True,
        "pushed": writer_receipt.get("pushed") is True,
        "merged": writer_receipt.get("merged") is True,
        "deployed": writer_receipt.get("deployed") is True,
        "eligible_for_canary_review": True,
        "eligible_for_live_activation": False,
        "authority_granted": False,
    }
    validate_application_result_shape(record)
    record["result_sha256"] = _sha256(canonical_json_bytes(record))
    payload = canonical_json_bytes(record)
    record["signature"] = {
        "algorithm": SIGNATURE_ALGORITHM,
        "signer_id": signer_key.verifier_id,
        "key_id": signer_key.key_id,
        "value": hmac.new(
            signer_key.secret,
            APPLICATION_RESULT_DOMAIN + payload,
            hashlib.sha256,
        ).hexdigest(),
        "assurance": "symmetric_mac_server_verifiable",
    }
    return record


def validate_signed_application_result(
    value: Any, key_provider: VerifierKeyProvider
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        *validate_application_result_shape_fields(),
        "result_sha256",
        "signature",
    }:
        raise ApplicationError("signed application result fields are malformed")
    unsigned = copy.deepcopy(value)
    signature = unsigned.pop("signature")
    result_digest = unsigned.pop("result_sha256")
    validate_application_result_shape(unsigned)
    _require_sha256(result_digest, "application result")
    if result_digest != _sha256(canonical_json_bytes(unsigned)):
        raise ApplicationError("application result digest is invalid")
    approval = unsigned["approval"]
    approval_signature = unsigned["approval_signature"]
    try:
        approval_key = key_provider(
            approval_signature["reviewer_id"], approval_signature["key_id"]
        )
    except Exception as exc:
        raise ApplicationError(
            "application reviewer key registry is unavailable"
        ) from exc
    if not isinstance(
        approval_key, VerifierKey
    ) or not verify_application_approval_signature(
        approval, approval_signature["value"], approval_key
    ):
        raise ApplicationError("recorded application approval signature is invalid")
    if (
        not isinstance(signature, dict)
        or set(signature) != {"algorithm", "signer_id", "key_id", "value", "assurance"}
        or signature.get("algorithm") != SIGNATURE_ALGORITHM
        or signature.get("assurance") != "symmetric_mac_server_verifiable"
        or not isinstance(signature.get("signer_id"), str)
        or not isinstance(signature.get("key_id"), str)
        or not isinstance(signature.get("value"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", signature["value"])
    ):
        raise ApplicationError("application result signature is malformed")
    expected_signer = approval["result_signer"]
    if (
        signature["signer_id"] != expected_signer["id"]
        or signature["key_id"] != expected_signer["key_id"]
    ):
        raise ApplicationError("application result signer does not match its approval")
    try:
        key = key_provider(signature["signer_id"], signature["key_id"])
    except Exception as exc:
        raise ApplicationError(
            "application result signing key registry is unavailable"
        ) from exc
    if (
        not isinstance(key, VerifierKey)
        or key.verifier_id != signature["signer_id"]
        or key.key_id != signature["key_id"]
    ):
        raise ApplicationError("application result signing key is unavailable")
    expected = hmac.new(
        key.secret,
        APPLICATION_RESULT_DOMAIN
        + canonical_json_bytes({**unsigned, "result_sha256": result_digest}),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature["value"]):
        raise ApplicationError("application result signature is invalid")
    return copy.deepcopy(value)


def validate_application_result_shape_fields() -> set[str]:
    """Return fields used by the unsigned result without accepting input."""
    return {
        "schema",
        "application_result_id",
        "approval",
        "approval_signature",
        "application_id",
        "application_approval_sha256",
        "challenge_id",
        "proposal_id",
        "proposal_content_sha256",
        "candidate_id",
        "candidate_sha256",
        "execution_id",
        "execution_result_sha256",
        "source_snapshot",
        "git_identity",
        "target_ref",
        "parent_revision",
        "tree_oid",
        "commit_oid",
        "applied_at",
        "commit_policy",
        "branch_created",
        "checkout_performed",
        "hooks_executed",
        "working_tree_writes",
        "live_source_writes",
        "pushed",
        "merged",
        "deployed",
        "eligible_for_canary_review",
        "eligible_for_live_activation",
        "authority_granted",
    }


__all__ = [
    "APPLICATION_SIGNER_ID_ENV",
    "APPLICATION_VALIDITY",
    "ApplicationError",
    "ApplicationWriter",
    "GitPlumbingApplicationWriter",
    "application_approval_sha256",
    "application_contract",
    "application_signature_record",
    "application_signing_input_b64",
    "build_application_approval",
    "build_signed_application_result",
    "sign_application_approval",
    "target_ref_for_candidate",
    "validate_application_approval",
    "validate_signed_application_result",
    "verify_application_approval_signature",
]
