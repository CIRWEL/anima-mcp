"""Bounded source awareness and self-iteration proposals for Lumen.

This module deliberately separates *understanding*, *requesting*, quarantined
construction, isolated execution, and reviewed branch creation.  The creature
may inspect a structural map of its source, persist an evidence-backed
proposal, construct a proposal-bound whole-file patch outside the repository,
run non-executing static checks, execute one narrowly eligible Python candidate
in a digest-pinned networkless Docker container after separate signed approval,
and create one reviewed commit on a dedicated Git branch without checkout.  It
may request one signed transient canary from an external supervisor that must
restore the baseline. It never edits the live worktree, executes candidate code
in the host process, retains live activation, pushes, merges, or deploys code.

The boundary is architectural rather than prompt-based. Its only repository
writes are immutable Git objects and one create-only dedicated ref; it exposes
no live-worktree, checkout, push, merge, restart, or deployment action. Other
writes are an atomic ledger and quarantined artifacts under ``~/.anima``.
"""

from __future__ import annotations

import ast
import copy
import fnmatch
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

from .atomic_write import atomic_json_write
from .self_iteration_application import (
    APPLICATION_SIGNER_ID_ENV,
    ApplicationError,
    ApplicationWriter,
    GitPlumbingApplicationWriter,
    application_approval_sha256,
    application_contract,
    application_signature_record,
    application_signing_input_b64,
    build_application_approval,
    build_signed_application_result,
    target_ref_for_candidate,
    validate_application_approval,
    validate_signed_application_result,
    verify_application_approval_signature,
)
from .self_iteration_canary import (
    CANARY_SIGNER_ID_ENV,
    CanaryError,
    CanarySupervisor,
    UnixSocketCanarySupervisor,
    build_canary_approval,
    build_canary_request,
    canary_approval_sha256,
    canary_contract,
    canary_signature_record,
    canary_signing_input_b64,
    validate_canary_approval,
    validate_signed_canary_result,
    validate_supervisor_identity,
    verify_canary_approval_signature,
)
from .self_iteration_execution import (
    RUNNER_SIGNER_ID_ENV,
    DockerIsolationRunner,
    ExecutionError,
    IsolationRunner,
    SourceWorkspaceBuilder,
    approval_signature_record,
    approval_signing_input_b64,
    build_execution_approval,
    build_signed_execution_result,
    execution_approval_sha256,
    execution_contract,
    execution_profile,
    validate_execution_approval,
    validate_signed_execution_result,
    verify_execution_approval_signature,
)
from .self_iteration_verification import (
    ATTESTATION_SCHEMA,
    MAX_ATTESTATION_VALIDITY,
    SIGNATURE_ALGORITHM,
    VerificationError,
    VerifierKey,
    VerifierKeyProvider,
    authenticated_identity,
    attestation_signing_input_b64,
    build_attestation,
    canonical_json_bytes,
    evaluate_verification,
    parse_utc_timestamp,
    proposal_content_sha256,
    proposal_subject_fingerprint,
    validate_evidence,
    validate_recorded_attestation,
    verification_contract,
    verifier_key_from_env,
    verify_attestation_signature,
)
from .self_iteration_sandbox import (
    STATIC_EVALUATOR_ID,
    PatchSandbox,
    PatchSandboxError,
    sandbox_contract,
)

SCHEMA_VERSION = 7
APPLICATION_SCHEMA_VERSION = 6
EXECUTION_SCHEMA_VERSION = 5
SANDBOX_SCHEMA_VERSION = 4
VERIFICATION_SCHEMA_VERSION = 3
PROVENANCE_SCHEMA_VERSION = 2
PROVENANCE_SCHEMA = "anima.self_iteration.provenance.v1"
MAX_INSPECT_BYTES = 1_000_000
MAX_FILE_DETAILS = 200

_SOURCE_SUFFIXES = {
    ".ex": "elixir",
    ".exs": "elixir",
    ".html": "html",
    ".js": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".py": "python",
    ".service": "systemd",
    ".sh": "shell",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
}

_SOURCE_ROOTS = (
    ".github",
    "src",
    "anima_broker",
    "docs",
    "scripts",
    "systemd",
    "tests",
)

_ROOT_SOURCE_FILES = {
    "README.md",
    "anima_config.yaml",
    "docker-compose.yml",
    "mkdocs.yml",
    "pyproject.toml",
    "uv.lock",
}

# These surfaces define identity continuity, safety/governance, deployment,
# persistence correctness, or the evaluator itself.  A proposal may name them
# (Lumen should be able to notice a problem anywhere), but it is always routed
# to protected human review.
_PROTECTED_RULES: tuple[tuple[str, str], ...] = (
    (".git/**", "repository integrity"),
    (".github/**", "independent CI evaluator"),
    ("tests/**", "independent test evaluator"),
    ("systemd/**", "process and recovery control"),
    ("scripts/**", "operator and deployment control"),
    ("pyproject.toml", "dependency and executable boundary"),
    ("uv.lock", "dependency supply-chain boundary"),
    ("src/anima_mcp/admin_auth.py", "authorization boundary"),
    ("src/anima_mcp/atomic_write.py", "persistence integrity"),
    ("src/anima_mcp/governance_passthrough.py", "governance boundary"),
    ("src/anima_mcp/unitares_bridge.py", "governance boundary"),
    ("src/anima_mcp/identity/**", "persistent identity continuity"),
    ("src/anima_mcp/trajectory.py", "identity trajectory continuity"),
    ("src/anima_mcp/lifecycle.py", "wake and recovery lifecycle"),
    ("src/anima_mcp/server.py", "runtime lifecycle"),
    ("src/anima_mcp/tool_registry.py", "capability boundary"),
    ("src/anima_mcp/handlers/system_ops.py", "deployment and system control"),
    ("src/anima_mcp/self_iteration.py", "self-iteration evaluator"),
    (
        "src/anima_mcp/self_iteration_application.py",
        "reviewed Git application boundary",
    ),
    (
        "src/anima_mcp/self_iteration_canary.py",
        "transient canary supervisor boundary",
    ),
    ("src/anima_mcp/self_iteration_execution.py", "isolated execution boundary"),
    ("src/anima_mcp/self_iteration_sandbox.py", "self-iteration evaluator"),
    ("src/anima_mcp/self_iteration_verification.py", "self-iteration evaluator"),
    ("src/anima_mcp/handlers/self_iteration.py", "self-iteration evaluator"),
    ("src/anima_mcp/anima.py", "embodied self-measurement boundary"),
    ("src/anima_mcp/config.py", "calibration boundary"),
    ("src/anima_mcp/self_model.py", "self-perception boundary"),
    ("src/anima_mcp/eisv_mapper.py", "self-measurement boundary"),
    ("src/anima_mcp/inner_life.py", "drive and need boundary"),
    ("src/anima_mcp/metacognition.py", "self-evaluation boundary"),
    ("src/anima_mcp/value_tension.py", "value-conflict boundary"),
    ("src/anima_mcp/preferences.py", "persistent preference integrity"),
    ("src/anima_mcp/self_reflection.py", "reflection evidence integrity"),
    ("src/anima_mcp/data_analysis.py", "self-analysis boundary"),
    ("src/anima_mcp/growth/**", "persistent goals and autobiography"),
    ("src/anima_mcp/memory.py", "persistent memory continuity"),
    ("src/anima_mcp/knowledge.py", "persistent knowledge integrity"),
    ("src/anima_mcp/oauth_*.py", "authentication boundary"),
    ("src/anima_mcp/rest_api.py", "remote interface boundary"),
    ("anima_broker/lib/**/governance/**", "governance boundary"),
)

# Autonomous candidate eligibility is intentionally narrow. Every later stage
# revalidates this allowlist and adds its own signed, no-authority boundary.
_AUTO_ELIGIBLE_RULES: tuple[tuple[str, str], ...] = (
    ("docs/**", "documentation-only"),
    ("README.md", "documentation-only"),
    ("src/anima_mcp/display/eras/**", "sandboxed art-era behavior"),
)

_SENSITIVE_RULES = (
    ".env*",
    "**/.env*",
    "**/*.key",
    "**/*.pem",
    "**/*secret*",
    "scripts/envelope*",
)

_ARCHITECTURE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "embodiment",
        "Sensors and mappings that ground warmth, clarity, stability, and presence.",
        (
            "src/anima_mcp/anima.py",
            "src/anima_mcp/eisv_mapper.py",
            "src/anima_mcp/sensors/**",
        ),
    ),
    (
        "identity",
        "Persistent identity, autobiography, memory, and longitudinal trajectory.",
        (
            "src/anima_mcp/identity/**",
            "src/anima_mcp/growth/**",
            "src/anima_mcp/memory.py",
            "src/anima_mcp/trajectory.py",
        ),
    ),
    (
        "learning",
        "Predictions, preferences, reflection, agency, and the behavioral self-model.",
        (
            "src/anima_mcp/adaptive_prediction.py",
            "src/anima_mcp/agency.py",
            "src/anima_mcp/preferences.py",
            "src/anima_mcp/self_model.py",
            "src/anima_mcp/self_reflection.py",
        ),
    ),
    (
        "expression",
        "Face, drawing, primitive language, voice, and display behavior.",
        (
            "src/anima_mcp/display/**",
            "src/anima_mcp/primitive_language.py",
            "src/anima_mcp/audio/**",
        ),
    ),
    (
        "interface",
        "MCP tools, handlers, REST endpoints, and runtime orchestration.",
        (
            "src/anima_mcp/server.py",
            "src/anima_mcp/tool_registry.py",
            "src/anima_mcp/handlers/**",
            "src/anima_mcp/rest_api.py",
        ),
    ),
    (
        "governance",
        "UNITARES check-ins and EISV governance integration.",
        (
            "src/anima_mcp/unitares_bridge.py",
            "src/anima_mcp/governance_passthrough.py",
            "anima_broker/lib/**/governance/**",
        ),
    ),
    (
        "operations",
        "Service definitions, deployment helpers, and recovery controls.",
        ("systemd/**", "scripts/**", "src/anima_mcp/handlers/system_ops.py"),
    ),
    (
        "evaluation",
        "Independent tests and continuous-integration checks used to judge changes.",
        ("tests/**", ".github/**"),
    ),
)

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

_V3_PROPOSAL_FIELDS = {
    "id",
    "created_at",
    "source_claim",
    "provenance",
    "proposer_identity",
    "trust_policy",
    "status",
    "observation",
    "hypothesis",
    "expected_outcome",
    "evidence",
    "evidence_epistemic_status",
    "target_paths",
    "verification",
    "rollback_plan",
    "risk",
    "boundaries",
    "code_fingerprint",
    "implementation_policy",
    "events",
    "content_sha256",
}

_PROPOSAL_STATUSES = {
    "protected_review_required",
    "human_review_required",
    "ready_for_isolated_implementation",
    "retained",
    "reverted",
    "measurement_inconclusive",
}


class SelfIterationError(ValueError):
    """Raised when an inspection or ledger operation violates its contract."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _current_request_headers() -> dict[str, str] | None:
    """Return server-observed MCP headers, never caller arguments."""
    try:
        from mcp.server.lowlevel.server import request_ctx

        ctx = request_ctx.get()
        if ctx.request is not None:
            return {
                str(key).lower(): str(value)
                for key, value in ctx.request.headers.items()
            }
    except (LookupError, AttributeError, ImportError, TypeError):
        pass
    return None


def _current_access_token() -> Any | None:
    """Return an OAuth token only after MCP auth middleware verified it."""
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token

        return get_access_token()
    except (LookupError, AttributeError, ImportError):
        return None


def _collect_server_provenance(recorded_at: str) -> dict[str, Any]:
    """Build a receipt from server context, excluding secrets and raw session IDs.

    Authentication proves which OAuth actor submitted the request.  It does
    not verify any narrative, source label, evidence item, or measurement in
    the request; those remain explicit caller claims.
    """
    headers = _current_request_headers()
    token = _current_access_token()

    actor = None
    if token is not None:
        subject = getattr(token, "subject", None)
        client_id = getattr(token, "client_id", None)
        claims = getattr(token, "claims", None) or {}
        issuer = claims.get("iss") if isinstance(claims, dict) else None
        scopes = getattr(token, "scopes", None) or []
        if subject or client_id:
            actor = {
                "kind": "oauth_subject" if subject else "oauth_client",
                "id": subject or client_id,
                "client_id": client_id,
                "issuer": issuer if isinstance(issuer, str) else None,
                "scopes": sorted(str(scope) for scope in scopes),
                "verified": True,
            }

    session_id = None
    if headers:
        session_id = headers.get("mcp-session-id") or headers.get("x-session-id")
    session = {
        "present": bool(session_id),
        "identifier_sha256": (
            hashlib.sha256(session_id.encode("utf-8")).hexdigest()
            if session_id
            else None
        ),
        "source": "server_observed_transport_header" if session_id else "none",
        "verified": False,
        "request_actor_verified": actor is not None,
        "note": "A transport session observation is not identity proof.",
    }

    return {
        "schema": PROVENANCE_SCHEMA,
        "recorded_by": "anima-mcp",
        "recorded_at": recorded_at,
        "transport": {
            "kind": "mcp_http" if headers is not None else "internal_or_test",
            "server_observed": headers is not None,
        },
        "authentication": {
            "method": "oauth_bearer" if actor else "none",
            "verified": actor is not None,
        },
        "actor": actor,
        "session": session,
        "integrity": {
            "tamper_evident": False,
            "cryptographically_signed": False,
            "note": "The local receipt is not a durable attestation.",
        },
        "trust": {
            "classification": (
                "authenticated_request_unverified_claims"
                if actor
                else "unverified_request"
            ),
            "actor_authenticated": actor is not None,
            "claims_verified": False,
            "evidence_verified": False,
            "weighting_eligible": False,
            "authority_eligible": False,
        },
    }


def _claim_envelope(value: Any, *, field: str, legacy: bool = False) -> dict[str, Any]:
    return {
        "field": field,
        "value": value,
        "epistemic_status": "caller_claimed_legacy" if legacy else "caller_claimed",
        "verified": False,
        "authority_granted": False,
    }


def _zero_weight_trust_policy(*, legacy: bool = False) -> dict[str, Any]:
    return {
        "effective_weight": 0.0,
        "priority_eligible": False,
        "automation_eligible": False,
        "authority_eligible": False,
        "evidence_status": "caller_asserted_legacy" if legacy else "caller_asserted",
        "reason": (
            "Legacy provenance is unavailable; claims are unverified."
            if legacy
            else "Request provenance identifies receipt context, not claim truth."
        ),
        "upgrade_required": (
            "An independent verifier must append a verification event before "
            "any policy may assign weight or authority."
        ),
    }


def _provenance_contract() -> dict[str, Any]:
    return {
        "schema": PROVENANCE_SCHEMA,
        "caller_labels_are_claims_only": True,
        "server_receipts_verify_request_context_only": True,
        "ledger_receipts_tamper_evident": False,
        "unverified_effective_weight": 0.0,
        "unverified_priority_eligible": False,
        "unverified_automation_eligible": False,
        "unverified_authority_eligible": False,
        "verification_upgrade": "independent_append_only_event_required",
    }


def _legacy_provenance(recorded_at: str | None, *, migrated_at: str) -> dict[str, Any]:
    return {
        "schema": PROVENANCE_SCHEMA,
        "recorded_by": "legacy_v1_migration",
        "recorded_at": recorded_at,
        "recorded_at_verified": False,
        "migration_observed_at": migrated_at,
        "transport": {"kind": "unknown", "server_observed": False},
        "authentication": {"method": "unknown", "verified": False},
        "actor": None,
        "integrity": {
            "tamper_evident": False,
            "cryptographically_signed": False,
            "note": "Schema v1 had no durable provenance attestation.",
        },
        "session": {
            "present": False,
            "identifier_sha256": None,
            "source": "legacy_unknown",
            "verified": False,
            "request_actor_verified": False,
            "note": "No trustworthy session provenance was stored in schema v1.",
        },
        "trust": {
            "classification": "legacy_unverified",
            "actor_authenticated": False,
            "claims_verified": False,
            "evidence_verified": False,
            "weighting_eligible": False,
            "authority_eligible": False,
        },
    }


def _discover_repo_root() -> Path | None:
    """Find the source tree without trusting caller-supplied paths."""
    override = os.environ.get("ANIMA_SOURCE_ROOT")
    candidates = []
    if override:
        candidates.append(Path(override).expanduser())
    candidates.extend((Path(__file__).resolve(), Path.cwd().resolve()))

    for candidate in candidates:
        start = candidate if candidate.is_dir() else candidate.parent
        for parent in (start, *start.parents):
            if (parent / "pyproject.toml").is_file() and (
                parent / "src" / "anima_mcp"
            ).is_dir():
                return parent.resolve()
    return None


def _normalize_repo_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SelfIterationError("path must be a non-empty repository-relative string")
    raw = value.strip().replace("\\", "/")
    if "\x00" in raw or raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        raise SelfIterationError("path must stay inside the source repository")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SelfIterationError("path may not contain empty, '.' or '..' segments")
    normalized = str(PurePosixPath(raw))
    if normalized == ".":
        raise SelfIterationError("path must name a file or directory")
    return normalized


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern)


def _rule_reasons(path: str, rules: Iterable[tuple[str, str]]) -> list[str]:
    return [reason for pattern, reason in rules if _matches(path, pattern)]


def _is_sensitive(path: str) -> bool:
    return any(_matches(path, pattern) for pattern in _SENSITIVE_RULES)


def _is_source_candidate(path: Path, relative: str) -> bool:
    if relative in _ROOT_SOURCE_FILES:
        return True
    if not relative.startswith(tuple(f"{root}/" for root in _SOURCE_ROOTS)):
        return False
    return path.suffix.lower() in _SOURCE_SUFFIXES


def _safe_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _required_text(value: Any, field: str, *, max_length: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SelfIterationError(f"{field} must be a non-empty string")
    result = value.strip()
    if len(result) > max_length:
        raise SelfIterationError(f"{field} must be at most {max_length} characters")
    return result


def _string_list(
    value: Any,
    field: str,
    *,
    required: bool = True,
    max_items: int = 20,
    item_max_length: int = 1000,
) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list) or (required and not value):
        requirement = "a non-empty list" if required else "a list"
        raise SelfIterationError(f"{field} must be {requirement} of strings")
    if len(value) > max_items:
        raise SelfIterationError(f"{field} may contain at most {max_items} items")
    return [_required_text(item, field, max_length=item_max_length) for item in value]


class SelfIterationSystem:
    """Read source structure and maintain an auditable proposal ledger."""

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        ledger_path: Path | None = None,
        sandbox_root: Path | None = None,
        clock: Callable[[], datetime] = _utc_now,
        provenance_provider: Callable[
            [str], dict[str, Any]
        ] = _collect_server_provenance,
        verifier_key_provider: VerifierKeyProvider = verifier_key_from_env,
        isolation_runner: IsolationRunner | None = None,
        workspace_builder: SourceWorkspaceBuilder | None = None,
        application_writer: ApplicationWriter | None = None,
        canary_supervisor: CanarySupervisor | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve() if repo_root else _discover_repo_root()
        self.ledger_path = ledger_path or Path.home() / ".anima" / "self_iteration.json"
        self.sandbox_root = (
            sandbox_root
            if sandbox_root is not None
            else Path.home() / ".anima" / "self_iteration_sandboxes"
        )
        self._clock = clock
        self._provenance_provider = provenance_provider
        self._verifier_key_provider = verifier_key_provider
        self._isolation_runner = (
            isolation_runner or DockerIsolationRunner.from_environment()
        )
        self._workspace_builder = workspace_builder or SourceWorkspaceBuilder()
        self._application_writer = (
            application_writer or GitPlumbingApplicationWriter.from_environment()
        )
        self._canary_supervisor = (
            canary_supervisor or UnixSocketCanarySupervisor.from_environment()
        )
        self._patch_sandbox = PatchSandbox(
            repo_root=self.repo_root,
            sandbox_root=self.sandbox_root,
        )
        self._lock = threading.RLock()

    def _server_provenance(self, recorded_at: str) -> dict[str, Any]:
        """Collect a server-controlled receipt and pin every claim trust bit false."""
        try:
            receipt = copy.deepcopy(self._provenance_provider(recorded_at))
        except Exception as exc:
            raise SelfIterationError(
                "server provenance is unavailable; refusing to persist the record"
            ) from exc
        if (
            not isinstance(receipt, dict)
            or receipt.get("schema") != PROVENANCE_SCHEMA
            or not isinstance(receipt.get("recorded_by"), str)
        ):
            raise SelfIterationError(
                "server provenance is malformed; refusing to persist the record"
            )

        receipt["recorded_at"] = recorded_at
        receipt["integrity"] = {
            "tamper_evident": False,
            "cryptographically_signed": False,
            "note": "The local receipt is not a durable attestation.",
        }
        authentication = receipt.get("authentication")
        actor = receipt.get("actor")
        actor_authenticated = bool(
            isinstance(authentication, dict)
            and authentication.get("verified") is True
            and isinstance(actor, dict)
            and actor.get("verified") is True
            and actor.get("id")
        )
        trust = receipt.get("trust")
        if not isinstance(trust, dict):
            trust = {}
        trust.update(
            {
                "classification": (
                    "authenticated_request_unverified_claims"
                    if actor_authenticated
                    else "unverified_request"
                ),
                "actor_authenticated": actor_authenticated,
                "claims_verified": False,
                "evidence_verified": False,
                "weighting_eligible": False,
                "authority_eligible": False,
            }
        )
        receipt["trust"] = trust
        return receipt

    @staticmethod
    def _identity_from_provenance(
        provenance: Any, *, label: str, required: bool
    ) -> dict[str, str | None] | None:
        trust = provenance.get("trust") if isinstance(provenance, dict) else None
        claims_authenticated_actor = bool(
            isinstance(trust, dict) and trust.get("actor_authenticated") is True
        )
        if not claims_authenticated_actor and not required:
            return None
        try:
            return authenticated_identity(provenance)
        except VerificationError as exc:
            if required:
                raise SelfIterationError(
                    f"{label} lacks authenticated actor provenance"
                ) from exc
            raise SelfIterationError(f"{label} actor provenance is malformed") from exc

    def _resolve_verifier_key(
        self,
        verifier_identity: dict[str, str | None],
        key_id: str | None = None,
    ) -> VerifierKey:
        verifier_id = verifier_identity["id"]
        assert isinstance(verifier_id, str)
        try:
            key = self._verifier_key_provider(verifier_id, key_id)
        except Exception as exc:
            raise SelfIterationError(
                "verifier key registry is unavailable or malformed"
            ) from exc
        if key is None:
            raise SelfIterationError(
                "no signing key is configured for the authenticated verifier"
            )
        if (
            not isinstance(key, VerifierKey)
            or key.verifier_id != verifier_id
            or not isinstance(key.key_id, str)
            or not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", key.key_id)
            or not isinstance(key.secret, bytes)
            or not 32 <= len(key.secret) <= 128
            or (key_id is not None and key.key_id != key_id)
        ):
            raise SelfIterationError("verifier key registry returned a mismatched key")
        return key

    def _git_metadata(self) -> dict[str, Any]:
        if self.repo_root is None:
            return {"available": False, "reason": "source repository not found"}

        revision_result = _safe_git(self.repo_root, "rev-parse", "HEAD")
        if revision_result is None or revision_result.returncode != 0:
            return {
                "available": False,
                "reason": "Git metadata unavailable; source may be a packaged deployment",
            }

        branch_result = _safe_git(self.repo_root, "branch", "--show-current")
        status_result = _safe_git(
            self.repo_root,
            "status",
            "--porcelain",
            "--untracked-files=normal",
        )
        revision = revision_result.stdout.strip()
        branch = (
            branch_result.stdout.strip()
            if branch_result and branch_result.returncode == 0
            else None
        )
        dirty = (
            None
            if status_result is None or status_result.returncode != 0
            else bool(status_result.stdout.strip())
        )
        return {
            "available": True,
            "revision": revision,
            "short_revision": revision[:12],
            "branch": branch or "detached",
            "working_tree_changes_present": dirty,
        }

    def _tracked_source_files(self) -> list[tuple[str, Path]]:
        if self.repo_root is None:
            return []

        relative_paths: list[str] = []
        tracked = _safe_git(
            self.repo_root,
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        )
        if tracked is not None and tracked.returncode == 0:
            relative_paths = [item for item in tracked.stdout.split("\x00") if item]
        else:
            for root_name in (*_SOURCE_ROOTS,):
                root = self.repo_root / root_name
                if root.exists():
                    relative_paths.extend(
                        str(path.relative_to(self.repo_root).as_posix())
                        for path in root.rglob("*")
                        if path.is_file()
                    )
            relative_paths.extend(
                name for name in _ROOT_SOURCE_FILES if (self.repo_root / name).is_file()
            )

        repo_resolved = self.repo_root.resolve()
        files: list[tuple[str, Path]] = []
        for raw_relative in sorted(set(relative_paths)):
            try:
                relative = _normalize_repo_path(raw_relative)
            except SelfIterationError:
                continue
            path = self.repo_root / relative
            try:
                resolved = path.resolve()
                resolved.relative_to(repo_resolved)
            except (OSError, ValueError):
                continue
            if not path.is_file() or path.is_symlink() or _is_sensitive(relative):
                continue
            if _is_source_candidate(path, relative):
                files.append((relative, path))
        return files

    @staticmethod
    def _package_version(repo_root: Path | None) -> str | None:
        try:
            return importlib.metadata.version("anima-mcp")
        except importlib.metadata.PackageNotFoundError:
            pass
        if repo_root is not None:
            pyproject = repo_root / "pyproject.toml"
            try:
                match = re.search(
                    r'^version\s*=\s*"([^"]+)"', pyproject.read_text(), re.MULTILINE
                )
                if match:
                    return match.group(1)
            except OSError:
                pass
        return None

    def _manifest(self, *, include_files: bool, file_limit: int) -> dict[str, Any]:
        digest = hashlib.sha256()
        total_bytes = 0
        total_lines = 0
        languages: dict[str, int] = {}
        relative_paths: list[str] = []
        details: list[dict[str, Any]] = []

        for relative, path in self._tracked_source_files():
            try:
                data = path.read_bytes()
            except OSError:
                continue
            file_digest = hashlib.sha256(data).hexdigest()
            lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
            digest.update(relative.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(file_digest.encode("ascii"))
            digest.update(b"\n")
            total_bytes += len(data)
            total_lines += lines
            relative_paths.append(relative)
            language = _SOURCE_SUFFIXES.get(path.suffix.lower(), "other")
            languages[language] = languages.get(language, 0) + 1
            if include_files and len(details) < file_limit:
                protected_reasons = _rule_reasons(relative, _PROTECTED_RULES)
                details.append(
                    {
                        "path": relative,
                        "sha256": file_digest,
                        "bytes": len(data),
                        "lines": lines,
                        "protected": bool(protected_reasons),
                    }
                )

        architecture = []
        for name, purpose, patterns in _ARCHITECTURE:
            matches = [
                relative
                for relative in relative_paths
                if any(_matches(relative, pattern) for pattern in patterns)
            ]
            architecture.append(
                {
                    "name": name,
                    "purpose": purpose,
                    "file_count": len(matches),
                    "example_paths": matches[:5],
                }
            )

        result: dict[str, Any] = {
            "sha256": digest.hexdigest(),
            "file_count": len(relative_paths),
            "total_bytes": total_bytes,
            "total_lines": total_lines,
            "languages": dict(sorted(languages.items())),
            "architecture": architecture,
        }
        if include_files:
            result["files"] = details
            result["files_truncated"] = len(relative_paths) > len(details)
        return result

    def inspect(
        self,
        *,
        path: str | None = None,
        include_files: bool = False,
        file_limit: int = 100,
    ) -> dict[str, Any]:
        """Return a structural view of the running source tree."""
        if (
            isinstance(file_limit, bool)
            or not isinstance(file_limit, int)
            or not 1 <= file_limit <= MAX_FILE_DETAILS
        ):
            raise SelfIterationError(
                f"file_limit must be between 1 and {MAX_FILE_DETAILS}"
            )
        if path is not None:
            return self._inspect_path(path)

        git = self._git_metadata()
        manifest = self._manifest(include_files=include_files, file_limit=file_limit)
        return {
            "mode": "bounded_self_iteration",
            "autonomy_level": "signed_transient_canary_evaluation",
            "runtime": {
                "package": "anima-mcp",
                "package_version": self._package_version(self.repo_root),
                "python": platform.python_version(),
                "platform": platform.system().lower(),
            },
            "source": {
                "available": self.repo_root is not None,
                "git": git,
                "manifest": manifest,
            },
            "capabilities": {
                "inspect_structure": True,
                "persist_change_proposals": True,
                "record_measured_outcomes": True,
                "prepare_signed_verification": True,
                "record_signed_verification": True,
                "construct_quarantined_patch_artifacts": True,
                "run_nonexecuting_static_evaluation": True,
                "prepare_signed_execution_approval": True,
                "prepare_signed_application_review": True,
                "prepare_signed_transient_canary_review": True,
                "execute_candidate_code_on_host": False,
                "execute_candidate_code_in_pinned_container": True,
                "execute_tests_in_pinned_container": True,
                "accept_caller_supplied_provenance": False,
                "weight_unverified_ledger_claims": False,
                "verification_grants_implementation_authority": False,
                "write_source": False,
                "write_live_worktree": False,
                "create_reviewed_dedicated_branch": True,
                "request_external_transient_canary": True,
                "retain_persistent_activation": False,
                "execute_proposal_text": False,
                "execute_candidate_code": True,
                "execute_tests": True,
                "create_commit": True,
                "push": False,
                "deploy": False,
            },
            "boundaries": {
                "protected_surfaces": [
                    {"pattern": pattern, "reason": reason}
                    for pattern, reason in _PROTECTED_RULES
                ],
                "initial_auto_eligible_surfaces": [
                    {"pattern": pattern, "reason": reason}
                    for pattern, reason in _AUTO_ELIGIBLE_RULES
                ],
                "implementation_rule": (
                    "This process may construct an inert patch artifact, run static parsers, "
                    "orchestrate one externally approved fixed test profile in a local "
                    "Docker boundary, and create one separately reviewed dedicated Git "
                    "branch. It may request one separately reviewed transient canary from "
                    "an external supervisor that must restore the baseline. A caretaker "
                    "still owns merge and deployment."
                ),
                "provenance_rule": (
                    "Caller labels, narratives, and evidence remain zero-weight claims. "
                    "Authentication identifies a submitter only; an independent verifier "
                    "must append a valid signed event before policy can assign priority."
                ),
                "verification_rule": (
                    "A valid HMAC attestation must bind a distinct authenticated verifier, "
                    "proposal digest, source fingerprint, evidence digests, and expiry. "
                    "Verification never grants source-editing, merge, or deployment authority."
                ),
                "sandbox_rule": (
                    "Patch artifacts are whole-file replacements stored outside the source "
                    "repository. Static evaluation is heuristic and never makes a candidate "
                    "eligible for execution."
                ),
                "execution_rule": (
                    "A separate authenticated approver must sign a ten-minute, one-use plan "
                    "that binds a passing static evaluation, clean committed source, fixed "
                    "test profile, and locally present digest-pinned Docker image. Execution "
                    "has no host fallback, network, secrets, source writes, apply, merge, or "
                    "deployment authority."
                ),
                "application_rule": (
                    "A new authenticated reviewer must sign a ten-minute, one-use plan "
                    "bound to one passing signed execution. Application uses Git plumbing "
                    "and a temporary index to create only a server-derived dedicated branch; "
                    "it performs no checkout, hooks, worktree writes, push, merge, restart, "
                    "or deployment."
                ),
                "canary_rule": (
                    "A new authenticated reviewer must sign a ten-minute, one-use plan "
                    "bound to the exact reviewed branch and a fixed external-supervisor "
                    "profile. The local Unix-socket supervisor owns transient activation, "
                    "fixed health measurement, and mandatory baseline restoration. This "
                    "process has no shell, service-control, persistent activation, push, "
                    "merge, or deployment primitive."
                ),
            },
            "ledger": self._ledger_summary(),
        }

    def _ledger_summary(self) -> dict[str, Any]:
        try:
            with self._lock:
                ledger = self._load_ledger()
            legacy_count = sum(
                1
                for proposal in ledger["proposals"]
                if proposal.get("provenance", {}).get("trust", {}).get("classification")
                == "legacy_unverified"
            )
            states = [
                evaluate_verification(
                    proposal,
                    key_provider=self._verifier_key_provider,
                    now=self._clock(),
                )
                for proposal in ledger["proposals"]
            ]
            return {
                "proposal_count": len(ledger["proposals"]),
                "legacy_unverified_count": legacy_count,
                "verified_count": sum(
                    state["status"] == "verified" for state in states
                ),
                "schema_version": ledger["schema_version"],
                "provenance_contract": ledger["provenance_contract"],
                "verification_contract": ledger["verification_contract"],
                "sandbox_contract": ledger["sandbox_contract"],
                "execution_contract": ledger["execution_contract"],
                "application_contract": ledger["application_contract"],
                "canary_contract": ledger["canary_contract"],
            }
        except SelfIterationError as exc:
            return {
                "schema_version": SCHEMA_VERSION,
                "error": str(exc),
                "writes_allowed": False,
            }

    def _inspect_path(self, raw_path: str) -> dict[str, Any]:
        if self.repo_root is None:
            raise SelfIterationError("source repository not found")
        relative = _normalize_repo_path(raw_path)
        if _is_sensitive(relative) or _matches(relative, ".git/**"):
            raise SelfIterationError("sensitive repository paths cannot be inspected")

        path = self.repo_root / relative
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.repo_root.resolve())
        except (OSError, ValueError) as exc:
            raise SelfIterationError(
                "path does not name a file inside the source repository"
            ) from exc
        if not resolved.is_file() or resolved.is_symlink():
            raise SelfIterationError("path must name a regular source file")
        if not _is_source_candidate(resolved, relative):
            raise SelfIterationError("path is outside the inspectable source surfaces")
        if resolved.stat().st_size > MAX_INSPECT_BYTES:
            raise SelfIterationError(
                f"source file exceeds the {MAX_INSPECT_BYTES}-byte inspection limit"
            )

        data = resolved.read_bytes()
        text = data.decode("utf-8", errors="replace")
        result: dict[str, Any] = {
            "path": relative,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "lines": data.count(b"\n")
            + (1 if data and not data.endswith(b"\n") else 0),
            "language": _SOURCE_SUFFIXES.get(resolved.suffix.lower(), "other"),
            "boundary": self.classify_target(relative),
            "source_body_included": False,
        }

        if resolved.suffix.lower() == ".py":
            result["structure"] = self._python_structure(text)
        elif resolved.suffix.lower() in {".ex", ".exs"}:
            result["structure"] = self._elixir_structure(text)
        else:
            result["structure"] = {
                "note": "structural symbol extraction is not available for this file type"
            }
        return result

    @staticmethod
    def _python_structure(text: str) -> dict[str, Any]:
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            return {"parse_error": f"{exc.msg} at line {exc.lineno}"}

        symbols = []
        imports: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                doc = ast.get_docstring(node, clean=True)
                symbols.append(
                    {
                        "name": node.name,
                        "kind": kind,
                        "line": node.lineno,
                        "end_line": getattr(node, "end_lineno", None),
                        "summary": doc.splitlines()[0][:240] if doc else None,
                    }
                )
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                prefix = "." * node.level
                imports.append(f"{prefix}{node.module or ''}")
        module_doc = ast.get_docstring(tree, clean=True)
        return {
            "module_summary": module_doc.splitlines()[0][:240] if module_doc else None,
            "symbols": symbols,
            "imports": imports[:100],
        }

    @staticmethod
    def _elixir_structure(text: str) -> dict[str, Any]:
        modules = re.findall(r"^\s*defmodule\s+([A-Za-z0-9_.]+)", text, re.MULTILINE)
        functions = [
            {"visibility": visibility, "name": name}
            for visibility, name in re.findall(
                r"^\s*(defp?)\s+([a-zA-Z0-9_!?]+)",
                text,
                re.MULTILINE,
            )
        ]
        return {"modules": modules, "functions": functions[:200]}

    def classify_target(self, raw_path: str) -> dict[str, Any]:
        relative = _normalize_repo_path(raw_path)
        protected_reasons = _rule_reasons(relative, _PROTECTED_RULES)
        if _is_sensitive(relative):
            protected_reasons.append("credential or secret material")
        eligible_reasons = _rule_reasons(relative, _AUTO_ELIGIBLE_RULES)

        if protected_reasons:
            boundary = "protected_core"
            risk = "high"
            auto_eligible = False
        elif eligible_reasons:
            boundary = "bounded_candidate"
            risk = "low"
            auto_eligible = True
        else:
            boundary = "human_review_required"
            risk = "medium"
            auto_eligible = False

        return {
            "path": relative,
            "boundary": boundary,
            "risk_floor": risk,
            "auto_implementation_eligible": auto_eligible,
            "reasons": protected_reasons
            or eligible_reasons
            or ["outside the initial autonomous allowlist"],
        }

    def _empty_ledger(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "provenance_contract": _provenance_contract(),
            "verification_contract": verification_contract(),
            "sandbox_contract": sandbox_contract(),
            "execution_contract": execution_contract(),
            "application_contract": application_contract(),
            "canary_contract": canary_contract(),
            "migrations": [],
            "proposals": [],
        }

    def _migrate_v1(self, data: dict[str, Any]) -> dict[str, Any]:
        """Reclassify schema-v1 attribution as explicit, zero-weight claims."""
        migrated_at = _isoformat(self._clock())
        ledger = copy.deepcopy(data)
        proposals = ledger.get("proposals")
        if not isinstance(proposals, list):
            raise SelfIterationError("self-iteration ledger proposals are malformed")

        for proposal in proposals:
            if not isinstance(proposal, dict):
                raise SelfIterationError(
                    "self-iteration ledger proposals are malformed"
                )
            proposal["source_claim"] = _claim_envelope(
                proposal.pop("source", "unknown"), field="source", legacy=True
            )
            proposal["provenance"] = _legacy_provenance(
                proposal.get("created_at"), migrated_at=migrated_at
            )
            proposal["trust_policy"] = _zero_weight_trust_policy(legacy=True)
            proposal["evidence_epistemic_status"] = "caller_asserted_legacy"

            events = proposal.setdefault("events", [])
            if not isinstance(events, list):
                raise SelfIterationError("self-iteration proposal events are malformed")
            for event in events:
                if not isinstance(event, dict):
                    raise SelfIterationError(
                        "self-iteration proposal events are malformed"
                    )
                if event.get("type") != "outcome_recorded":
                    continue
                event["measurement_source_claim"] = _claim_envelope(
                    event.pop("measurement_source", "unknown"),
                    field="measurement_source",
                    legacy=True,
                )
                event["provenance"] = _legacy_provenance(
                    event.get("at"), migrated_at=migrated_at
                )
                event["trust_policy"] = _zero_weight_trust_policy(legacy=True)
                event["evidence_epistemic_status"] = "caller_asserted_legacy"
            events.append(
                {
                    "type": "provenance_migrated",
                    "at": migrated_at,
                    "from_schema": 1,
                    "to_schema": PROVENANCE_SCHEMA_VERSION,
                    "classification": "legacy_unverified",
                    "authority_granted": False,
                }
            )

        ledger["schema_version"] = PROVENANCE_SCHEMA_VERSION
        ledger["provenance_contract"] = _provenance_contract()
        migrations = ledger.setdefault("migrations", [])
        if not isinstance(migrations, list):
            raise SelfIterationError("self-iteration ledger migrations are malformed")
        migrations.append(
            {
                "type": "schema_migration",
                "at": migrated_at,
                "from_schema": 1,
                "to_schema": PROVENANCE_SCHEMA_VERSION,
                "classification": "legacy_unverified",
            }
        )
        return ledger

    def _migrate_v2(self, data: dict[str, Any]) -> dict[str, Any]:
        """Bind every proposal to immutable content before signed verification."""
        migrated_at = _isoformat(self._clock())
        ledger = copy.deepcopy(data)
        for proposal in ledger["proposals"]:
            proposal["proposer_identity"] = self._identity_from_provenance(
                proposal.get("provenance"),
                label="self-iteration proposal",
                required=False,
            )
            proposal["content_sha256"] = proposal_content_sha256(proposal)
            proposal.setdefault("events", []).append(
                {
                    "type": "verification_schema_migrated",
                    "at": migrated_at,
                    "from_schema": PROVENANCE_SCHEMA_VERSION,
                    "to_schema": VERIFICATION_SCHEMA_VERSION,
                    "verification_status": "unverified",
                    "authority_granted": False,
                }
            )
        ledger["schema_version"] = VERIFICATION_SCHEMA_VERSION
        ledger["verification_contract"] = verification_contract()
        ledger["migrations"].append(
            {
                "type": "schema_migration",
                "at": migrated_at,
                "from_schema": PROVENANCE_SCHEMA_VERSION,
                "to_schema": VERIFICATION_SCHEMA_VERSION,
                "classification": "verification_requires_signed_attestation",
            }
        )
        return ledger

    def _migrate_v3(self, data: dict[str, Any]) -> dict[str, Any]:
        """Declare the quarantined artifact boundary without granting authority."""
        migrated_at = _isoformat(self._clock())
        ledger = copy.deepcopy(data)
        for proposal in ledger["proposals"]:
            proposal.setdefault("events", []).append(
                {
                    "type": "sandbox_schema_migrated",
                    "at": migrated_at,
                    "from_schema": VERIFICATION_SCHEMA_VERSION,
                    "to_schema": SANDBOX_SCHEMA_VERSION,
                    "authority_granted": False,
                }
            )
        ledger["schema_version"] = SANDBOX_SCHEMA_VERSION
        ledger["sandbox_contract"] = sandbox_contract()
        ledger["migrations"].append(
            {
                "type": "schema_migration",
                "at": migrated_at,
                "from_schema": VERIFICATION_SCHEMA_VERSION,
                "to_schema": SANDBOX_SCHEMA_VERSION,
                "classification": "quarantined_patch_static_evaluation_only",
            }
        )
        return ledger

    def _migrate_v4(self, data: dict[str, Any]) -> dict[str, Any]:
        """Add signed isolated execution without adding apply authority."""
        migrated_at = _isoformat(self._clock())
        ledger = copy.deepcopy(data)
        for proposal in ledger["proposals"]:
            proposal.setdefault("events", []).append(
                {
                    "type": "execution_schema_migrated",
                    "at": migrated_at,
                    "from_schema": SANDBOX_SCHEMA_VERSION,
                    "to_schema": EXECUTION_SCHEMA_VERSION,
                    "authority_granted": False,
                }
            )
        ledger["schema_version"] = EXECUTION_SCHEMA_VERSION
        ledger["execution_contract"] = execution_contract()
        ledger["migrations"].append(
            {
                "type": "schema_migration",
                "at": migrated_at,
                "from_schema": SANDBOX_SCHEMA_VERSION,
                "to_schema": EXECUTION_SCHEMA_VERSION,
                "classification": "externally_approved_isolated_execution_only",
            }
        )
        return ledger

    def _migrate_v5(self, data: dict[str, Any]) -> dict[str, Any]:
        """Add reviewed dedicated-ref application without live activation."""
        migrated_at = _isoformat(self._clock())
        ledger = copy.deepcopy(data)
        for proposal in ledger["proposals"]:
            proposal.setdefault("events", []).append(
                {
                    "type": "application_schema_migrated",
                    "at": migrated_at,
                    "from_schema": EXECUTION_SCHEMA_VERSION,
                    "to_schema": APPLICATION_SCHEMA_VERSION,
                    "authority_granted": False,
                }
            )
        ledger["schema_version"] = APPLICATION_SCHEMA_VERSION
        ledger["application_contract"] = application_contract()
        ledger["migrations"].append(
            {
                "type": "schema_migration",
                "at": migrated_at,
                "from_schema": EXECUTION_SCHEMA_VERSION,
                "to_schema": APPLICATION_SCHEMA_VERSION,
                "classification": "reviewed_dedicated_branch_application_only",
            }
        )
        return ledger

    def _migrate_v6(self, data: dict[str, Any]) -> dict[str, Any]:
        """Add signed transient canary evaluation without release authority."""
        migrated_at = _isoformat(self._clock())
        ledger = copy.deepcopy(data)
        for proposal in ledger["proposals"]:
            proposal.setdefault("events", []).append(
                {
                    "type": "canary_schema_migrated",
                    "at": migrated_at,
                    "from_schema": APPLICATION_SCHEMA_VERSION,
                    "to_schema": SCHEMA_VERSION,
                    "authority_granted": False,
                }
            )
        ledger["schema_version"] = SCHEMA_VERSION
        ledger["canary_contract"] = canary_contract()
        ledger["migrations"].append(
            {
                "type": "schema_migration",
                "at": migrated_at,
                "from_schema": APPLICATION_SCHEMA_VERSION,
                "to_schema": SCHEMA_VERSION,
                "classification": "signed_transient_canary_with_mandatory_restore",
            }
        )
        return ledger

    @staticmethod
    def _validate_claim(claim: Any, *, label: str) -> None:
        if (
            not isinstance(claim, dict)
            or claim.get("verified") is not False
            or claim.get("authority_granted") is not False
            or not isinstance(claim.get("field"), str)
            or "value" not in claim
        ):
            raise SelfIterationError(
                f"self-iteration ledger {label} is not a valid unverified claim"
            )

    @staticmethod
    def _validate_provenance(provenance: Any, *, label: str) -> None:
        trust = provenance.get("trust") if isinstance(provenance, dict) else None
        authentication = (
            provenance.get("authentication") if isinstance(provenance, dict) else None
        )
        actor = provenance.get("actor") if isinstance(provenance, dict) else None
        integrity = (
            provenance.get("integrity") if isinstance(provenance, dict) else None
        )
        authenticated_context = bool(
            isinstance(authentication, dict)
            and authentication.get("verified") is True
            and isinstance(actor, dict)
            and actor.get("verified") is True
            and isinstance(actor.get("id"), str)
            and actor.get("id", "").strip()
        )
        if (
            not isinstance(provenance, dict)
            or provenance.get("schema") != PROVENANCE_SCHEMA
            or not isinstance(provenance.get("recorded_by"), str)
            or not isinstance(authentication, dict)
            or not isinstance(trust, dict)
            or trust.get("actor_authenticated") is not authenticated_context
            or trust.get("claims_verified") is not False
            or trust.get("evidence_verified") is not False
            or trust.get("weighting_eligible") is not False
            or trust.get("authority_eligible") is not False
            or not isinstance(integrity, dict)
            or integrity.get("tamper_evident") is not False
            or integrity.get("cryptographically_signed") is not False
        ):
            raise SelfIterationError(
                f"self-iteration ledger {label} provenance violates the zero-trust contract"
            )
        if authenticated_context:
            try:
                authenticated_identity(provenance)
            except VerificationError as exc:
                raise SelfIterationError(
                    f"self-iteration ledger {label} authenticated identity is malformed"
                ) from exc

    @staticmethod
    def _validate_trust_policy(policy: Any, *, label: str) -> None:
        weight = policy.get("effective_weight") if isinstance(policy, dict) else None
        if (
            not isinstance(policy, dict)
            or isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or weight != 0.0
            or policy.get("priority_eligible") is not False
            or policy.get("automation_eligible") is not False
            or policy.get("authority_eligible") is not False
        ):
            raise SelfIterationError(
                f"self-iteration ledger {label} trust policy violates the zero-weight contract"
            )

    def _validate_v2(self, data: dict[str, Any]) -> None:
        if data.get("provenance_contract") != _provenance_contract():
            raise SelfIterationError(
                "self-iteration ledger provenance contract is malformed"
            )
        if not isinstance(data.get("migrations"), list):
            raise SelfIterationError("self-iteration ledger migrations are malformed")

        for proposal in data["proposals"]:
            if not isinstance(proposal, dict):
                raise SelfIterationError(
                    "self-iteration ledger proposals are malformed"
                )
            if "source" in proposal:
                raise SelfIterationError(
                    "self-iteration ledger contains an authoritative-looking source field"
                )
            self._validate_claim(proposal.get("source_claim"), label="proposal source")
            self._validate_provenance(proposal.get("provenance"), label="proposal")
            self._validate_trust_policy(proposal.get("trust_policy"), label="proposal")
            events = proposal.get("events")
            if not isinstance(events, list):
                raise SelfIterationError("self-iteration proposal events are malformed")
            for event in events:
                if not isinstance(event, dict):
                    raise SelfIterationError(
                        "self-iteration proposal events are malformed"
                    )
                if event.get("type") != "outcome_recorded":
                    continue
                if "measurement_source" in event:
                    raise SelfIterationError(
                        "self-iteration outcome contains an authoritative-looking measurement field"
                    )
                self._validate_claim(
                    event.get("measurement_source_claim"),
                    label="outcome measurement source",
                )
                self._validate_provenance(event.get("provenance"), label="outcome")
                self._validate_trust_policy(event.get("trust_policy"), label="outcome")

    def _validate_v3(self, data: dict[str, Any]) -> None:
        self._validate_v2(data)
        if data.get("verification_contract") != verification_contract():
            raise SelfIterationError(
                "self-iteration ledger verification contract is malformed"
            )
        proposal_ids: set[str] = set()
        for proposal in data["proposals"]:
            if not set(proposal).issubset(_V3_PROPOSAL_FIELDS):
                raise SelfIterationError(
                    "self-iteration proposal contains unsupported unbound fields"
                )
            proposal_id = proposal.get("id")
            if (
                not isinstance(proposal_id, str)
                or not proposal_id
                or proposal_id in proposal_ids
            ):
                raise SelfIterationError(
                    "self-iteration proposal identifiers are malformed or duplicated"
                )
            proposal_ids.add(proposal_id)
            if proposal.get("status") not in _PROPOSAL_STATUSES:
                raise SelfIterationError("self-iteration proposal status is malformed")
            expected_digest = proposal_content_sha256(proposal)
            if proposal.get("content_sha256") != expected_digest:
                raise SelfIterationError(
                    "self-iteration proposal content digest is malformed"
                )
            expected_identity = self._identity_from_provenance(
                proposal.get("provenance"),
                label="self-iteration proposal",
                required=False,
            )
            if proposal.get("proposer_identity") != expected_identity:
                raise SelfIterationError(
                    "self-iteration proposal identity binding is malformed"
                )
            for event in proposal["events"]:
                if event.get("type") not in {
                    "verification_challenge_issued",
                    "verification_attested",
                }:
                    continue
                attestation = event.get("attestation")
                if (
                    not isinstance(attestation, dict)
                    or attestation.get("schema") != ATTESTATION_SCHEMA
                ):
                    raise SelfIterationError(
                        "self-iteration verification event is malformed"
                    )
                self._validate_provenance(
                    event.get("provenance"), label="verification event"
                )
                if event.get("authority_granted") is not False:
                    raise SelfIterationError(
                        "self-iteration verification event grants forbidden authority"
                    )
                if event.get("type") == "verification_challenge_issued":
                    if set(event) != {
                        "type",
                        "at",
                        "challenge_id",
                        "attestation",
                        "signing_sha256",
                        "provenance",
                        "authority_granted",
                    }:
                        raise SelfIterationError(
                            "self-iteration verification challenge fields are malformed"
                        )
                    signing_digest = event.get("signing_sha256")
                    if not isinstance(signing_digest, str) or not re.fullmatch(
                        r"[0-9a-f]{64}", signing_digest
                    ):
                        raise SelfIterationError(
                            "self-iteration verification challenge digest is malformed"
                        )
                if event.get("type") == "verification_attested":
                    if set(event) != {
                        "type",
                        "at",
                        "challenge_id",
                        "attestation",
                        "signature",
                        "provenance",
                        "authority_granted",
                    }:
                        raise SelfIterationError(
                            "self-iteration attestation event fields are malformed"
                        )
                    signature = event.get("signature")
                    if (
                        not isinstance(signature, dict)
                        or set(signature)
                        != {"algorithm", "key_id", "value", "assurance"}
                        or signature.get("algorithm") != SIGNATURE_ALGORITHM
                        or signature.get("assurance")
                        != "symmetric_mac_server_verifiable"
                        or not isinstance(signature.get("value"), str)
                    ):
                        raise SelfIterationError(
                            "self-iteration attestation signature is malformed"
                        )

    @staticmethod
    def _validate_hex_digest(value: Any, *, label: str) -> None:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise SelfIterationError(f"self-iteration {label} digest is malformed")

    def _validate_v4(self, data: dict[str, Any]) -> None:
        self._validate_v3(data)
        if data.get("sandbox_contract") != sandbox_contract():
            raise SelfIterationError(
                "self-iteration ledger sandbox contract is malformed"
            )
        for proposal in data["proposals"]:
            constructed: dict[str, dict[str, Any]] = {}
            evaluation_ids: set[str] = set()
            for event in proposal["events"]:
                event_type = event.get("type")
                if event_type == "sandbox_schema_migrated":
                    if (
                        set(event)
                        != {
                            "type",
                            "at",
                            "from_schema",
                            "to_schema",
                            "authority_granted",
                        }
                        or event
                        != {
                            "type": "sandbox_schema_migrated",
                            "at": event.get("at"),
                            "from_schema": VERIFICATION_SCHEMA_VERSION,
                            "to_schema": SANDBOX_SCHEMA_VERSION,
                            "authority_granted": False,
                        }
                        or not isinstance(event.get("at"), str)
                    ):
                        raise SelfIterationError(
                            "self-iteration sandbox migration event is malformed"
                        )
                    continue
                if event_type == "patch_candidate_constructed":
                    if set(event) != {
                        "type",
                        "at",
                        "candidate_id",
                        "candidate_sha256",
                        "proposal_content_sha256",
                        "source_fingerprint",
                        "author_identity",
                        "active_attestation_ids",
                        "paths",
                        "patch_sha256",
                        "provenance",
                        "execution_performed",
                        "tests_executed",
                        "live_source_writes",
                        "authority_granted",
                    }:
                        raise SelfIterationError(
                            "self-iteration patch construction event fields are malformed"
                        )
                    candidate_id = event.get("candidate_id")
                    if (
                        not isinstance(candidate_id, str)
                        or not re.fullmatch(r"sip-[0-9a-f]{32}", candidate_id)
                        or candidate_id in constructed
                    ):
                        raise SelfIterationError(
                            "self-iteration patch candidate identifier is malformed or duplicated"
                        )
                    self._validate_hex_digest(
                        event.get("candidate_sha256"), label="patch candidate"
                    )
                    self._validate_hex_digest(
                        event.get("patch_sha256"), label="patch artifact"
                    )
                    try:
                        subject_fingerprint = proposal_subject_fingerprint(proposal)
                    except VerificationError as exc:
                        raise SelfIterationError(
                            "self-iteration proposal source fingerprint is malformed"
                        ) from exc
                    attestation_ids = event.get("active_attestation_ids")
                    paths = event.get("paths")
                    if (
                        not isinstance(event.get("at"), str)
                        or event.get("proposal_content_sha256")
                        != proposal.get("content_sha256")
                        or event.get("source_fingerprint") != subject_fingerprint
                        or event.get("author_identity")
                        != proposal.get("proposer_identity")
                        or not isinstance(attestation_ids, list)
                        or not attestation_ids
                        or attestation_ids != sorted(attestation_ids)
                        or len(set(attestation_ids)) != len(attestation_ids)
                        or any(
                            not isinstance(item, str)
                            or not re.fullmatch(r"sia-[0-9a-f]{32}", item)
                            for item in attestation_ids
                        )
                        or not isinstance(paths, list)
                        or not paths
                        or paths != sorted(paths)
                        or len(set(paths)) != len(paths)
                        or not set(paths).issubset(
                            set(proposal.get("target_paths", []))
                        )
                        or event.get("execution_performed") is not False
                        or event.get("tests_executed") is not False
                        or event.get("live_source_writes") is not False
                        or event.get("authority_granted") is not False
                    ):
                        raise SelfIterationError(
                            "self-iteration patch construction event violates its boundary"
                        )
                    self._validate_provenance(
                        event.get("provenance"), label="patch construction event"
                    )
                    construction_actor = self._identity_from_provenance(
                        event.get("provenance"),
                        label="patch construction event",
                        required=True,
                    )
                    if construction_actor != event.get("author_identity"):
                        raise SelfIterationError(
                            "self-iteration patch author is not bound to request provenance"
                        )
                    constructed[candidate_id] = event
                    continue
                if event_type == "patch_candidate_evaluated":
                    if set(event) != {
                        "type",
                        "at",
                        "candidate_id",
                        "candidate_sha256",
                        "proposal_content_sha256",
                        "evaluation_id",
                        "evaluation_sha256",
                        "evaluator_id",
                        "evaluator_contract_sha256",
                        "requester_identity",
                        "status",
                        "eligible_for_external_review",
                        "eligible_for_execution",
                        "execution_performed",
                        "tests_executed",
                        "live_source_writes",
                        "authority_granted",
                        "provenance",
                    }:
                        raise SelfIterationError(
                            "self-iteration patch evaluation event fields are malformed"
                        )
                    candidate_id = event.get("candidate_id")
                    construction = constructed.get(candidate_id)
                    status = event.get("status")
                    evaluation_id = event.get("evaluation_id")
                    if (
                        construction is None
                        or not isinstance(event.get("at"), str)
                        or event.get("candidate_sha256")
                        != construction.get("candidate_sha256")
                        or event.get("proposal_content_sha256")
                        != proposal.get("content_sha256")
                        or not isinstance(evaluation_id, str)
                        or not re.fullmatch(r"sie-[0-9a-f]{32}", evaluation_id)
                        or evaluation_id in evaluation_ids
                        or event.get("evaluator_id") != STATIC_EVALUATOR_ID
                        or status not in {"static_checks_passed", "rejected"}
                        or event.get("eligible_for_external_review")
                        is not (status == "static_checks_passed")
                        or event.get("eligible_for_execution") is not False
                        or event.get("execution_performed") is not False
                        or event.get("tests_executed") is not False
                        or event.get("live_source_writes") is not False
                        or event.get("authority_granted") is not False
                    ):
                        raise SelfIterationError(
                            "self-iteration patch evaluation event violates its boundary"
                        )
                    self._validate_hex_digest(
                        event.get("evaluation_sha256"), label="patch evaluation"
                    )
                    self._validate_hex_digest(
                        event.get("evaluator_contract_sha256"),
                        label="patch evaluator contract",
                    )
                    self._validate_provenance(
                        event.get("provenance"), label="patch evaluation event"
                    )
                    requester_identity = self._identity_from_provenance(
                        event.get("provenance"),
                        label="patch evaluation event",
                        required=True,
                    )
                    if requester_identity != event.get("requester_identity"):
                        raise SelfIterationError(
                            "self-iteration patch evaluation requester is not bound to provenance"
                        )
                    evaluation_ids.add(evaluation_id)

    def _validate_v5(self, data: dict[str, Any]) -> None:
        self._validate_v4(data)
        if data.get("execution_contract") != execution_contract():
            raise SelfIterationError(
                "self-iteration ledger execution contract is malformed"
            )
        for proposal in data["proposals"]:
            challenges: dict[str, dict[str, Any]] = {}
            approval_ids: set[str] = set()
            executions: set[str] = set()
            executed_challenges: set[str] = set()
            for event in proposal["events"]:
                event_type = event.get("type")
                if event_type == "execution_schema_migrated":
                    if event != {
                        "type": "execution_schema_migrated",
                        "at": event.get("at"),
                        "from_schema": SANDBOX_SCHEMA_VERSION,
                        "to_schema": EXECUTION_SCHEMA_VERSION,
                        "authority_granted": False,
                    } or not isinstance(event.get("at"), str):
                        raise SelfIterationError(
                            "self-iteration execution migration event is malformed"
                        )
                    continue
                if event_type == "execution_approval_challenge_issued":
                    if set(event) != {
                        "type",
                        "at",
                        "approval",
                        "approval_sha256",
                        "requester_identity",
                        "provenance",
                        "execution_performed",
                        "tests_executed",
                        "live_source_writes",
                        "authority_granted",
                    }:
                        raise SelfIterationError(
                            "self-iteration execution challenge fields are malformed"
                        )
                    try:
                        approval = validate_execution_approval(event.get("approval"))
                        approval_digest = execution_approval_sha256(approval)
                    except ExecutionError as exc:
                        raise SelfIterationError(
                            "self-iteration execution approval is malformed"
                        ) from exc
                    challenge_id = approval["challenge_id"]
                    active_verifiers = [
                        attestation.get("verifier_identity")
                        for recorded in proposal["events"]
                        if recorded.get("type") == "verification_attested"
                        and isinstance(recorded.get("attestation"), dict)
                        and (attestation := recorded["attestation"]).get(
                            "attestation_id"
                        )
                        in approval["active_attestation_ids"]
                        and attestation.get("decision") == "verified"
                    ]
                    construction_matches = [
                        recorded
                        for recorded in proposal["events"]
                        if recorded.get("type") == "patch_candidate_constructed"
                        and recorded.get("candidate_id") == approval["candidate_id"]
                    ]
                    evaluation_matches = [
                        recorded
                        for recorded in proposal["events"]
                        if recorded.get("type") == "patch_candidate_evaluated"
                        and recorded.get("candidate_id") == approval["candidate_id"]
                        and recorded.get("evaluation_id") == approval["evaluation_id"]
                    ]
                    if (
                        challenge_id in challenges
                        or approval["approval_id"] in approval_ids
                        or approval["proposal_id"] != proposal.get("id")
                        or approval["proposal_content_sha256"]
                        != proposal.get("content_sha256")
                        or approval["source_fingerprint"]
                        != proposal_subject_fingerprint(proposal)
                        or len(active_verifiers)
                        != len(approval["active_attestation_ids"])
                        or approval["approver_identity"]
                        in [proposal.get("proposer_identity"), *active_verifiers]
                        or approval["result_signer"]["id"]
                        in {
                            identity.get("id")
                            for identity in [
                                proposal.get("proposer_identity"),
                                approval["approver_identity"],
                                *active_verifiers,
                            ]
                            if isinstance(identity, dict)
                        }
                        or len(construction_matches) != 1
                        or construction_matches[0].get("candidate_sha256")
                        != approval["candidate_sha256"]
                        or construction_matches[0].get("active_attestation_ids")
                        != approval["active_attestation_ids"]
                        or len(evaluation_matches) != 1
                        or evaluation_matches[0].get("evaluation_sha256")
                        != approval["evaluation_sha256"]
                        or evaluation_matches[0].get("status") != "static_checks_passed"
                        or event.get("at") != approval["issued_at"]
                        or event.get("approval_sha256") != approval_digest
                        or event.get("execution_performed") is not False
                        or event.get("tests_executed") is not False
                        or event.get("live_source_writes") is not False
                        or event.get("authority_granted") is not False
                    ):
                        raise SelfIterationError(
                            "self-iteration execution challenge violates its boundary"
                        )
                    self._validate_provenance(
                        event.get("provenance"), label="execution challenge event"
                    )
                    requester = self._identity_from_provenance(
                        event.get("provenance"),
                        label="execution challenge event",
                        required=True,
                    )
                    if requester != event.get("requester_identity"):
                        raise SelfIterationError(
                            "execution challenge requester is not bound to provenance"
                        )
                    challenges[challenge_id] = event
                    approval_ids.add(approval["approval_id"])
                    continue
                if event_type == "isolated_execution_recorded":
                    if set(event) != {
                        "type",
                        "at",
                        "challenge_id",
                        "approval_id",
                        "approval_sha256",
                        "approval_signature_sha256",
                        "execution_id",
                        "result_sha256",
                        "candidate_id",
                        "candidate_sha256",
                        "evaluation_id",
                        "evaluation_sha256",
                        "approver_identity",
                        "result_signer_id",
                        "outcome",
                        "execution_performed",
                        "tests_executed",
                        "cleanup_confirmed",
                        "eligible_for_external_review",
                        "eligible_for_apply",
                        "live_source_writes",
                        "authority_granted",
                    }:
                        raise SelfIterationError(
                            "self-iteration execution result fields are malformed"
                        )
                    challenge = challenges.get(event.get("challenge_id"))
                    approval = challenge.get("approval") if challenge else None
                    challenge_approval_digest = (
                        challenge.get("approval_sha256") if challenge else None
                    )
                    execution_id = event.get("execution_id")
                    outcome = event.get("outcome")
                    if (
                        not isinstance(approval, dict)
                        or not isinstance(execution_id, str)
                        or not re.fullmatch(r"six-[0-9a-f]{32}", execution_id)
                        or execution_id in executions
                        or event.get("challenge_id") in executed_challenges
                        or event.get("approval_id") != approval.get("approval_id")
                        or event.get("approval_sha256") != challenge_approval_digest
                        or not isinstance(event.get("approval_signature_sha256"), str)
                        or event.get("candidate_id") != approval.get("candidate_id")
                        or event.get("candidate_sha256")
                        != approval.get("candidate_sha256")
                        or event.get("evaluation_id") != approval.get("evaluation_id")
                        or event.get("evaluation_sha256")
                        != approval.get("evaluation_sha256")
                        or event.get("approver_identity")
                        != approval.get("approver_identity")
                        or event.get("result_signer_id")
                        != approval.get("result_signer", {}).get("id")
                        or outcome
                        not in {
                            "passed",
                            "failed",
                            "timed_out",
                            "output_limit_exceeded",
                            "runner_error",
                        }
                        or not isinstance(event.get("execution_performed"), bool)
                        or event.get("tests_executed")
                        is not event.get("execution_performed")
                        or not isinstance(event.get("cleanup_confirmed"), bool)
                        or event.get("eligible_for_external_review")
                        is not (outcome == "passed")
                        or (
                            outcome == "passed"
                            and (
                                event.get("execution_performed") is not True
                                or event.get("cleanup_confirmed") is not True
                            )
                        )
                        or (
                            outcome
                            in {
                                "failed",
                                "timed_out",
                                "output_limit_exceeded",
                            }
                            and event.get("execution_performed") is not True
                        )
                        or event.get("eligible_for_apply") is not False
                        or event.get("live_source_writes") is not False
                        or event.get("authority_granted") is not False
                    ):
                        raise SelfIterationError(
                            "self-iteration execution result violates its boundary"
                        )
                    self._validate_hex_digest(
                        event.get("result_sha256"), label="execution result"
                    )
                    self._validate_hex_digest(
                        event.get("approval_signature_sha256"),
                        label="execution approval signature",
                    )
                    executions.add(execution_id)
                    executed_challenges.add(event["challenge_id"])

    def _validate_v6(self, data: dict[str, Any]) -> None:
        self._validate_v5(data)
        if data.get("application_contract") != application_contract():
            raise SelfIterationError(
                "self-iteration ledger application contract is malformed"
            )
        for proposal in data["proposals"]:
            challenges: dict[str, dict[str, Any]] = {}
            application_ids: set[str] = set()
            recorded_challenges: set[str] = set()
            result_ids: set[str] = set()
            for event in proposal["events"]:
                event_type = event.get("type")
                if event_type == "application_schema_migrated":
                    if event != {
                        "type": "application_schema_migrated",
                        "at": event.get("at"),
                        "from_schema": EXECUTION_SCHEMA_VERSION,
                        "to_schema": APPLICATION_SCHEMA_VERSION,
                        "authority_granted": False,
                    } or not isinstance(event.get("at"), str):
                        raise SelfIterationError(
                            "self-iteration application migration event is malformed"
                        )
                    continue
                if event_type == "application_review_challenge_issued":
                    if set(event) != {
                        "type",
                        "at",
                        "approval",
                        "approval_sha256",
                        "requester_identity",
                        "provenance",
                        "branch_created",
                        "live_source_writes",
                        "pushed",
                        "merged",
                        "deployed",
                        "authority_granted",
                    }:
                        raise SelfIterationError(
                            "self-iteration application challenge fields are malformed"
                        )
                    try:
                        approval = validate_application_approval(event.get("approval"))
                        approval_digest = application_approval_sha256(approval)
                    except ApplicationError as exc:
                        raise SelfIterationError(
                            "self-iteration application approval is malformed"
                        ) from exc
                    challenge_id = approval["challenge_id"]
                    active_verifiers = [
                        attestation.get("verifier_identity")
                        for recorded in proposal["events"]
                        if recorded.get("type") == "verification_attested"
                        and isinstance(recorded.get("attestation"), dict)
                        and (attestation := recorded["attestation"]).get(
                            "attestation_id"
                        )
                        in approval["active_attestation_ids"]
                        and attestation.get("decision") == "verified"
                    ]
                    execution_events = [
                        recorded
                        for recorded in proposal["events"]
                        if recorded.get("type") == "isolated_execution_recorded"
                        and recorded.get("execution_id") == approval["execution_id"]
                    ]
                    execution_challenges = [
                        recorded
                        for recorded in proposal["events"]
                        if recorded.get("type") == "execution_approval_challenge_issued"
                        and recorded.get("approval_sha256")
                        == approval["execution_approval_sha256"]
                    ]
                    prior_participant_ids = {
                        identity.get("id")
                        for identity in [
                            proposal.get("proposer_identity"),
                            *active_verifiers,
                            (
                                execution_challenges[0]["approval"].get(
                                    "approver_identity"
                                )
                                if len(execution_challenges) == 1
                                else None
                            ),
                        ]
                        if isinstance(identity, dict)
                    }
                    if len(execution_events) == 1:
                        prior_participant_ids.add(
                            execution_events[0].get("result_signer_id")
                        )
                    reviewer_id = approval["reviewer_identity"]["id"]
                    result_signer_id = approval["result_signer"]["id"]
                    if (
                        challenge_id in challenges
                        or approval["application_id"] in application_ids
                        or approval["proposal_id"] != proposal.get("id")
                        or approval["proposal_content_sha256"]
                        != proposal.get("content_sha256")
                        or approval["source_fingerprint"]
                        != proposal_subject_fingerprint(proposal)
                        or len(active_verifiers)
                        != len(approval["active_attestation_ids"])
                        or len(execution_events) != 1
                        or execution_events[0].get("candidate_id")
                        != approval["candidate_id"]
                        or execution_events[0].get("candidate_sha256")
                        != approval["candidate_sha256"]
                        or execution_events[0].get("result_sha256")
                        != approval["execution_result_sha256"]
                        or execution_events[0].get("approval_sha256")
                        != approval["execution_approval_sha256"]
                        or execution_events[0].get("at")
                        != approval["execution_finished_at"]
                        or execution_events[0].get("outcome") != "passed"
                        or execution_events[0].get("execution_performed") is not True
                        or execution_events[0].get("cleanup_confirmed") is not True
                        or execution_events[0].get("eligible_for_external_review")
                        is not True
                        or len(execution_challenges) != 1
                        or reviewer_id in prior_participant_ids
                        or result_signer_id in {reviewer_id, *prior_participant_ids}
                        or event.get("at") != approval["issued_at"]
                        or event.get("approval_sha256") != approval_digest
                        or event.get("branch_created") is not False
                        or event.get("live_source_writes") is not False
                        or event.get("pushed") is not False
                        or event.get("merged") is not False
                        or event.get("deployed") is not False
                        or event.get("authority_granted") is not False
                    ):
                        raise SelfIterationError(
                            "self-iteration application challenge violates its boundary"
                        )
                    self._validate_provenance(
                        event.get("provenance"), label="application challenge event"
                    )
                    requester = self._identity_from_provenance(
                        event.get("provenance"),
                        label="application challenge event",
                        required=True,
                    )
                    if (
                        requester != event.get("requester_identity")
                        or requester != approval["reviewer_identity"]
                    ):
                        raise SelfIterationError(
                            "application reviewer is not bound to request provenance"
                        )
                    challenges[challenge_id] = event
                    application_ids.add(approval["application_id"])
                    continue
                if event_type == "reviewed_application_recorded":
                    if set(event) != {
                        "type",
                        "at",
                        "challenge_id",
                        "application_id",
                        "approval_sha256",
                        "approval_signature_sha256",
                        "application_result_id",
                        "result_sha256",
                        "candidate_id",
                        "candidate_sha256",
                        "execution_id",
                        "execution_result_sha256",
                        "reviewer_identity",
                        "result_signer_id",
                        "target_ref",
                        "commit_oid",
                        "tree_oid",
                        "branch_created",
                        "live_source_writes",
                        "pushed",
                        "merged",
                        "deployed",
                        "eligible_for_canary_review",
                        "eligible_for_live_activation",
                        "authority_granted",
                    }:
                        raise SelfIterationError(
                            "self-iteration application result fields are malformed"
                        )
                    result_challenge = challenges.get(event.get("challenge_id"))
                    recorded_approval = (
                        result_challenge.get("approval") if result_challenge else None
                    )
                    result_approval_digest = (
                        result_challenge.get("approval_sha256")
                        if result_challenge
                        else None
                    )
                    result_id = event.get("application_result_id")
                    commit_oid = event.get("commit_oid")
                    tree_oid = event.get("tree_oid")
                    if (
                        not isinstance(recorded_approval, dict)
                        or event.get("challenge_id") in recorded_challenges
                        or not isinstance(result_id, str)
                        or not re.fullmatch(r"siar-[0-9a-f]{32}", result_id)
                        or result_id in result_ids
                        or event.get("application_id")
                        != recorded_approval.get("application_id")
                        or event.get("approval_sha256") != result_approval_digest
                        or event.get("candidate_id")
                        != recorded_approval.get("candidate_id")
                        or event.get("candidate_sha256")
                        != recorded_approval.get("candidate_sha256")
                        or event.get("execution_id")
                        != recorded_approval.get("execution_id")
                        or event.get("execution_result_sha256")
                        != recorded_approval.get("execution_result_sha256")
                        or event.get("reviewer_identity")
                        != recorded_approval.get("reviewer_identity")
                        or event.get("result_signer_id")
                        != recorded_approval.get("result_signer", {}).get("id")
                        or event.get("target_ref")
                        != recorded_approval.get("target_ref")
                        or not isinstance(commit_oid, str)
                        or not re.fullmatch(
                            r"[0-9a-f]{40}(?:[0-9a-f]{24})?", commit_oid
                        )
                        or not isinstance(tree_oid, str)
                        or not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", tree_oid)
                        or len(commit_oid)
                        != len(recorded_approval["expected_parent_revision"])
                        or len(tree_oid) != len(commit_oid)
                        or event.get("branch_created") is not True
                        or event.get("live_source_writes") is not False
                        or event.get("pushed") is not False
                        or event.get("merged") is not False
                        or event.get("deployed") is not False
                        or event.get("eligible_for_canary_review") is not True
                        or event.get("eligible_for_live_activation") is not False
                        or event.get("authority_granted") is not False
                    ):
                        raise SelfIterationError(
                            "self-iteration application result violates its boundary"
                        )
                    self._validate_hex_digest(
                        event.get("approval_signature_sha256"),
                        label="application approval signature",
                    )
                    self._validate_hex_digest(
                        event.get("result_sha256"), label="application result"
                    )
                    recorded_challenges.add(event["challenge_id"])
                    result_ids.add(result_id)

    def _validate_v7(self, data: dict[str, Any]) -> None:
        self._validate_v6(data)
        if data.get("canary_contract") != canary_contract():
            raise SelfIterationError(
                "self-iteration ledger canary contract is malformed"
            )
        for proposal in data["proposals"]:
            challenges: dict[str, dict[str, Any]] = {}
            canary_ids: set[str] = set()
            recorded_challenges: set[str] = set()
            result_ids: set[str] = set()
            for event in proposal["events"]:
                event_type = event.get("type")
                if event_type == "canary_schema_migrated":
                    if event != {
                        "type": "canary_schema_migrated",
                        "at": event.get("at"),
                        "from_schema": APPLICATION_SCHEMA_VERSION,
                        "to_schema": SCHEMA_VERSION,
                        "authority_granted": False,
                    } or not isinstance(event.get("at"), str):
                        raise SelfIterationError(
                            "self-iteration canary migration event is malformed"
                        )
                    continue
                if event_type == "canary_review_challenge_issued":
                    if set(event) != {
                        "type",
                        "at",
                        "approval",
                        "approval_sha256",
                        "requester_identity",
                        "provenance",
                        "activation_performed",
                        "baseline_restore_attempted",
                        "persistent_activation_retained",
                        "authority_granted",
                    }:
                        raise SelfIterationError(
                            "self-iteration canary challenge fields are malformed"
                        )
                    try:
                        approval = validate_canary_approval(event.get("approval"))
                        approval_digest = canary_approval_sha256(approval)
                    except CanaryError as exc:
                        raise SelfIterationError(
                            "self-iteration canary approval is malformed"
                        ) from exc
                    challenge_id = approval["challenge_id"]
                    application_results = [
                        recorded
                        for recorded in proposal["events"]
                        if recorded.get("type") == "reviewed_application_recorded"
                        and recorded.get("application_result_id")
                        == approval["application_result_id"]
                    ]
                    application_challenges = [
                        recorded
                        for recorded in proposal["events"]
                        if recorded.get("type") == "application_review_challenge_issued"
                        and recorded.get("approval", {}).get("application_id")
                        == approval["application_id"]
                    ]
                    app_approval = (
                        application_challenges[0].get("approval")
                        if len(application_challenges) == 1
                        else None
                    )
                    execution_challenges = [
                        recorded
                        for recorded in proposal["events"]
                        if isinstance(app_approval, dict)
                        and recorded.get("type")
                        == "execution_approval_challenge_issued"
                        and recorded.get("approval_sha256")
                        == app_approval.get("execution_approval_sha256")
                    ]
                    active_verifiers = [
                        attestation.get("verifier_identity")
                        for recorded in proposal["events"]
                        if isinstance(app_approval, dict)
                        and recorded.get("type") == "verification_attested"
                        and isinstance(recorded.get("attestation"), dict)
                        and (attestation := recorded["attestation"]).get(
                            "attestation_id"
                        )
                        in app_approval.get("active_attestation_ids", [])
                        and attestation.get("decision") == "verified"
                    ]
                    prior_ids = {
                        identity.get("id")
                        for identity in [
                            proposal.get("proposer_identity"),
                            *active_verifiers,
                            (
                                execution_challenges[0]["approval"].get(
                                    "approver_identity"
                                )
                                if len(execution_challenges) == 1
                                else None
                            ),
                            (
                                app_approval.get("reviewer_identity")
                                if isinstance(app_approval, dict)
                                else None
                            ),
                        ]
                        if isinstance(identity, dict)
                    }
                    if isinstance(app_approval, dict):
                        prior_ids.add(app_approval.get("result_signer", {}).get("id"))
                    execution_results = [
                        recorded
                        for recorded in proposal["events"]
                        if isinstance(app_approval, dict)
                        and recorded.get("type") == "isolated_execution_recorded"
                        and recorded.get("execution_id")
                        == app_approval.get("execution_id")
                    ]
                    if len(execution_results) == 1:
                        prior_ids.add(execution_results[0].get("result_signer_id"))
                    reviewer_id = approval["reviewer_identity"]["id"]
                    supervisor_id = approval["supervisor_identity"]["result_signer"][
                        "id"
                    ]
                    if (
                        challenge_id in challenges
                        or approval["canary_id"] in canary_ids
                        or approval["proposal_id"] != proposal.get("id")
                        or approval["proposal_content_sha256"]
                        != proposal.get("content_sha256")
                        or len(application_results) != 1
                        or application_results[0].get("candidate_id")
                        != approval["candidate_id"]
                        or application_results[0].get("application_id")
                        != approval["application_id"]
                        or application_results[0].get("result_sha256")
                        != approval["application_result_sha256"]
                        or application_results[0].get("approval_sha256")
                        != approval["application_approval_sha256"]
                        or application_results[0].get("target_ref")
                        != approval["target_ref"]
                        or application_results[0].get("commit_oid")
                        != approval["candidate_commit_oid"]
                        or len(application_challenges) != 1
                        or not isinstance(app_approval, dict)
                        or app_approval.get("expected_parent_revision")
                        != approval["baseline_revision"]
                        or approval["application_reviewer_identity"]
                        != app_approval.get("reviewer_identity")
                        or approval["application_result_signer_id"]
                        != app_approval.get("result_signer", {}).get("id")
                        or len(active_verifiers)
                        != len(app_approval.get("active_attestation_ids", []))
                        or len(execution_challenges) != 1
                        or len(execution_results) != 1
                        or reviewer_id in prior_ids
                        or supervisor_id in {reviewer_id, *prior_ids}
                        or event.get("at") != approval["issued_at"]
                        or event.get("approval_sha256") != approval_digest
                        or event.get("activation_performed") is not False
                        or event.get("baseline_restore_attempted") is not False
                        or event.get("persistent_activation_retained") is not False
                        or event.get("authority_granted") is not False
                    ):
                        raise SelfIterationError(
                            "self-iteration canary challenge violates its boundary"
                        )
                    self._validate_provenance(
                        event.get("provenance"), label="canary challenge event"
                    )
                    requester = self._identity_from_provenance(
                        event.get("provenance"),
                        label="canary challenge event",
                        required=True,
                    )
                    if (
                        requester != event.get("requester_identity")
                        or requester != approval["reviewer_identity"]
                    ):
                        raise SelfIterationError(
                            "canary reviewer is not bound to request provenance"
                        )
                    challenges[challenge_id] = event
                    canary_ids.add(approval["canary_id"])
                    continue
                if event_type == "transient_canary_recorded":
                    if set(event) != {
                        "type",
                        "at",
                        "challenge_id",
                        "canary_id",
                        "approval_sha256",
                        "approval_signature_sha256",
                        "canary_result_id",
                        "result_sha256",
                        "candidate_id",
                        "application_result_id",
                        "application_result_sha256",
                        "reviewer_identity",
                        "supervisor_signer_id",
                        "outcome",
                        "activation_performed",
                        "health_checks_sha256",
                        "baseline_restore_attempted",
                        "baseline_restored",
                        "persistent_activation_retained",
                        "recommended_decision",
                        "eligible_for_merge_review",
                        "eligible_for_live_activation",
                        "authority_granted",
                    }:
                        raise SelfIterationError(
                            "self-iteration canary result fields are malformed"
                        )
                    challenge = challenges.get(event.get("challenge_id"))
                    recorded_approval = challenge.get("approval") if challenge else None
                    result_id = event.get("canary_result_id")
                    outcome = event.get("outcome")
                    baseline_restored = event.get("baseline_restored")
                    expected_decision = (
                        "keep_candidate_for_merge_review"
                        if outcome == "passed" and baseline_restored is True
                        else (
                            "operator_recovery_required"
                            if outcome == "rollback_failed"
                            or baseline_restored is False
                            else "reject_candidate"
                        )
                    )
                    eligible = outcome == "passed" and baseline_restored is True
                    if (
                        not isinstance(recorded_approval, dict)
                        or event.get("challenge_id") in recorded_challenges
                        or not isinstance(result_id, str)
                        or not re.fullmatch(r"sicr-[0-9a-f]{32}", result_id)
                        or result_id in result_ids
                        or event.get("canary_id") != recorded_approval.get("canary_id")
                        or event.get("approval_sha256")
                        != canary_approval_sha256(recorded_approval)
                        or event.get("candidate_id")
                        != recorded_approval.get("candidate_id")
                        or event.get("application_result_id")
                        != recorded_approval.get("application_result_id")
                        or event.get("application_result_sha256")
                        != recorded_approval.get("application_result_sha256")
                        or event.get("reviewer_identity")
                        != recorded_approval.get("reviewer_identity")
                        or event.get("supervisor_signer_id")
                        != recorded_approval.get("supervisor_identity", {})
                        .get("result_signer", {})
                        .get("id")
                        or outcome
                        not in {
                            "passed",
                            "failed",
                            "activation_failed",
                            "timed_out",
                            "supervisor_error",
                            "rollback_failed",
                        }
                        or not isinstance(event.get("activation_performed"), bool)
                        or not isinstance(event.get("baseline_restore_attempted"), bool)
                        or not isinstance(baseline_restored, bool)
                        or event.get("persistent_activation_retained") is not False
                        or event.get("recommended_decision") != expected_decision
                        or event.get("eligible_for_merge_review") is not eligible
                        or event.get("eligible_for_live_activation") is not False
                        or event.get("authority_granted") is not False
                    ):
                        raise SelfIterationError(
                            "self-iteration canary result violates its boundary"
                        )
                    for field, label in (
                        ("approval_signature_sha256", "canary approval signature"),
                        ("health_checks_sha256", "canary health checks"),
                        ("result_sha256", "canary result"),
                    ):
                        self._validate_hex_digest(event.get(field), label=label)
                    recorded_challenges.add(event["challenge_id"])
                    result_ids.add(result_id)

    def _load_ledger(self) -> dict[str, Any]:
        if not self.ledger_path.exists():
            return self._empty_ledger()
        try:
            data = json.loads(self.ledger_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise SelfIterationError(
                "self-iteration ledger is unreadable; refusing to overwrite it"
            ) from exc
        if not isinstance(data, dict):
            raise SelfIterationError("self-iteration ledger has an unsupported schema")
        if not isinstance(data.get("proposals"), list):
            raise SelfIterationError("self-iteration ledger proposals are malformed")
        version = data.get("schema_version", 1)
        migrated = False
        if version == 1:
            data = self._migrate_v1(data)
            self._validate_v2(data)
            version = PROVENANCE_SCHEMA_VERSION
            migrated = True
        if version == PROVENANCE_SCHEMA_VERSION:
            self._validate_v2(data)
            data = self._migrate_v2(data)
            self._validate_v3(data)
            version = VERIFICATION_SCHEMA_VERSION
            migrated = True
        if version == VERIFICATION_SCHEMA_VERSION:
            self._validate_v3(data)
            data = self._migrate_v3(data)
            self._validate_v4(data)
            version = SANDBOX_SCHEMA_VERSION
            migrated = True
        if version == SANDBOX_SCHEMA_VERSION:
            self._validate_v4(data)
            data = self._migrate_v4(data)
            self._validate_v5(data)
            version = EXECUTION_SCHEMA_VERSION
            migrated = True
        if version == EXECUTION_SCHEMA_VERSION:
            self._validate_v5(data)
            data = self._migrate_v5(data)
            self._validate_v6(data)
            version = APPLICATION_SCHEMA_VERSION
            migrated = True
        if version == APPLICATION_SCHEMA_VERSION:
            self._validate_v6(data)
            data = self._migrate_v6(data)
            self._validate_v7(data)
            version = SCHEMA_VERSION
            migrated = True
        elif version == SCHEMA_VERSION:
            self._validate_v7(data)
        else:
            raise SelfIterationError("self-iteration ledger has an unsupported schema")
        if version != SCHEMA_VERSION:
            self._validate_v7(data)
            raise SelfIterationError("self-iteration ledger has an unsupported schema")
        if migrated:
            self._save_ledger(data)
        return data

    def _save_ledger(self, ledger: dict[str, Any]) -> None:
        atomic_json_write(self.ledger_path, ledger, indent=2)

    @staticmethod
    def _find_proposal(ledger: dict[str, Any], proposal_id: str) -> dict[str, Any]:
        proposal = next(
            (item for item in ledger["proposals"] if item.get("id") == proposal_id),
            None,
        )
        if proposal is None:
            raise SelfIterationError(f"proposal not found: {proposal_id}")
        return proposal

    def _verification_state(
        self, proposal: dict[str, Any], *, now: datetime | None = None
    ) -> dict[str, Any]:
        return evaluate_verification(
            proposal,
            key_provider=self._verifier_key_provider,
            now=now or self._now_utc(),
        )

    def _now_utc(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise SelfIterationError("self-iteration clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    def _public_proposal(
        self, proposal: dict[str, Any], *, now: datetime | None = None
    ) -> dict[str, Any]:
        result = copy.deepcopy(proposal)
        result["verification_state"] = self._verification_state(proposal, now=now)
        return result

    def _validated_attestation(
        self,
        proposal: dict[str, Any],
        attestation_id: str,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        matches = [
            (index, event)
            for index, event in enumerate(proposal["events"])
            if event.get("type") == "verification_attested"
            and isinstance(event.get("attestation"), dict)
            and event["attestation"].get("attestation_id") == attestation_id
        ]
        if len(matches) != 1:
            raise SelfIterationError(
                "target_attestation_id does not name one recorded attestation"
            )
        event_index, event = matches[0]
        try:
            return validate_recorded_attestation(
                proposal=proposal,
                event=event,
                event_index=event_index,
                key_provider=self._verifier_key_provider,
                now=now,
            )
        except VerificationError as exc:
            raise SelfIterationError(
                "target attestation is not currently valid"
            ) from exc

    def _code_fingerprint(self) -> dict[str, Any]:
        git = self._git_metadata()
        manifest = self._manifest(include_files=False, file_limit=1)
        return {
            "revision": git.get("revision"),
            "branch": git.get("branch"),
            "working_tree_changes_present": git.get("working_tree_changes_present"),
            "manifest_sha256": manifest["sha256"],
            "source_file_count": manifest["file_count"],
        }

    def _assert_current_proposal_source(
        self, proposal: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            expected = proposal_subject_fingerprint(proposal)
        except VerificationError as exc:
            raise SelfIterationError(
                "proposal source fingerprint is unavailable or malformed"
            ) from exc
        current = self._code_fingerprint()
        current_subject = {
            "revision": current.get("revision"),
            "manifest_sha256": current.get("manifest_sha256"),
        }
        if current_subject != expected:
            raise SelfIterationError(
                "live source no longer matches the verified proposal fingerprint"
            )
        return expected

    def _patch_eligible_state(
        self,
        proposal: dict[str, Any],
        *,
        expected_content_sha256: str,
        now: datetime,
    ) -> dict[str, Any]:
        if (
            proposal.get("content_sha256") != expected_content_sha256
            or proposal_content_sha256(proposal) != expected_content_sha256
        ):
            raise SelfIterationError(
                "proposal content digest changed; inspect the proposal again"
            )
        if (
            proposal.get("status") != "ready_for_isolated_implementation"
            or proposal.get("risk", {}).get("effective") != "low"
        ):
            raise SelfIterationError(
                "only low-risk proposals ready for isolated implementation may construct or evaluate patches"
            )
        target_paths = proposal.get("target_paths")
        if not isinstance(target_paths, list) or not target_paths:
            raise SelfIterationError("proposal target paths are malformed")
        current_boundaries = [self.classify_target(path) for path in target_paths]
        if any(
            boundary.get("boundary") != "bounded_candidate"
            or boundary.get("auto_implementation_eligible") is not True
            for boundary in current_boundaries
        ):
            raise SelfIterationError(
                "proposal targets are no longer within the bounded candidate allowlist"
            )
        state = self._verification_state(proposal, now=now)
        if (
            state.get("status") != "verified"
            or state.get("priority_eligible") is not True
        ):
            raise SelfIterationError(
                "a current independent verified attestation is required"
            )
        if (
            state.get("automation_eligible") is not False
            or state.get("authority_eligible") is not False
        ):
            raise SelfIterationError(
                "verification state violates the no-authority contract"
            )
        active_ids = state.get("active_attestation_ids")
        if not isinstance(active_ids, list) or not active_ids:
            raise SelfIterationError("active verification binding is unavailable")
        return state

    @staticmethod
    def _candidate_construction_event(
        proposal: dict[str, Any], candidate_id: str
    ) -> dict[str, Any]:
        matches = [
            event
            for event in proposal["events"]
            if event.get("type") == "patch_candidate_constructed"
            and event.get("candidate_id") == candidate_id
        ]
        if len(matches) != 1:
            raise SelfIterationError(
                "candidate is not bound to one recorded construction event"
            )
        return matches[0]

    def _assert_candidate_binding(
        self,
        *,
        proposal: dict[str, Any],
        candidate: dict[str, Any],
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str):
            raise SelfIterationError("candidate manifest identifier is malformed")
        construction = self._candidate_construction_event(proposal, candidate_id)
        binding = candidate.get("proposal_binding")
        files = candidate.get("files")
        if not isinstance(binding, dict) or not isinstance(files, list):
            raise SelfIterationError("candidate manifest binding is malformed")
        try:
            source_fingerprint = proposal_subject_fingerprint(proposal)
        except VerificationError as exc:
            raise SelfIterationError(
                "proposal source fingerprint is unavailable or malformed"
            ) from exc
        expected_binding = {
            "proposal_id": proposal.get("id"),
            "proposal_content_sha256": proposal.get("content_sha256"),
            "source_fingerprint": source_fingerprint,
            "proposer_identity": proposal.get("proposer_identity"),
            "active_attestation_ids": construction.get("active_attestation_ids"),
        }
        paths: list[str] = []
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise SelfIterationError("candidate manifest file paths are malformed")
            paths.append(item["path"])
        paths.sort()
        if (
            binding != expected_binding
            or candidate.get("candidate_sha256") != construction.get("candidate_sha256")
            or candidate.get("patch", {}).get("sha256")
            != construction.get("patch_sha256")
            or paths != construction.get("paths")
        ):
            raise SelfIterationError(
                "candidate artifact does not match its ledger construction event"
            )
        if state is not None and binding.get("active_attestation_ids") != state.get(
            "active_attestation_ids"
        ):
            raise SelfIterationError(
                "candidate verification binding is stale; construct a new candidate"
            )
        return construction

    @staticmethod
    def _active_verifier_identities(
        proposal: dict[str, Any], state: dict[str, Any]
    ) -> list[dict[str, str | None]]:
        active_ids = set(state.get("active_attestation_ids", []))
        identities: list[dict[str, str | None]] = []
        for event in proposal["events"]:
            attestation = event.get("attestation")
            if (
                event.get("type") != "verification_attested"
                or not isinstance(attestation, dict)
                or attestation.get("attestation_id") not in active_ids
                or attestation.get("decision") != "verified"
            ):
                continue
            identity = attestation.get("verifier_identity")
            if not isinstance(identity, dict):
                raise SelfIterationError("active verifier identity is malformed")
            identities.append(copy.deepcopy(identity))
        if len(identities) != len(active_ids):
            raise SelfIterationError("active verifier identity binding is incomplete")
        return identities

    def _passing_evaluation(
        self,
        *,
        proposal: dict[str, Any],
        candidate: dict[str, Any],
        evaluation_id: str,
        expected_evaluation_sha256: str,
    ) -> dict[str, Any]:
        matches = [
            event
            for event in proposal["events"]
            if event.get("type") == "patch_candidate_evaluated"
            and event.get("candidate_id") == candidate.get("candidate_id")
            and event.get("evaluation_id") == evaluation_id
        ]
        if len(matches) != 1:
            raise SelfIterationError(
                "execution requires one recorded static evaluation event"
            )
        event = matches[0]
        if (
            event.get("status") != "static_checks_passed"
            or event.get("eligible_for_external_review") is not True
            or event.get("eligible_for_execution") is not False
            or event.get("evaluation_sha256") != expected_evaluation_sha256
        ):
            raise SelfIterationError(
                "execution requires the exact passing static evaluation digest"
            )
        try:
            artifacts = self._patch_sandbox.load_evaluations(candidate["candidate_id"])
        except PatchSandboxError as exc:
            raise SelfIterationError(str(exc)) from exc
        artifact_matches = [
            item for item in artifacts if item.get("evaluation_id") == evaluation_id
        ]
        if len(artifact_matches) != 1:
            raise SelfIterationError(
                "recorded static evaluation artifact is unavailable"
            )
        evaluation = artifact_matches[0]
        if (
            evaluation.get("evaluation_sha256") != expected_evaluation_sha256
            or evaluation.get("candidate_sha256") != candidate.get("candidate_sha256")
            or evaluation.get("status") != "static_checks_passed"
        ):
            raise SelfIterationError(
                "static evaluation artifact does not match its ledger event"
            )
        return evaluation

    @staticmethod
    def _execution_claim_record(
        *,
        approval: dict[str, Any],
        approval_signature: str,
        approver_identity: dict[str, Any],
        claimed_at: str,
    ) -> dict[str, Any]:
        return {
            "schema": "anima.self_iteration.execution_claim.v1",
            "challenge_id": approval["challenge_id"],
            "approval_id": approval["approval_id"],
            "approval_sha256": execution_approval_sha256(approval),
            "approval_signature": approval_signature_record(
                approval, approval_signature
            ),
            "proposal_id": approval["proposal_id"],
            "candidate_id": approval["candidate_id"],
            "approver_identity": copy.deepcopy(approver_identity),
            "claimed_at": claimed_at,
            "automatic_retry_allowed": False,
            "authority_granted": False,
        }

    def _validate_execution_claim(
        self, claim: Any, *, approval: dict[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(claim, dict) or set(claim) != {
            "schema",
            "challenge_id",
            "approval_id",
            "approval_sha256",
            "approval_signature",
            "proposal_id",
            "candidate_id",
            "approver_identity",
            "claimed_at",
            "automatic_retry_allowed",
            "authority_granted",
        }:
            raise SelfIterationError("execution claim fields are malformed")
        try:
            parse_utc_timestamp(claim.get("claimed_at"), "claimed_at")
        except VerificationError as exc:
            raise SelfIterationError("execution claim timestamp is malformed") from exc
        raw_signature = claim.get("approval_signature")
        try:
            expected_signature = approval_signature_record(
                approval,
                (
                    raw_signature.get("value")
                    if isinstance(raw_signature, dict)
                    else None
                ),
            )
        except ExecutionError as exc:
            raise SelfIterationError("execution claim signature is malformed") from exc
        if (
            claim.get("schema") != "anima.self_iteration.execution_claim.v1"
            or claim.get("challenge_id") != approval["challenge_id"]
            or claim.get("approval_id") != approval["approval_id"]
            or claim.get("approval_sha256") != execution_approval_sha256(approval)
            or raw_signature != expected_signature
            or claim.get("proposal_id") != approval["proposal_id"]
            or claim.get("candidate_id") != approval["candidate_id"]
            or claim.get("approver_identity") != approval["approver_identity"]
            or claim.get("automatic_retry_allowed") is not False
            or claim.get("authority_granted") is not False
        ):
            raise SelfIterationError("execution claim binding is malformed")
        approval_signature = claim["approval_signature"]
        try:
            key = self._verifier_key_provider(
                approval_signature["approver_id"], approval_signature["key_id"]
            )
        except Exception as exc:
            raise SelfIterationError(
                "execution approval signing key registry is unavailable"
            ) from exc
        if not isinstance(key, VerifierKey) or not verify_execution_approval_signature(
            approval, approval_signature["value"], key
        ):
            raise SelfIterationError("execution claim approval signature is invalid")
        return copy.deepcopy(claim)

    @staticmethod
    def _execution_challenge_event(
        proposal: dict[str, Any], challenge_id: str
    ) -> dict[str, Any]:
        matches = [
            event
            for event in proposal["events"]
            if event.get("type") == "execution_approval_challenge_issued"
            and isinstance(event.get("approval"), dict)
            and event["approval"].get("challenge_id") == challenge_id
        ]
        if len(matches) != 1:
            raise SelfIterationError(
                "challenge_id does not name one execution approval"
            )
        return matches[0]

    def _passing_execution_result(
        self,
        *,
        proposal: dict[str, Any],
        candidate: dict[str, Any],
        execution_id: str,
        expected_result_sha256: str,
    ) -> dict[str, Any]:
        try:
            raw_results = self._patch_sandbox.load_execution_results(
                candidate["candidate_id"]
            )
        except PatchSandboxError as exc:
            raise SelfIterationError(str(exc)) from exc
        validated_results: list[dict[str, Any]] = []
        for raw_result in raw_results:
            try:
                result = validate_signed_execution_result(
                    raw_result, self._verifier_key_provider
                )
            except ExecutionError as exc:
                raise SelfIterationError(
                    "signed execution result artifact is invalid"
                ) from exc
            if result.get("execution_id") == execution_id:
                validated_results.append(result)
        if len(validated_results) != 1:
            raise SelfIterationError(
                "application requires one exact signed execution result"
            )
        result = validated_results[0]
        recorded = [
            event
            for event in proposal["events"]
            if event.get("type") == "isolated_execution_recorded"
            and event.get("execution_id") == execution_id
        ]
        if (
            result.get("result_sha256") != expected_result_sha256
            or result.get("candidate_id") != candidate.get("candidate_id")
            or result.get("candidate_sha256") != candidate.get("candidate_sha256")
            or result.get("outcome") != "passed"
            or result.get("execution_performed") is not True
            or result.get("tests_executed") is not True
            or result.get("cleanup_confirmed") is not True
            or result.get("eligible_for_external_review") is not True
            or result.get("eligible_for_apply") is not False
            or result.get("live_source_writes") is not False
            or len(recorded) != 1
            or recorded[0].get("result_sha256") != result["result_sha256"]
            or recorded[0].get("candidate_sha256") != result["candidate_sha256"]
            or recorded[0].get("approval_sha256") != result["approval_sha256"]
            or recorded[0].get("outcome") != "passed"
            or recorded[0].get("eligible_for_external_review") is not True
        ):
            raise SelfIterationError(
                "application requires the exact passing recorded execution digest"
            )
        challenge = self._execution_challenge_event(proposal, result["challenge_id"])
        if (
            challenge.get("approval") != result["approval"]
            or challenge.get("approval_sha256") != result["approval_sha256"]
        ):
            raise SelfIterationError(
                "signed execution result does not match its ledger approval"
            )
        return result

    @staticmethod
    def _application_claim_record(
        *,
        approval: dict[str, Any],
        approval_signature: str,
        reviewer_identity: dict[str, Any],
        claimed_at: str,
    ) -> dict[str, Any]:
        return {
            "schema": "anima.self_iteration.application_claim.v1",
            "challenge_id": approval["challenge_id"],
            "application_id": approval["application_id"],
            "approval_sha256": application_approval_sha256(approval),
            "approval_signature": application_signature_record(
                approval, approval_signature
            ),
            "proposal_id": approval["proposal_id"],
            "candidate_id": approval["candidate_id"],
            "execution_id": approval["execution_id"],
            "reviewer_identity": copy.deepcopy(reviewer_identity),
            "claimed_at": claimed_at,
            "automatic_retry_allowed": False,
            "authority_granted": False,
        }

    def _validate_application_claim(
        self, claim: Any, *, approval: dict[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(claim, dict) or set(claim) != {
            "schema",
            "challenge_id",
            "application_id",
            "approval_sha256",
            "approval_signature",
            "proposal_id",
            "candidate_id",
            "execution_id",
            "reviewer_identity",
            "claimed_at",
            "automatic_retry_allowed",
            "authority_granted",
        }:
            raise SelfIterationError("application claim fields are malformed")
        try:
            parse_utc_timestamp(claim.get("claimed_at"), "claimed_at")
        except VerificationError as exc:
            raise SelfIterationError(
                "application claim timestamp is malformed"
            ) from exc
        raw_signature = claim.get("approval_signature")
        try:
            expected_signature = application_signature_record(
                approval,
                raw_signature.get("value") if isinstance(raw_signature, dict) else None,
            )
        except ApplicationError as exc:
            raise SelfIterationError(
                "application claim signature is malformed"
            ) from exc
        if (
            claim.get("schema") != "anima.self_iteration.application_claim.v1"
            or claim.get("challenge_id") != approval["challenge_id"]
            or claim.get("application_id") != approval["application_id"]
            or claim.get("approval_sha256") != application_approval_sha256(approval)
            or raw_signature != expected_signature
            or claim.get("proposal_id") != approval["proposal_id"]
            or claim.get("candidate_id") != approval["candidate_id"]
            or claim.get("execution_id") != approval["execution_id"]
            or claim.get("reviewer_identity") != approval["reviewer_identity"]
            or claim.get("automatic_retry_allowed") is not False
            or claim.get("authority_granted") is not False
        ):
            raise SelfIterationError("application claim binding is malformed")
        signature = claim["approval_signature"]
        try:
            key = self._verifier_key_provider(
                signature["reviewer_id"], signature["key_id"]
            )
        except Exception as exc:
            raise SelfIterationError(
                "application reviewer key registry is unavailable"
            ) from exc
        if not isinstance(
            key, VerifierKey
        ) or not verify_application_approval_signature(
            approval, signature["value"], key
        ):
            raise SelfIterationError("application claim approval signature is invalid")
        return copy.deepcopy(claim)

    @staticmethod
    def _application_challenge_event(
        proposal: dict[str, Any], challenge_id: str
    ) -> dict[str, Any]:
        matches = [
            event
            for event in proposal["events"]
            if event.get("type") == "application_review_challenge_issued"
            and isinstance(event.get("approval"), dict)
            and event["approval"].get("challenge_id") == challenge_id
        ]
        if len(matches) != 1:
            raise SelfIterationError(
                "challenge_id does not name one application approval"
            )
        return matches[0]

    @staticmethod
    def _application_result_event(result: dict[str, Any]) -> dict[str, Any]:
        approval = result["approval"]
        return {
            "type": "reviewed_application_recorded",
            "at": result["applied_at"],
            "challenge_id": result["challenge_id"],
            "application_id": result["application_id"],
            "approval_sha256": result["application_approval_sha256"],
            "approval_signature_sha256": hashlib.sha256(
                canonical_json_bytes(result["approval_signature"])
            ).hexdigest(),
            "application_result_id": result["application_result_id"],
            "result_sha256": result["result_sha256"],
            "candidate_id": result["candidate_id"],
            "candidate_sha256": result["candidate_sha256"],
            "execution_id": result["execution_id"],
            "execution_result_sha256": result["execution_result_sha256"],
            "reviewer_identity": approval["reviewer_identity"],
            "result_signer_id": result["signature"]["signer_id"],
            "target_ref": result["target_ref"],
            "commit_oid": result["commit_oid"],
            "tree_oid": result["tree_oid"],
            "branch_created": True,
            "live_source_writes": False,
            "pushed": False,
            "merged": False,
            "deployed": False,
            "eligible_for_canary_review": True,
            "eligible_for_live_activation": False,
            "authority_granted": False,
        }

    def _passing_application_result(
        self,
        *,
        proposal: dict[str, Any],
        candidate: dict[str, Any],
        application_result_id: str,
        expected_result_sha256: str,
    ) -> dict[str, Any]:
        try:
            raw_results = self._patch_sandbox.load_application_results(
                candidate["candidate_id"]
            )
        except PatchSandboxError as exc:
            raise SelfIterationError(str(exc)) from exc
        matches: list[dict[str, Any]] = []
        for raw_result in raw_results:
            try:
                result = validate_signed_application_result(
                    raw_result, self._verifier_key_provider
                )
            except ApplicationError as exc:
                raise SelfIterationError(
                    "signed application result artifact is invalid"
                ) from exc
            if result.get("application_result_id") == application_result_id:
                matches.append(result)
        if len(matches) != 1:
            raise SelfIterationError(
                "canary review requires one exact signed application result"
            )
        result = matches[0]
        if (
            result.get("result_sha256") != expected_result_sha256
            or result.get("candidate_id") != candidate.get("candidate_id")
            or result.get("candidate_sha256") != candidate.get("candidate_sha256")
            or result.get("eligible_for_canary_review") is not True
            or result.get("eligible_for_live_activation") is not False
            or result.get("branch_created") is not True
            or result.get("pushed") is not False
            or result.get("merged") is not False
            or result.get("deployed") is not False
        ):
            raise SelfIterationError(
                "canary review requires the exact eligible application digest"
            )
        recorded = [
            event
            for event in proposal["events"]
            if event.get("type") == "reviewed_application_recorded"
            and event.get("application_result_id") == application_result_id
        ]
        if len(recorded) != 1 or recorded[0] != self._application_result_event(result):
            raise SelfIterationError(
                "signed application result does not match its ledger event"
            )
        challenge = self._application_challenge_event(proposal, result["challenge_id"])
        if (
            challenge.get("approval") != result["approval"]
            or challenge.get("approval_sha256") != result["application_approval_sha256"]
        ):
            raise SelfIterationError(
                "signed application result does not match its ledger approval"
            )
        if self.repo_root is None or not self._application_writer.verify_result(
            repo_root=self.repo_root, result=result
        ):
            raise SelfIterationError(
                "reviewed application Git ref failed integrity verification"
            )
        return result

    @staticmethod
    def _canary_claim_record(
        *,
        approval: dict[str, Any],
        approval_signature: str,
        reviewer_identity: dict[str, Any],
        claimed_at: str,
    ) -> dict[str, Any]:
        return {
            "schema": "anima.self_iteration.canary_claim.v1",
            "challenge_id": approval["challenge_id"],
            "canary_id": approval["canary_id"],
            "approval_sha256": canary_approval_sha256(approval),
            "approval_signature": canary_signature_record(approval, approval_signature),
            "proposal_id": approval["proposal_id"],
            "candidate_id": approval["candidate_id"],
            "application_result_id": approval["application_result_id"],
            "reviewer_identity": copy.deepcopy(reviewer_identity),
            "claimed_at": claimed_at,
            "automatic_retry_allowed": False,
            "persistent_activation_allowed": False,
            "authority_granted": False,
        }

    def _validate_canary_claim(
        self, claim: Any, *, approval: dict[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(claim, dict) or set(claim) != {
            "schema",
            "challenge_id",
            "canary_id",
            "approval_sha256",
            "approval_signature",
            "proposal_id",
            "candidate_id",
            "application_result_id",
            "reviewer_identity",
            "claimed_at",
            "automatic_retry_allowed",
            "persistent_activation_allowed",
            "authority_granted",
        }:
            raise SelfIterationError("canary claim fields are malformed")
        try:
            parse_utc_timestamp(claim.get("claimed_at"), "claimed_at")
        except VerificationError as exc:
            raise SelfIterationError("canary claim timestamp is malformed") from exc
        raw_signature = claim.get("approval_signature")
        try:
            expected_signature = canary_signature_record(
                approval,
                raw_signature.get("value") if isinstance(raw_signature, dict) else None,
            )
        except CanaryError as exc:
            raise SelfIterationError("canary claim signature is malformed") from exc
        if (
            claim.get("schema") != "anima.self_iteration.canary_claim.v1"
            or claim.get("challenge_id") != approval["challenge_id"]
            or claim.get("canary_id") != approval["canary_id"]
            or claim.get("approval_sha256") != canary_approval_sha256(approval)
            or raw_signature != expected_signature
            or claim.get("proposal_id") != approval["proposal_id"]
            or claim.get("candidate_id") != approval["candidate_id"]
            or claim.get("application_result_id") != approval["application_result_id"]
            or claim.get("reviewer_identity") != approval["reviewer_identity"]
            or claim.get("automatic_retry_allowed") is not False
            or claim.get("persistent_activation_allowed") is not False
            or claim.get("authority_granted") is not False
        ):
            raise SelfIterationError("canary claim binding is malformed")
        signature = claim["approval_signature"]
        try:
            key = self._verifier_key_provider(
                signature["reviewer_id"], signature["key_id"]
            )
        except Exception as exc:
            raise SelfIterationError(
                "canary reviewer key registry is unavailable"
            ) from exc
        if not isinstance(key, VerifierKey) or not verify_canary_approval_signature(
            approval, signature["value"], key
        ):
            raise SelfIterationError("canary claim approval signature is invalid")
        return copy.deepcopy(claim)

    @staticmethod
    def _canary_challenge_event(
        proposal: dict[str, Any], challenge_id: str
    ) -> dict[str, Any]:
        matches = [
            event
            for event in proposal["events"]
            if event.get("type") == "canary_review_challenge_issued"
            and isinstance(event.get("approval"), dict)
            and event["approval"].get("challenge_id") == challenge_id
        ]
        if len(matches) != 1:
            raise SelfIterationError("challenge_id does not name one canary approval")
        return matches[0]

    @staticmethod
    def _canary_result_event(result: dict[str, Any]) -> dict[str, Any]:
        approval = result["approval"]
        return {
            "type": "transient_canary_recorded",
            "at": result["finished_at"],
            "challenge_id": result["challenge_id"],
            "canary_id": result["canary_id"],
            "approval_sha256": canary_approval_sha256(approval),
            "approval_signature_sha256": hashlib.sha256(
                canonical_json_bytes(result["approval_signature"])
            ).hexdigest(),
            "canary_result_id": result["canary_result_id"],
            "result_sha256": result["result_sha256"],
            "candidate_id": result["candidate_id"],
            "application_result_id": result["application_result_id"],
            "application_result_sha256": result["application_result_sha256"],
            "reviewer_identity": approval["reviewer_identity"],
            "supervisor_signer_id": result["signature"]["signer_id"],
            "outcome": result["outcome"],
            "activation_performed": result["activation_performed"],
            "health_checks_sha256": hashlib.sha256(
                canonical_json_bytes(result["health_checks"])
            ).hexdigest(),
            "baseline_restore_attempted": result["baseline_restore_attempted"],
            "baseline_restored": result["baseline_restored"],
            "persistent_activation_retained": False,
            "recommended_decision": result["recommended_decision"],
            "eligible_for_merge_review": result["eligible_for_merge_review"],
            "eligible_for_live_activation": False,
            "authority_granted": False,
        }

    def propose(
        self,
        *,
        observation: Any,
        hypothesis: Any,
        expected_outcome: Any,
        evidence: Any,
        target_paths: Any,
        verification: Any,
        rollback_plan: Any = None,
        risk: Any = "medium",
        claimed_source: Any = "self_observation",
    ) -> dict[str, Any]:
        """Persist an evidence-backed proposal without changing source code."""
        observation_text = _required_text(observation, "observation")
        hypothesis_text = _required_text(hypothesis, "hypothesis")
        expected_text = _required_text(expected_outcome, "expected_outcome")
        evidence_items = _string_list(evidence, "evidence")
        verification_items = _string_list(verification, "verification")
        target_items = _string_list(target_paths, "target_paths", item_max_length=500)
        normalized_targets = [_normalize_repo_path(item) for item in target_items]
        if len(set(normalized_targets)) != len(normalized_targets):
            raise SelfIterationError("target_paths may not contain duplicates")

        if not isinstance(risk, str) or risk not in _RISK_ORDER:
            raise SelfIterationError("risk must be one of: low, medium, high")
        allowed_sources = {
            "self_observation",
            "test_failure",
            "caretaker",
            "governance",
        }
        if not isinstance(claimed_source, str) or claimed_source not in allowed_sources:
            raise SelfIterationError(
                "claimed_source must be one of: " + ", ".join(sorted(allowed_sources))
            )

        rollback_text = (
            _required_text(rollback_plan, "rollback_plan")
            if rollback_plan is not None
            else "Revert the implementing commit and restore the prior known-good deployment."
        )
        boundaries = [self.classify_target(path) for path in normalized_targets]
        risk_floor = max(
            (str(item["risk_floor"]) for item in boundaries),
            key=lambda level: _RISK_ORDER[level],
        )
        effective_risk = max(
            (str(risk), risk_floor), key=lambda level: _RISK_ORDER[level]
        )
        if any(item["boundary"] == "protected_core" for item in boundaries):
            status = "protected_review_required"
        elif any(not item["auto_implementation_eligible"] for item in boundaries):
            status = "human_review_required"
        else:
            status = "ready_for_isolated_implementation"

        created_at = _isoformat(self._clock())
        proposal_id = f"si-{created_at[:10].replace('-', '')}-{uuid.uuid4().hex[:10]}"
        provenance = self._server_provenance(created_at)
        proposal = {
            "id": proposal_id,
            "created_at": created_at,
            "source_claim": _claim_envelope(claimed_source, field="claimed_source"),
            "provenance": provenance,
            "proposer_identity": self._identity_from_provenance(
                provenance,
                label="self-iteration proposal",
                required=False,
            ),
            "trust_policy": _zero_weight_trust_policy(),
            "status": status,
            "observation": observation_text,
            "hypothesis": hypothesis_text,
            "expected_outcome": expected_text,
            "evidence": evidence_items,
            "evidence_epistemic_status": "caller_asserted",
            "target_paths": normalized_targets,
            "verification": verification_items,
            "rollback_plan": rollback_text,
            "risk": {
                "self_assessed": risk,
                "boundary_floor": risk_floor,
                "effective": effective_risk,
            },
            "boundaries": boundaries,
            "code_fingerprint": self._code_fingerprint(),
            "implementation_policy": {
                "mode": "proposal_only",
                "source_writes_performed": False,
                "commands_executed": False,
                "provenance_authorizes_execution": False,
                "required_path": "isolated branch -> tests -> review -> canary -> measured outcome",
            },
            "events": [
                {
                    "type": "proposed",
                    "at": created_at,
                    "status": status,
                }
            ],
        }
        proposal["content_sha256"] = proposal_content_sha256(proposal)

        with self._lock:
            ledger = self._load_ledger()
            ledger["proposals"].append(proposal)
            self._save_ledger(ledger)
        return self._public_proposal(proposal)

    def list_proposals(
        self,
        *,
        limit: int = 10,
        status: str | None = None,
        proposal_id: str | None = None,
    ) -> dict[str, Any]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise SelfIterationError("limit must be between 1 and 100")
        with self._lock:
            proposals = list(self._load_ledger()["proposals"])
        if proposal_id is not None:
            proposals = [item for item in proposals if item.get("id") == proposal_id]
        if status is not None:
            proposals = [item for item in proposals if item.get("status") == status]
        proposals = [
            self._public_proposal(item) for item in list(reversed(proposals))[:limit]
        ]
        return {"count": len(proposals), "proposals": proposals}

    def prepare_verification(
        self,
        *,
        proposal_id: Any,
        verification_decision: Any,
        verification_statement: Any,
        verification_evidence: Any,
        expected_content_sha256: Any,
        expires_at: Any = None,
        target_attestation_id: Any = None,
    ) -> dict[str, Any]:
        """Append a one-time challenge for an independent verifier to sign."""
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        if verification_decision not in {"verified", "rejected", "revoke"}:
            raise SelfIterationError(
                "verification_decision must be one of: verified, rejected, revoke"
            )
        statement = _required_text(
            verification_statement, "verification_statement", max_length=4000
        )
        try:
            evidence = validate_evidence(verification_evidence)
        except VerificationError as exc:
            raise SelfIterationError(str(exc)) from exc
        expected_digest = _required_text(
            expected_content_sha256,
            "expected_content_sha256",
            max_length=64,
        ).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            raise SelfIterationError(
                "expected_content_sha256 must be exactly 64 hexadecimal characters"
            )
        target_id = (
            _required_text(
                target_attestation_id,
                "target_attestation_id",
                max_length=100,
            )
            if target_attestation_id is not None
            else None
        )

        with self._lock:
            ledger = self._load_ledger()
            proposal = self._find_proposal(ledger, proposal_id_text)
            if proposal["content_sha256"] != expected_digest:
                raise SelfIterationError(
                    "proposal content digest changed; inspect the proposal again"
                )

            now = self._now_utc()
            recorded_at = _isoformat(now)
            receipt = self._server_provenance(recorded_at)
            verifier_identity = self._identity_from_provenance(
                receipt,
                label="verification request",
                required=True,
            )
            proposer_identity = self._identity_from_provenance(
                proposal.get("provenance"),
                label="proposal",
                required=True,
            )
            assert verifier_identity is not None
            assert proposer_identity is not None
            if proposal.get("proposer_identity") != proposer_identity:
                raise SelfIterationError(
                    "proposal proposer identity binding is invalid"
                )
            if verifier_identity == proposer_identity:
                raise SelfIterationError(
                    "the authenticated proposer may not verify its own proposal"
                )

            key = self._resolve_verifier_key(verifier_identity)
            state = self._verification_state(proposal, now=now)
            if state["status"] == "invalid":
                raise SelfIterationError(
                    "proposal contains an invalid attestation; refusing a new challenge"
                )

            expiry: datetime | None
            if verification_decision == "revoke":
                if expires_at is not None:
                    raise SelfIterationError("expires_at is not valid for a revocation")
                if target_id is None:
                    raise SelfIterationError(
                        "target_attestation_id is required for a revocation"
                    )
                target = self._validated_attestation(proposal, target_id, now=now)[
                    "attestation"
                ]
                if target.get("decision") == "revoke":
                    raise SelfIterationError("a revocation may not target a revocation")
                if target.get("verifier_identity") != verifier_identity:
                    raise SelfIterationError(
                        "only the original verifier may revoke an attestation"
                    )
                if target_id in state["revoked_attestation_ids"]:
                    raise SelfIterationError("target attestation is already revoked")
                expiry = None
            else:
                if target_id is not None:
                    raise SelfIterationError(
                        "target_attestation_id is only valid for a revocation"
                    )
                if any(
                    event.get("attestation", {}).get("verifier_identity")
                    == verifier_identity
                    and event.get("attestation", {}).get("attestation_id")
                    in state["active_attestation_ids"]
                    for event in proposal["events"]
                    if isinstance(event.get("attestation"), dict)
                ):
                    raise SelfIterationError(
                        "verifier already has an active verdict; revoke it first"
                    )
                if expires_at is None:
                    expiry = now + timedelta(days=1)
                else:
                    try:
                        expiry = parse_utc_timestamp(expires_at, "expires_at")
                    except VerificationError as exc:
                        raise SelfIterationError(str(exc)) from exc
                if expiry <= now:
                    raise SelfIterationError("expires_at must be in the future")
                if expiry - now > MAX_ATTESTATION_VALIDITY:
                    raise SelfIterationError(
                        "expires_at may be at most seven days after issuance"
                    )

            challenge_id = f"sic-{uuid.uuid4().hex}"
            attestation_id = f"sia-{uuid.uuid4().hex}"
            try:
                attestation = build_attestation(
                    proposal=proposal,
                    verifier_key=key,
                    verifier_identity=verifier_identity,
                    decision=verification_decision,
                    statement=statement,
                    evidence=evidence,
                    issued_at=now,
                    expires_at=expiry,
                    challenge_id=challenge_id,
                    attestation_id=attestation_id,
                    target_attestation_id=target_id,
                )
                signing_bytes = canonical_json_bytes(attestation)
            except VerificationError as exc:
                raise SelfIterationError(str(exc)) from exc
            signing_digest = hashlib.sha256(signing_bytes).hexdigest()
            proposal["events"].append(
                {
                    "type": "verification_challenge_issued",
                    "at": recorded_at,
                    "challenge_id": challenge_id,
                    "attestation": attestation,
                    "signing_sha256": signing_digest,
                    "provenance": receipt,
                    "authority_granted": False,
                }
            )
            self._save_ledger(ledger)

        return {
            "proposal_id": proposal_id_text,
            "challenge_id": challenge_id,
            "attestation_id": attestation_id,
            "attestation": attestation,
            "signing_input_b64": attestation_signing_input_b64(attestation),
            "signing_sha256": signing_digest,
            "signature_algorithm": SIGNATURE_ALGORITHM,
            "challenge_expires_at": attestation["challenge_expires_at"],
            "instructions": (
                "Base64url-decode signing_input_b64, compute HMAC-SHA256 with "
                "the configured verifier key, and submit the lowercase hexadecimal "
                "MAC with record_verification before challenge_expires_at."
            ),
            "authority_granted": False,
        }

    def record_verification(
        self,
        *,
        proposal_id: Any,
        challenge_id: Any,
        signature: Any,
    ) -> dict[str, Any]:
        """Verify a one-time challenge signature and append the signed verdict."""
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        challenge_id_text = _required_text(challenge_id, "challenge_id", max_length=100)
        if not re.fullmatch(r"sic-[0-9a-f]{32}", challenge_id_text):
            raise SelfIterationError("challenge_id is malformed")
        signature_text = _required_text(signature, "signature", max_length=64).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", signature_text):
            raise SelfIterationError(
                "signature must be exactly 64 hexadecimal characters"
            )

        with self._lock:
            ledger = self._load_ledger()
            proposal = self._find_proposal(ledger, proposal_id_text)
            challenges = [
                event
                for event in proposal["events"]
                if event.get("type") == "verification_challenge_issued"
                and event.get("challenge_id") == challenge_id_text
            ]
            if len(challenges) != 1:
                raise SelfIterationError(
                    "challenge_id does not name one issued verification challenge"
                )
            if any(
                event.get("type") == "verification_attested"
                and event.get("challenge_id") == challenge_id_text
                for event in proposal["events"]
            ):
                raise SelfIterationError("verification challenge has already been used")

            challenge = challenges[0]
            attestation = challenge.get("attestation")
            if not isinstance(attestation, dict):
                raise SelfIterationError("verification challenge is malformed")
            signing_digest = hashlib.sha256(
                canonical_json_bytes(attestation)
            ).hexdigest()
            if challenge.get("signing_sha256") != signing_digest:
                raise SelfIterationError("verification challenge digest is malformed")
            if attestation.get("proposal_id") != proposal_id_text:
                raise SelfIterationError(
                    "verification challenge belongs to another proposal"
                )
            if attestation.get("proposal_content_sha256") != proposal.get(
                "content_sha256"
            ) or proposal_content_sha256(proposal) != proposal.get("content_sha256"):
                raise SelfIterationError(
                    "verification challenge proposal digest is stale"
                )

            now = self._now_utc()
            try:
                challenge_expires_at = parse_utc_timestamp(
                    attestation.get("challenge_expires_at"),
                    "challenge_expires_at",
                )
            except VerificationError as exc:
                raise SelfIterationError(str(exc)) from exc
            if now >= challenge_expires_at:
                raise SelfIterationError("verification challenge has expired")

            recorded_at = _isoformat(now)
            receipt = self._server_provenance(recorded_at)
            verifier_identity = self._identity_from_provenance(
                receipt,
                label="verification request",
                required=True,
            )
            proposer_identity = self._identity_from_provenance(
                proposal.get("provenance"),
                label="proposal",
                required=True,
            )
            assert verifier_identity is not None
            assert proposer_identity is not None
            if attestation.get("verifier_identity") != verifier_identity:
                raise SelfIterationError(
                    "authenticated verifier does not own this challenge"
                )
            if attestation.get("proposer_identity") != proposer_identity:
                raise SelfIterationError("verification challenge proposer is stale")
            if verifier_identity == proposer_identity:
                raise SelfIterationError(
                    "the authenticated proposer may not verify its own proposal"
                )

            key_id = attestation.get("key_id")
            if not isinstance(key_id, str):
                raise SelfIterationError("verification challenge key ID is malformed")
            key = self._resolve_verifier_key(verifier_identity, key_id)
            if not verify_attestation_signature(attestation, signature_text, key):
                raise SelfIterationError("verification signature is invalid")

            state = self._verification_state(proposal, now=now)
            if state["status"] == "invalid":
                raise SelfIterationError(
                    "proposal contains an invalid attestation; refusing a new verdict"
                )
            attestation_decision = attestation.get("decision")
            if attestation_decision in {"verified", "rejected"} and any(
                event.get("attestation", {}).get("verifier_identity")
                == verifier_identity
                and event.get("attestation", {}).get("attestation_id")
                in state["active_attestation_ids"]
                for event in proposal["events"]
                if isinstance(event.get("attestation"), dict)
            ):
                raise SelfIterationError(
                    "verifier already has an active verdict; revoke it first"
                )
            if attestation_decision == "revoke":
                target_id = attestation.get("target_attestation_id")
                if not isinstance(target_id, str):
                    raise SelfIterationError("revocation target is malformed")
                target = self._validated_attestation(proposal, target_id, now=now)[
                    "attestation"
                ]
                if target.get("decision") == "revoke":
                    raise SelfIterationError("a revocation may not target a revocation")
                if target.get("verifier_identity") != verifier_identity:
                    raise SelfIterationError(
                        "only the original verifier may revoke an attestation"
                    )
                if target_id in state["revoked_attestation_ids"]:
                    raise SelfIterationError("target attestation is already revoked")

            event = {
                "type": "verification_attested",
                "at": recorded_at,
                "challenge_id": challenge_id_text,
                "attestation": copy.deepcopy(attestation),
                "signature": {
                    "algorithm": SIGNATURE_ALGORITHM,
                    "key_id": key_id,
                    "value": signature_text,
                    "assurance": "symmetric_mac_server_verifiable",
                },
                "provenance": receipt,
                "authority_granted": False,
            }
            proposal["events"].append(event)
            post_state = self._verification_state(proposal, now=now)
            if post_state["status"] == "invalid":
                proposal["events"].pop()
                raise SelfIterationError(
                    "signed verification failed post-append validation"
                )
            self._save_ledger(ledger)
        return self._public_proposal(proposal, now=now)

    def verification_status(self, *, proposal_id: Any) -> dict[str, Any]:
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        with self._lock:
            ledger = self._load_ledger()
            proposal = self._find_proposal(ledger, proposal_id_text)
            state = self._verification_state(proposal)
        return {
            "proposal_id": proposal_id_text,
            "content_sha256": proposal["content_sha256"],
            "verification_state": state,
            "verification_contract": verification_contract(),
        }

    def construct_patch(
        self,
        *,
        proposal_id: Any,
        expected_content_sha256: Any,
        changes: Any,
    ) -> dict[str, Any]:
        """Construct an inert, proposal-bound artifact outside live source."""
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        expected_digest = _required_text(
            expected_content_sha256,
            "expected_content_sha256",
            max_length=64,
        ).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            raise SelfIterationError(
                "expected_content_sha256 must be exactly 64 hexadecimal characters"
            )
        if not isinstance(changes, list) or not changes:
            raise SelfIterationError("changes must be a non-empty list")

        candidate: dict[str, Any] | None = None
        with self._lock:
            try:
                ledger = self._load_ledger()
                proposal = self._find_proposal(ledger, proposal_id_text)
                now = self._now_utc()
                state = self._patch_eligible_state(
                    proposal,
                    expected_content_sha256=expected_digest,
                    now=now,
                )
                source_fingerprint = self._assert_current_proposal_source(proposal)
                proposal_targets = set(proposal["target_paths"])
                normalized_change_paths: list[str] = []
                for change in changes:
                    if not isinstance(change, dict):
                        raise SelfIterationError("each change must be an object")
                    raw_path = change.get("path")
                    if not isinstance(raw_path, str):
                        raise SelfIterationError("change path must be a string")
                    path = _normalize_repo_path(raw_path)
                    if path not in proposal_targets:
                        raise SelfIterationError(
                            f"candidate path was not bound by the proposal: {path}"
                        )
                    boundary = self.classify_target(path)
                    if (
                        boundary["boundary"] != "bounded_candidate"
                        or boundary["auto_implementation_eligible"] is not True
                    ):
                        raise SelfIterationError(
                            f"candidate path is outside the bounded allowlist: {path}"
                        )
                    normalized_change_paths.append(path)

                recorded_at = _isoformat(now)
                receipt = self._server_provenance(recorded_at)
                author_identity = self._identity_from_provenance(
                    receipt,
                    label="patch construction request",
                    required=True,
                )
                proposer_identity = self._identity_from_provenance(
                    proposal.get("provenance"),
                    label="proposal",
                    required=True,
                )
                assert author_identity is not None
                assert proposer_identity is not None
                if (
                    proposal.get("proposer_identity") != proposer_identity
                    or author_identity != proposer_identity
                ):
                    raise SelfIterationError(
                        "only the authenticated proposal author may construct its patch"
                    )

                candidate = self._patch_sandbox.construct(
                    proposal_id=proposal_id_text,
                    proposal_content_sha256=expected_digest,
                    source_fingerprint=source_fingerprint,
                    proposer_identity=proposer_identity,
                    author_identity=author_identity,
                    active_attestation_ids=state["active_attestation_ids"],
                    changes=changes,
                    created_at=recorded_at,
                )
                self._assert_current_proposal_source(proposal)
                event = {
                    "type": "patch_candidate_constructed",
                    "at": recorded_at,
                    "candidate_id": candidate["candidate_id"],
                    "candidate_sha256": candidate["candidate_sha256"],
                    "proposal_content_sha256": expected_digest,
                    "source_fingerprint": source_fingerprint,
                    "author_identity": author_identity,
                    "active_attestation_ids": sorted(state["active_attestation_ids"]),
                    "paths": sorted(normalized_change_paths),
                    "patch_sha256": candidate["patch"]["sha256"],
                    "provenance": receipt,
                    "execution_performed": False,
                    "tests_executed": False,
                    "live_source_writes": False,
                    "authority_granted": False,
                }
                proposal["events"].append(event)
                self._save_ledger(ledger)
            except PatchSandboxError as exc:
                if candidate is not None:
                    try:
                        self._patch_sandbox.discard_candidate(candidate["candidate_id"])
                    except (OSError, PatchSandboxError):
                        pass
                raise SelfIterationError(str(exc)) from exc
            except BaseException:
                if candidate is not None:
                    try:
                        self._patch_sandbox.discard_candidate(candidate["candidate_id"])
                    except (OSError, PatchSandboxError):
                        pass
                raise

        assert candidate is not None
        return {
            "candidate": candidate,
            "sandbox_contract": sandbox_contract(),
            "next_step": (
                "Run evaluate_patch for non-executing static checks. Eligible Python era "
                "candidates may then be submitted to a distinct approver with prepare_execution."
            ),
            "authority_granted": False,
        }

    def evaluate_patch(
        self,
        *,
        proposal_id: Any,
        candidate_id: Any,
        expected_candidate_sha256: Any,
    ) -> dict[str, Any]:
        """Evaluate an artifact without importing or executing candidate code."""
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        candidate_id_text = _required_text(candidate_id, "candidate_id", max_length=100)
        expected_digest = _required_text(
            expected_candidate_sha256,
            "expected_candidate_sha256",
            max_length=64,
        ).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            raise SelfIterationError(
                "expected_candidate_sha256 must be exactly 64 hexadecimal characters"
            )

        evaluation: dict[str, Any] | None = None
        with self._lock:
            try:
                ledger = self._load_ledger()
                proposal = self._find_proposal(ledger, proposal_id_text)
                now = self._now_utc()
                state = self._patch_eligible_state(
                    proposal,
                    expected_content_sha256=proposal["content_sha256"],
                    now=now,
                )
                self._assert_current_proposal_source(proposal)
                candidate = self._patch_sandbox.load_manifest(candidate_id_text)
                if candidate.get("candidate_sha256") != expected_digest:
                    raise SelfIterationError(
                        "candidate digest changed; inspect the candidate again"
                    )
                self._assert_candidate_binding(
                    proposal=proposal,
                    candidate=candidate,
                    state=state,
                )
                recorded_at = _isoformat(now)
                receipt = self._server_provenance(recorded_at)
                requester_identity = self._identity_from_provenance(
                    receipt,
                    label="patch evaluation request",
                    required=True,
                )
                assert requester_identity is not None
                evaluation = self._patch_sandbox.evaluate(
                    candidate_id=candidate_id_text,
                    expected_candidate_sha256=expected_digest,
                    evaluated_at=recorded_at,
                )
                self._assert_current_proposal_source(proposal)
                post_state = self._patch_eligible_state(
                    proposal,
                    expected_content_sha256=proposal["content_sha256"],
                    now=now,
                )
                self._assert_candidate_binding(
                    proposal=proposal,
                    candidate=candidate,
                    state=post_state,
                )
                event = {
                    "type": "patch_candidate_evaluated",
                    "at": recorded_at,
                    "candidate_id": candidate_id_text,
                    "candidate_sha256": expected_digest,
                    "proposal_content_sha256": proposal["content_sha256"],
                    "evaluation_id": evaluation["evaluation_id"],
                    "evaluation_sha256": evaluation["evaluation_sha256"],
                    "evaluator_id": evaluation["evaluator"]["id"],
                    "evaluator_contract_sha256": evaluation["evaluator"][
                        "contract_sha256"
                    ],
                    "requester_identity": requester_identity,
                    "status": evaluation["status"],
                    "eligible_for_external_review": evaluation[
                        "eligible_for_external_review"
                    ],
                    "eligible_for_execution": False,
                    "execution_performed": False,
                    "tests_executed": False,
                    "live_source_writes": False,
                    "authority_granted": False,
                    "provenance": receipt,
                }
                proposal["events"].append(event)
                self._save_ledger(ledger)
            except PatchSandboxError as exc:
                if evaluation is not None:
                    try:
                        self._patch_sandbox.discard_evaluation(
                            candidate_id_text,
                            evaluation["evaluation_id"],
                        )
                    except (OSError, PatchSandboxError):
                        pass
                raise SelfIterationError(str(exc)) from exc
            except BaseException:
                if evaluation is not None:
                    try:
                        self._patch_sandbox.discard_evaluation(
                            candidate_id_text,
                            evaluation["evaluation_id"],
                        )
                    except (OSError, PatchSandboxError):
                        pass
                raise

        assert evaluation is not None
        return {
            "evaluation": evaluation,
            "next_step": (
                "Static success permits external review only. An eligible Python era "
                "candidate still requires a distinct signed prepare_execution approval "
                "before its fixed tests may run in Docker."
            ),
            "authority_granted": False,
        }

    def patch_status(
        self,
        *,
        proposal_id: Any,
        candidate_id: Any,
        include_patch: Any = False,
    ) -> dict[str, Any]:
        """Read one candidate and reconcile artifacts with ledger events."""
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        candidate_id_text = _required_text(candidate_id, "candidate_id", max_length=100)
        if not isinstance(include_patch, bool):
            raise SelfIterationError("include_patch must be a boolean")
        with self._lock:
            ledger = self._load_ledger()
            proposal = self._find_proposal(ledger, proposal_id_text)
            if include_patch:
                receipt = self._server_provenance(_isoformat(self._now_utc()))
                self._identity_from_provenance(
                    receipt,
                    label="patch content request",
                    required=True,
                )
            try:
                artifact = self._patch_sandbox.status(
                    candidate_id_text,
                    include_patch=include_patch,
                )
            except PatchSandboxError as exc:
                raise SelfIterationError(str(exc)) from exc
            candidate = artifact["candidate"]
            self._assert_candidate_binding(
                proposal=proposal,
                candidate=candidate,
            )
            recorded_events = [
                event
                for event in proposal["events"]
                if event.get("type") == "patch_candidate_evaluated"
                and event.get("candidate_id") == candidate_id_text
            ]
            recorded_by_id = {
                event["evaluation_id"]: event for event in recorded_events
            }
            artifacts_by_id = {
                item["evaluation_id"]: item for item in artifact["evaluations"]
            }
            recorded_evaluations: list[dict[str, Any]] = []
            for evaluation_id, event in recorded_by_id.items():
                evaluation = artifacts_by_id.get(evaluation_id)
                if (
                    evaluation is None
                    or evaluation.get("evaluation_sha256")
                    != event.get("evaluation_sha256")
                    or evaluation.get("candidate_sha256")
                    != candidate.get("candidate_sha256")
                    or evaluation.get("status") != event.get("status")
                ):
                    raise SelfIterationError(
                        "recorded evaluation artifact does not match its ledger event"
                    )
                recorded_evaluations.append(evaluation)
            artifact["evaluations"] = recorded_evaluations
            artifact["unledgered_evaluation_artifact_count"] = len(
                set(artifacts_by_id) - set(recorded_by_id)
            )

            now = self._now_utc()
            verification_state = self._verification_state(proposal, now=now)
            try:
                self._assert_current_proposal_source(proposal)
            except SelfIterationError:
                source_current = False
            else:
                source_current = True
            attestation_binding_current = candidate["proposal_binding"][
                "active_attestation_ids"
            ] == verification_state.get("active_attestation_ids")
            execution_profile_supported = execution_profile(
                "display_era_pytest_v1"
            ).supports([item["path"] for item in candidate["files"]])
            static_pass_recorded = any(
                item.get("status") == "static_checks_passed"
                for item in recorded_evaluations
            )
            base_eligible = bool(
                proposal["status"] == "ready_for_isolated_implementation"
                and proposal.get("risk", {}).get("effective") == "low"
                and verification_state["status"] == "verified"
                and source_current
                and attestation_binding_current
            )
            artifact["current_state"] = {
                "proposal_status": proposal["status"],
                "verification_status": verification_state["status"],
                "source_fingerprint_current": source_current,
                "active_attestation_binding_current": attestation_binding_current,
                "eligible_for_new_static_evaluation": base_eligible,
                "eligible_for_execution_approval": bool(
                    base_eligible
                    and static_pass_recorded
                    and execution_profile_supported
                ),
                "execution_profile_supported": execution_profile_supported,
                "eligible_for_execution": False,
                "authority_granted": False,
            }
            artifact["sandbox_contract"] = sandbox_contract()
            return artifact

    def prepare_execution(
        self,
        *,
        proposal_id: Any,
        candidate_id: Any,
        expected_candidate_sha256: Any,
        evaluation_id: Any,
        expected_evaluation_sha256: Any,
        execution_profile_id: Any = "display_era_pytest_v1",
    ) -> dict[str, Any]:
        """Issue a short-lived plan for one externally approved execution."""
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        candidate_id_text = _required_text(candidate_id, "candidate_id", max_length=100)
        candidate_digest = _required_text(
            expected_candidate_sha256,
            "expected_candidate_sha256",
            max_length=64,
        ).lower()
        evaluation_id_text = _required_text(
            evaluation_id, "evaluation_id", max_length=100
        )
        evaluation_digest = _required_text(
            expected_evaluation_sha256,
            "expected_evaluation_sha256",
            max_length=64,
        ).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", candidate_digest):
            raise SelfIterationError("expected_candidate_sha256 is malformed")
        if not re.fullmatch(r"sie-[0-9a-f]{32}", evaluation_id_text):
            raise SelfIterationError("evaluation_id is malformed")
        if not re.fullmatch(r"[0-9a-f]{64}", evaluation_digest):
            raise SelfIterationError("expected_evaluation_sha256 is malformed")
        try:
            profile = execution_profile(execution_profile_id)
        except ExecutionError as exc:
            raise SelfIterationError(str(exc)) from exc

        with self._lock:
            try:
                ledger = self._load_ledger()
                proposal = self._find_proposal(ledger, proposal_id_text)
                now = self._now_utc()
                state = self._patch_eligible_state(
                    proposal,
                    expected_content_sha256=proposal["content_sha256"],
                    now=now,
                )
                source_fingerprint = self._assert_current_proposal_source(proposal)
                candidate, contents = self._patch_sandbox.execution_material(
                    candidate_id_text
                )
                if candidate.get("candidate_sha256") != candidate_digest:
                    raise SelfIterationError(
                        "candidate digest changed; inspect the candidate again"
                    )
                self._assert_candidate_binding(
                    proposal=proposal, candidate=candidate, state=state
                )
                self._passing_evaluation(
                    proposal=proposal,
                    candidate=candidate,
                    evaluation_id=evaluation_id_text,
                    expected_evaluation_sha256=evaluation_digest,
                )
                candidate_paths = [item["path"] for item in candidate["files"]]
                if not profile.supports(candidate_paths):
                    raise SelfIterationError(
                        "candidate paths are outside the fixed execution profile"
                    )

                recorded_at = _isoformat(now)
                receipt = self._server_provenance(recorded_at)
                approver_identity = self._identity_from_provenance(
                    receipt,
                    label="execution approval request",
                    required=True,
                )
                assert approver_identity is not None
                proposer_identity = proposal.get("proposer_identity")
                verifier_identities = self._active_verifier_identities(proposal, state)
                if approver_identity == proposer_identity or approver_identity in (
                    verifier_identities
                ):
                    raise SelfIterationError(
                        "execution approver must differ from the proposer and active verifiers"
                    )
                approval_key = self._resolve_verifier_key(approver_identity)

                result_signer_id = os.environ.get(RUNNER_SIGNER_ID_ENV)
                if not isinstance(result_signer_id, str) or not result_signer_id:
                    raise SelfIterationError(
                        f"{RUNNER_SIGNER_ID_ENV} must name a dedicated result signer"
                    )
                participant_ids = {
                    identity.get("id")
                    for identity in [
                        proposer_identity,
                        approver_identity,
                        *verifier_identities,
                    ]
                    if isinstance(identity, dict)
                }
                if result_signer_id in participant_ids:
                    raise SelfIterationError(
                        "execution result signer must differ from all proposal participants"
                    )
                result_signer_identity = {
                    "kind": "service_signer",
                    "id": result_signer_id,
                    "issuer": None,
                }
                result_key = self._resolve_verifier_key(result_signer_identity)

                runner_identity = self._isolation_runner.probe()
                if self.repo_root is None:
                    raise SelfIterationError("source repository not found")
                revision = source_fingerprint.get("revision")
                if not isinstance(revision, str):
                    raise SelfIterationError(
                        "isolated execution requires a committed source revision"
                    )
                snapshot = self._workspace_builder.fingerprint(
                    repo_root=self.repo_root,
                    expected_revision=revision,
                    candidate_manifest=candidate,
                    candidate_contents=contents,
                )
                approval = build_execution_approval(
                    proposal_id=proposal_id_text,
                    proposal_content_sha256=proposal["content_sha256"],
                    source_fingerprint=source_fingerprint,
                    active_attestation_ids=state["active_attestation_ids"],
                    candidate_id=candidate_id_text,
                    candidate_sha256=candidate_digest,
                    evaluation_id=evaluation_id_text,
                    evaluation_sha256=evaluation_digest,
                    approver_identity=approver_identity,
                    approval_key_id=approval_key.key_id,
                    runner_identity=runner_identity,
                    profile=profile,
                    source_snapshot=snapshot,
                    result_signer_id=result_signer_id,
                    result_signer_key_id=result_key.key_id,
                    issued_at=now,
                )
                event = {
                    "type": "execution_approval_challenge_issued",
                    "at": recorded_at,
                    "approval": copy.deepcopy(approval),
                    "approval_sha256": execution_approval_sha256(approval),
                    "requester_identity": approver_identity,
                    "provenance": receipt,
                    "execution_performed": False,
                    "tests_executed": False,
                    "live_source_writes": False,
                    "authority_granted": False,
                }
                proposal["events"].append(event)
                self._save_ledger(ledger)
            except (ExecutionError, PatchSandboxError) as exc:
                raise SelfIterationError(str(exc)) from exc

        return {
            "approval": approval,
            "approval_sha256": execution_approval_sha256(approval),
            "signing_input_b64": approval_signing_input_b64(approval),
            "signature": {
                "algorithm": SIGNATURE_ALGORITHM,
                "key_id": approval_key.key_id,
                "assurance": "symmetric_mac_server_verifiable",
            },
            "next_step": (
                "The authenticated external approver signs these exact bytes, then submits "
                "execute_candidate before expiry. The challenge is consumed before execution."
            ),
            "authority_granted": False,
        }

    def execute_candidate(
        self,
        *,
        proposal_id: Any,
        challenge_id: Any,
        signature: Any,
    ) -> dict[str, Any]:
        """Consume an approval and run its exact candidate once in Docker."""
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        challenge_id_text = _required_text(challenge_id, "challenge_id", max_length=100)
        signature_text = _required_text(signature, "signature", max_length=64).lower()
        if not re.fullmatch(r"sixc-[0-9a-f]{32}", challenge_id_text):
            raise SelfIterationError("execution challenge_id is malformed")
        if not re.fullmatch(r"[0-9a-f]{64}", signature_text):
            raise SelfIterationError("execution approval signature is malformed")

        with self._lock:
            try:
                ledger = self._load_ledger()
                proposal = self._find_proposal(ledger, proposal_id_text)
                challenge_event = self._execution_challenge_event(
                    proposal, challenge_id_text
                )
                approval = validate_execution_approval(challenge_event["approval"])
                now = self._now_utc()
                issued = parse_utc_timestamp(approval["issued_at"], "issued_at")
                expires = parse_utc_timestamp(
                    approval["challenge_expires_at"], "challenge_expires_at"
                )
                if now < issued - timedelta(seconds=30) or now > expires:
                    raise SelfIterationError(
                        "execution approval is expired or not yet valid"
                    )
                receipt = self._server_provenance(_isoformat(now))
                approver_identity = self._identity_from_provenance(
                    receipt,
                    label="candidate execution request",
                    required=True,
                )
                assert approver_identity is not None
                if approver_identity != approval["approver_identity"]:
                    raise SelfIterationError(
                        "only the authenticated execution approver may consume this challenge"
                    )
                approval_key = self._resolve_verifier_key(
                    approver_identity, approval["approval_key_id"]
                )
                if not verify_execution_approval_signature(
                    approval, signature_text, approval_key
                ):
                    raise SelfIterationError("execution approval signature is invalid")

                state = self._patch_eligible_state(
                    proposal,
                    expected_content_sha256=approval["proposal_content_sha256"],
                    now=now,
                )
                source_fingerprint = self._assert_current_proposal_source(proposal)
                if (
                    source_fingerprint != approval["source_fingerprint"]
                    or sorted(state["active_attestation_ids"])
                    != approval["active_attestation_ids"]
                ):
                    raise SelfIterationError(
                        "proposal source or verification changed after execution approval"
                    )
                candidate, contents = self._patch_sandbox.execution_material(
                    approval["candidate_id"]
                )
                if candidate.get("candidate_sha256") != approval["candidate_sha256"]:
                    raise SelfIterationError("approved candidate digest is stale")
                self._assert_candidate_binding(
                    proposal=proposal, candidate=candidate, state=state
                )
                self._passing_evaluation(
                    proposal=proposal,
                    candidate=candidate,
                    evaluation_id=approval["evaluation_id"],
                    expected_evaluation_sha256=approval["evaluation_sha256"],
                )
                result_signer = approval["result_signer"]
                result_key = self._resolve_verifier_key(
                    {
                        "kind": "service_signer",
                        "id": result_signer["id"],
                        "issuer": None,
                    },
                    result_signer["key_id"],
                )
                if self._isolation_runner.probe() != approval["runner_identity"]:
                    raise SelfIterationError(
                        "Docker runner identity changed after execution approval"
                    )
                if self.repo_root is None:
                    raise SelfIterationError("source repository not found")
                current_snapshot = self._workspace_builder.fingerprint(
                    repo_root=self.repo_root,
                    expected_revision=approval["source_snapshot"]["revision"],
                    candidate_manifest=candidate,
                    candidate_contents=contents,
                )
                if current_snapshot != approval["source_snapshot"]:
                    raise SelfIterationError(
                        "source snapshot changed after execution approval"
                    )

                claimed_at = _isoformat(now)
                claim = self._execution_claim_record(
                    approval=approval,
                    approval_signature=signature_text,
                    approver_identity=approver_identity,
                    claimed_at=claimed_at,
                )
                self._patch_sandbox.claim_execution(
                    approval["candidate_id"], challenge_id_text, claim
                )

                started_at = _isoformat(self._now_utc())
                profile = execution_profile(approval["profile"]["profile_id"])
                with self._workspace_builder.materialize(
                    repo_root=self.repo_root,
                    expected_revision=approval["source_snapshot"]["revision"],
                    candidate_manifest=candidate,
                    candidate_contents=contents,
                    expected_snapshot=approval["source_snapshot"],
                ) as workspace:
                    runner_receipt = self._isolation_runner.run(
                        workspace=workspace,
                        profile=profile,
                        expected_identity=approval["runner_identity"],
                    )
                finished_at = _isoformat(self._now_utc())
                result = build_signed_execution_result(
                    approval=approval,
                    approval_signature=signature_text,
                    approval_key=approval_key,
                    runner_receipt=runner_receipt,
                    started_at=started_at,
                    finished_at=finished_at,
                    signer_key=result_key,
                )
                validate_signed_execution_result(result, self._verifier_key_provider)
                self._patch_sandbox.store_execution_result(
                    approval["candidate_id"], result
                )

                fresh_ledger = self._load_ledger()
                fresh_proposal = self._find_proposal(fresh_ledger, proposal_id_text)
                self._execution_challenge_event(fresh_proposal, challenge_id_text)
                if any(
                    event.get("type") == "isolated_execution_recorded"
                    and event.get("challenge_id") == challenge_id_text
                    for event in fresh_proposal["events"]
                ):
                    raise SelfIterationError(
                        "execution challenge already has a recorded result"
                    )
                result_event = {
                    "type": "isolated_execution_recorded",
                    "at": finished_at,
                    "challenge_id": challenge_id_text,
                    "approval_id": approval["approval_id"],
                    "approval_sha256": execution_approval_sha256(approval),
                    "approval_signature_sha256": hashlib.sha256(
                        canonical_json_bytes(result["approval_signature"])
                    ).hexdigest(),
                    "execution_id": result["execution_id"],
                    "result_sha256": result["result_sha256"],
                    "candidate_id": approval["candidate_id"],
                    "candidate_sha256": approval["candidate_sha256"],
                    "evaluation_id": approval["evaluation_id"],
                    "evaluation_sha256": approval["evaluation_sha256"],
                    "approver_identity": approval["approver_identity"],
                    "result_signer_id": result_signer["id"],
                    "outcome": result["outcome"],
                    "execution_performed": result["execution_performed"],
                    "tests_executed": result["tests_executed"],
                    "cleanup_confirmed": result["cleanup_confirmed"],
                    "eligible_for_external_review": result[
                        "eligible_for_external_review"
                    ],
                    "eligible_for_apply": False,
                    "live_source_writes": False,
                    "authority_granted": False,
                }
                fresh_proposal["events"].append(result_event)
                self._save_ledger(fresh_ledger)
            except (ExecutionError, PatchSandboxError) as exc:
                raise SelfIterationError(str(exc)) from exc

        return {
            "result": result,
            "execution_contract": execution_contract(),
            "next_step": (
                "A passing signed result is eligible for external review only. It does not "
                "apply, commit, merge, deploy, or grant authority."
            ),
            "authority_granted": False,
        }

    def execution_status(
        self,
        *,
        proposal_id: Any,
        candidate_id: Any,
        include_output: Any = False,
    ) -> dict[str, Any]:
        """Reconcile approvals, one-use claims, signed results, and ledger events."""
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        candidate_id_text = _required_text(candidate_id, "candidate_id", max_length=100)
        if not isinstance(include_output, bool):
            raise SelfIterationError("include_output must be a boolean")
        with self._lock:
            ledger = self._load_ledger()
            proposal = self._find_proposal(ledger, proposal_id_text)
            if include_output:
                receipt = self._server_provenance(_isoformat(self._now_utc()))
                self._identity_from_provenance(
                    receipt, label="execution output request", required=True
                )
            try:
                candidate = self._patch_sandbox.load_manifest(candidate_id_text)
                self._assert_candidate_binding(proposal=proposal, candidate=candidate)
                raw_claims = self._patch_sandbox.load_execution_claims(
                    candidate_id_text
                )
                raw_results = self._patch_sandbox.load_execution_results(
                    candidate_id_text
                )
            except PatchSandboxError as exc:
                raise SelfIterationError(str(exc)) from exc

            challenge_events = [
                event
                for event in proposal["events"]
                if event.get("type") == "execution_approval_challenge_issued"
                and event.get("approval", {}).get("candidate_id") == candidate_id_text
            ]
            approvals = {
                event["approval"]["challenge_id"]: event["approval"]
                for event in challenge_events
            }
            claims: dict[str, dict[str, Any]] = {}
            for claim in raw_claims:
                challenge = claim.get("challenge_id")
                if not isinstance(challenge, str):
                    raise SelfIterationError(
                        "execution claim challenge identifier is malformed"
                    )
                approval = approvals.get(challenge)
                if approval is None:
                    raise SelfIterationError(
                        "execution claim has no ledger-recorded approval"
                    )
                claims[challenge] = self._validate_execution_claim(
                    claim, approval=approval
                )
            results: dict[str, dict[str, Any]] = {}
            for raw_result in raw_results:
                try:
                    result = validate_signed_execution_result(
                        raw_result, self._verifier_key_provider
                    )
                except ExecutionError as exc:
                    raise SelfIterationError(
                        "signed execution result artifact is invalid"
                    ) from exc
                challenge = result["challenge_id"]
                approval = approvals.get(challenge)
                if (
                    approval is None
                    or challenge not in claims
                    or result["approval"] != approval
                    or result["approval_signature"]
                    != claims[challenge]["approval_signature"]
                    or result["approval_id"] != approval["approval_id"]
                    or result["approval_sha256"] != execution_approval_sha256(approval)
                    or result["candidate_sha256"] != approval["candidate_sha256"]
                    or result["evaluation_sha256"] != approval["evaluation_sha256"]
                    or result["runner_identity"] != approval["runner_identity"]
                    or result["profile"] != approval["profile"]
                    or result["signature"]["signer_id"]
                    != approval["result_signer"]["id"]
                    or result["signature"]["key_id"]
                    != approval["result_signer"]["key_id"]
                    or challenge in results
                ):
                    raise SelfIterationError(
                        "signed execution result does not match its one-use approval"
                    )
                results[challenge] = result

            result_events = [
                event
                for event in proposal["events"]
                if event.get("type") == "isolated_execution_recorded"
                and event.get("candidate_id") == candidate_id_text
            ]
            recorded_by_challenge = {
                event["challenge_id"]: event for event in result_events
            }
            now = self._now_utc()
            statuses: list[dict[str, Any]] = []
            for challenge_id_text, approval in approvals.items():
                selected_claim = claims.get(challenge_id_text)
                selected_result = results.get(challenge_id_text)
                recorded = recorded_by_challenge.get(challenge_id_text)
                if recorded is not None:
                    expected_recorded = (
                        None
                        if selected_result is None
                        else {
                            "type": "isolated_execution_recorded",
                            "at": selected_result["finished_at"],
                            "challenge_id": challenge_id_text,
                            "approval_id": approval["approval_id"],
                            "approval_sha256": execution_approval_sha256(approval),
                            "approval_signature_sha256": hashlib.sha256(
                                canonical_json_bytes(
                                    selected_result["approval_signature"]
                                )
                            ).hexdigest(),
                            "execution_id": selected_result["execution_id"],
                            "result_sha256": selected_result["result_sha256"],
                            "candidate_id": selected_result["candidate_id"],
                            "candidate_sha256": selected_result["candidate_sha256"],
                            "evaluation_id": selected_result["evaluation_id"],
                            "evaluation_sha256": selected_result["evaluation_sha256"],
                            "approver_identity": approval["approver_identity"],
                            "result_signer_id": selected_result["signature"][
                                "signer_id"
                            ],
                            "outcome": selected_result["outcome"],
                            "execution_performed": selected_result[
                                "execution_performed"
                            ],
                            "tests_executed": selected_result["tests_executed"],
                            "cleanup_confirmed": selected_result["cleanup_confirmed"],
                            "eligible_for_external_review": selected_result[
                                "eligible_for_external_review"
                            ],
                            "eligible_for_apply": False,
                            "live_source_writes": False,
                            "authority_granted": False,
                        }
                    )
                    if recorded != expected_recorded:
                        raise SelfIterationError(
                            "ledger execution event does not match its signed result artifact"
                        )
                if selected_result is not None and recorded is not None:
                    state = "recorded"
                elif selected_result is not None:
                    state = "signed_result_unledgered"
                elif selected_claim is not None:
                    state = "claimed_result_indeterminate"
                elif now > parse_utc_timestamp(
                    approval["challenge_expires_at"], "challenge_expires_at"
                ):
                    state = "expired_unclaimed"
                else:
                    state = "awaiting_signature"
                public_result: dict[str, Any] | None = None
                if selected_result is not None:
                    public_result = copy.deepcopy(selected_result)
                    if not include_output:
                        for stream_name in ("stdout", "stderr"):
                            stream = public_result[stream_name]
                            stream.pop("captured", None)
                        public_result["output_omitted"] = True
                statuses.append(
                    {
                        "challenge_id": challenge_id_text,
                        "approval_id": approval["approval_id"],
                        "approval_sha256": execution_approval_sha256(approval),
                        "issued_at": approval["issued_at"],
                        "challenge_expires_at": approval["challenge_expires_at"],
                        "approver_identity": approval["approver_identity"],
                        "profile_id": approval["profile"]["profile_id"],
                        "state": state,
                        "claim": copy.deepcopy(selected_claim),
                        "result": public_result,
                        "ledger_recorded": recorded is not None,
                        "automatic_retry_allowed": False,
                        "eligible_for_apply": False,
                        "authority_granted": False,
                    }
                )
            return {
                "proposal_id": proposal_id_text,
                "candidate_id": candidate_id_text,
                "candidate_sha256": candidate["candidate_sha256"],
                "executions": statuses,
                "output_included": include_output,
                "execution_contract": execution_contract(),
                "eligible_for_apply": False,
                "authority_granted": False,
            }

    def prepare_application(
        self,
        *,
        proposal_id: Any,
        candidate_id: Any,
        execution_id: Any,
        expected_execution_result_sha256: Any,
    ) -> dict[str, Any]:
        """Issue a short-lived review plan for one dedicated Git branch."""
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        candidate_id_text = _required_text(candidate_id, "candidate_id", max_length=100)
        execution_id_text = _required_text(execution_id, "execution_id", max_length=100)
        execution_digest = _required_text(
            expected_execution_result_sha256,
            "expected_execution_result_sha256",
            max_length=64,
        ).lower()
        if not re.fullmatch(r"six-[0-9a-f]{32}", execution_id_text):
            raise SelfIterationError("execution_id is malformed")
        if not re.fullmatch(r"[0-9a-f]{64}", execution_digest):
            raise SelfIterationError("expected_execution_result_sha256 is malformed")

        with self._lock:
            try:
                ledger = self._load_ledger()
                proposal = self._find_proposal(ledger, proposal_id_text)
                now = self._now_utc()
                state = self._patch_eligible_state(
                    proposal,
                    expected_content_sha256=proposal["content_sha256"],
                    now=now,
                )
                source_fingerprint = self._assert_current_proposal_source(proposal)
                candidate, contents = self._patch_sandbox.execution_material(
                    candidate_id_text
                )
                self._assert_candidate_binding(
                    proposal=proposal, candidate=candidate, state=state
                )
                execution_result = self._passing_execution_result(
                    proposal=proposal,
                    candidate=candidate,
                    execution_id=execution_id_text,
                    expected_result_sha256=execution_digest,
                )
                execution_approval = execution_result["approval"]
                if execution_approval[
                    "source_fingerprint"
                ] != source_fingerprint or execution_approval[
                    "active_attestation_ids"
                ] != sorted(
                    state["active_attestation_ids"]
                ):
                    raise SelfIterationError(
                        "proposal source or verification changed after execution"
                    )

                recorded_at = _isoformat(now)
                receipt = self._server_provenance(recorded_at)
                reviewer_identity = self._identity_from_provenance(
                    receipt,
                    label="application review request",
                    required=True,
                )
                assert reviewer_identity is not None
                verifier_identities = self._active_verifier_identities(proposal, state)
                prior_ids = {
                    identity.get("id")
                    for identity in [
                        proposal.get("proposer_identity"),
                        execution_approval["approver_identity"],
                        *verifier_identities,
                    ]
                    if isinstance(identity, dict)
                }
                prior_ids.add(execution_result["signature"]["signer_id"])
                reviewer_id = reviewer_identity["id"]
                if reviewer_id in prior_ids:
                    raise SelfIterationError(
                        "application reviewer must differ from all prior participants"
                    )
                reviewer_key = self._resolve_verifier_key(reviewer_identity)

                result_signer_id = os.environ.get(APPLICATION_SIGNER_ID_ENV)
                if not isinstance(result_signer_id, str) or not result_signer_id:
                    raise SelfIterationError(
                        f"{APPLICATION_SIGNER_ID_ENV} must name a dedicated result signer"
                    )
                if result_signer_id in {reviewer_id, *prior_ids}:
                    raise SelfIterationError(
                        "application result signer must differ from all review participants"
                    )
                result_signer_identity = {
                    "kind": "service_signer",
                    "id": result_signer_id,
                    "issuer": None,
                }
                result_key = self._resolve_verifier_key(result_signer_identity)
                if self.repo_root is None:
                    raise SelfIterationError("source repository not found")
                snapshot = self._workspace_builder.fingerprint(
                    repo_root=self.repo_root,
                    expected_revision=execution_result["source_snapshot"]["revision"],
                    candidate_manifest=candidate,
                    candidate_contents=contents,
                )
                if snapshot != execution_result["source_snapshot"]:
                    raise SelfIterationError(
                        "source snapshot changed after isolated execution"
                    )
                git_identity = self._application_writer.probe(
                    repo_root=self.repo_root,
                    expected_parent_revision=snapshot["revision"],
                    target_ref=target_ref_for_candidate(candidate_id_text),
                )
                approval = build_application_approval(
                    proposal_id=proposal_id_text,
                    proposal_content_sha256=proposal["content_sha256"],
                    source_fingerprint=source_fingerprint,
                    active_attestation_ids=state["active_attestation_ids"],
                    candidate_id=candidate_id_text,
                    candidate_sha256=candidate["candidate_sha256"],
                    execution_id=execution_id_text,
                    execution_result_sha256=execution_digest,
                    execution_approval_sha256=execution_result["approval_sha256"],
                    execution_finished_at=execution_result["finished_at"],
                    source_snapshot=snapshot,
                    reviewer_identity=reviewer_identity,
                    reviewer_key_id=reviewer_key.key_id,
                    git_identity=git_identity,
                    result_signer_id=result_signer_id,
                    result_signer_key_id=result_key.key_id,
                    issued_at=now,
                )
                event = {
                    "type": "application_review_challenge_issued",
                    "at": recorded_at,
                    "approval": copy.deepcopy(approval),
                    "approval_sha256": application_approval_sha256(approval),
                    "requester_identity": reviewer_identity,
                    "provenance": receipt,
                    "branch_created": False,
                    "live_source_writes": False,
                    "pushed": False,
                    "merged": False,
                    "deployed": False,
                    "authority_granted": False,
                }
                proposal["events"].append(event)
                self._save_ledger(ledger)
            except (ApplicationError, PatchSandboxError) as exc:
                raise SelfIterationError(str(exc)) from exc

        return {
            "approval": approval,
            "approval_sha256": application_approval_sha256(approval),
            "signing_input_b64": application_signing_input_b64(approval),
            "signature": {
                "algorithm": SIGNATURE_ALGORITHM,
                "key_id": reviewer_key.key_id,
                "assurance": "symmetric_mac_server_verifiable",
            },
            "next_step": (
                "The authenticated application reviewer signs these exact bytes, then "
                "submits apply_candidate before expiry. The one-use claim is consumed "
                "before Git creates the dedicated branch."
            ),
            "authority_granted": False,
        }

    def apply_candidate(
        self,
        *,
        proposal_id: Any,
        challenge_id: Any,
        signature: Any,
    ) -> dict[str, Any]:
        """Consume one review and create its exact dedicated Git branch once."""
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        challenge_id_text = _required_text(challenge_id, "challenge_id", max_length=100)
        signature_text = _required_text(signature, "signature", max_length=64).lower()
        if not re.fullmatch(r"siac-[0-9a-f]{32}", challenge_id_text):
            raise SelfIterationError("application challenge_id is malformed")
        if not re.fullmatch(r"[0-9a-f]{64}", signature_text):
            raise SelfIterationError("application approval signature is malformed")

        with self._lock:
            try:
                ledger = self._load_ledger()
                proposal = self._find_proposal(ledger, proposal_id_text)
                challenge_event = self._application_challenge_event(
                    proposal, challenge_id_text
                )
                approval = validate_application_approval(challenge_event["approval"])
                now = self._now_utc()
                issued = parse_utc_timestamp(approval["issued_at"], "issued_at")
                expires = parse_utc_timestamp(
                    approval["challenge_expires_at"], "challenge_expires_at"
                )
                if now < issued - timedelta(seconds=30) or now > expires:
                    raise SelfIterationError(
                        "application approval is expired or not yet valid"
                    )
                receipt = self._server_provenance(_isoformat(now))
                reviewer_identity = self._identity_from_provenance(
                    receipt,
                    label="candidate application request",
                    required=True,
                )
                assert reviewer_identity is not None
                if reviewer_identity != approval["reviewer_identity"]:
                    raise SelfIterationError(
                        "only the authenticated application reviewer may consume this challenge"
                    )
                approval_key = self._resolve_verifier_key(
                    reviewer_identity, approval["reviewer_key_id"]
                )
                if not verify_application_approval_signature(
                    approval, signature_text, approval_key
                ):
                    raise SelfIterationError(
                        "application approval signature is invalid"
                    )

                state = self._patch_eligible_state(
                    proposal,
                    expected_content_sha256=approval["proposal_content_sha256"],
                    now=now,
                )
                source_fingerprint = self._assert_current_proposal_source(proposal)
                if (
                    source_fingerprint != approval["source_fingerprint"]
                    or sorted(state["active_attestation_ids"])
                    != approval["active_attestation_ids"]
                ):
                    raise SelfIterationError(
                        "proposal source or verification changed after application review"
                    )
                candidate, contents = self._patch_sandbox.execution_material(
                    approval["candidate_id"]
                )
                if candidate.get("candidate_sha256") != approval["candidate_sha256"]:
                    raise SelfIterationError("reviewed candidate digest is stale")
                self._assert_candidate_binding(
                    proposal=proposal, candidate=candidate, state=state
                )
                execution_result = self._passing_execution_result(
                    proposal=proposal,
                    candidate=candidate,
                    execution_id=approval["execution_id"],
                    expected_result_sha256=approval["execution_result_sha256"],
                )
                if (
                    execution_result["approval_sha256"]
                    != approval["execution_approval_sha256"]
                    or execution_result["finished_at"]
                    != approval["execution_finished_at"]
                    or execution_result["source_snapshot"]
                    != approval["source_snapshot"]
                ):
                    raise SelfIterationError(
                        "reviewed execution binding changed before application"
                    )
                result_signer = approval["result_signer"]
                result_key = self._resolve_verifier_key(
                    {
                        "kind": "service_signer",
                        "id": result_signer["id"],
                        "issuer": None,
                    },
                    result_signer["key_id"],
                )
                if self.repo_root is None:
                    raise SelfIterationError("source repository not found")
                current_snapshot = self._workspace_builder.fingerprint(
                    repo_root=self.repo_root,
                    expected_revision=approval["source_snapshot"]["revision"],
                    candidate_manifest=candidate,
                    candidate_contents=contents,
                )
                if current_snapshot != approval["source_snapshot"]:
                    raise SelfIterationError(
                        "source snapshot changed after application review"
                    )
                if (
                    self._application_writer.probe(
                        repo_root=self.repo_root,
                        expected_parent_revision=approval["expected_parent_revision"],
                        target_ref=approval["target_ref"],
                    )
                    != approval["git_identity"]
                ):
                    raise SelfIterationError(
                        "Git application backend changed after review"
                    )

                claimed_at = _isoformat(now)
                claim = self._application_claim_record(
                    approval=approval,
                    approval_signature=signature_text,
                    reviewer_identity=reviewer_identity,
                    claimed_at=claimed_at,
                )
                self._patch_sandbox.claim_application(
                    approval["candidate_id"], challenge_id_text, claim
                )

                applied_at = _isoformat(self._now_utc())
                writer_receipt = self._application_writer.apply(
                    repo_root=self.repo_root,
                    expected_identity=approval["git_identity"],
                    approval=approval,
                    candidate_manifest=candidate,
                    candidate_contents=contents,
                    applied_at=applied_at,
                )
                result = build_signed_application_result(
                    approval=approval,
                    approval_signature=signature_text,
                    approval_key=approval_key,
                    writer_receipt=writer_receipt,
                    applied_at=applied_at,
                    signer_key=result_key,
                )
                validate_signed_application_result(result, self._verifier_key_provider)
                self._patch_sandbox.store_application_result(
                    approval["candidate_id"], result
                )

                fresh_ledger = self._load_ledger()
                fresh_proposal = self._find_proposal(fresh_ledger, proposal_id_text)
                self._application_challenge_event(fresh_proposal, challenge_id_text)
                if any(
                    event.get("type") == "reviewed_application_recorded"
                    and event.get("challenge_id") == challenge_id_text
                    for event in fresh_proposal["events"]
                ):
                    raise SelfIterationError(
                        "application challenge already has a recorded result"
                    )
                fresh_proposal["events"].append(self._application_result_event(result))
                self._save_ledger(fresh_ledger)
            except (ApplicationError, PatchSandboxError) as exc:
                raise SelfIterationError(str(exc)) from exc

        return {
            "result": result,
            "application_contract": application_contract(),
            "next_step": (
                "The signed result names a dedicated local branch eligible for canary "
                "review. It is not pushed, merged, deployed, or live."
            ),
            "authority_granted": False,
        }

    def application_status(
        self,
        *,
        proposal_id: Any,
        candidate_id: Any,
    ) -> dict[str, Any]:
        """Reconcile application reviews, claims, signed results, and Git refs."""
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        candidate_id_text = _required_text(candidate_id, "candidate_id", max_length=100)
        with self._lock:
            ledger = self._load_ledger()
            proposal = self._find_proposal(ledger, proposal_id_text)
            try:
                candidate = self._patch_sandbox.load_manifest(candidate_id_text)
                self._assert_candidate_binding(proposal=proposal, candidate=candidate)
                raw_claims = self._patch_sandbox.load_application_claims(
                    candidate_id_text
                )
                raw_results = self._patch_sandbox.load_application_results(
                    candidate_id_text
                )
            except PatchSandboxError as exc:
                raise SelfIterationError(str(exc)) from exc
            challenge_events = [
                event
                for event in proposal["events"]
                if event.get("type") == "application_review_challenge_issued"
                and event.get("approval", {}).get("candidate_id") == candidate_id_text
            ]
            approvals = {
                event["approval"]["challenge_id"]: event["approval"]
                for event in challenge_events
            }
            claims: dict[str, dict[str, Any]] = {}
            for raw_claim in raw_claims:
                challenge_id_value = raw_claim.get("challenge_id")
                if not isinstance(challenge_id_value, str):
                    raise SelfIterationError(
                        "application claim challenge identifier is malformed"
                    )
                approval = approvals.get(challenge_id_value)
                if approval is None or challenge_id_value in claims:
                    raise SelfIterationError(
                        "application claim has no unique ledger-recorded approval"
                    )
                claims[challenge_id_value] = self._validate_application_claim(
                    raw_claim, approval=approval
                )
            results: dict[str, dict[str, Any]] = {}
            for raw_result in raw_results:
                try:
                    result = validate_signed_application_result(
                        raw_result, self._verifier_key_provider
                    )
                except ApplicationError as exc:
                    raise SelfIterationError(
                        "signed application result artifact is invalid"
                    ) from exc
                challenge_id_value = result["challenge_id"]
                approval = approvals.get(challenge_id_value)
                claim = claims.get(challenge_id_value)
                if (
                    approval is None
                    or claim is None
                    or challenge_id_value in results
                    or result["approval"] != approval
                    or result["approval_signature"] != claim["approval_signature"]
                    or result["application_approval_sha256"]
                    != application_approval_sha256(approval)
                ):
                    raise SelfIterationError(
                        "signed application result does not match its one-use approval"
                    )
                results[challenge_id_value] = result

            recorded_events = [
                event
                for event in proposal["events"]
                if event.get("type") == "reviewed_application_recorded"
                and event.get("candidate_id") == candidate_id_text
            ]
            recorded_by_challenge = {
                event["challenge_id"]: event for event in recorded_events
            }
            now = self._now_utc()
            statuses: list[dict[str, Any]] = []
            if self.repo_root is None and results:
                raise SelfIterationError("source repository not found")
            for challenge_id_value, approval in approvals.items():
                selected_claim = claims.get(challenge_id_value)
                selected_result = results.get(challenge_id_value)
                recorded = recorded_by_challenge.get(challenge_id_value)
                if recorded is not None and (
                    selected_result is None
                    or recorded != self._application_result_event(selected_result)
                ):
                    raise SelfIterationError(
                        "ledger application event does not match its signed result artifact"
                    )
                ref_intact = bool(
                    selected_result is not None
                    and self.repo_root is not None
                    and self._application_writer.verify_result(
                        repo_root=self.repo_root, result=selected_result
                    )
                )
                if selected_result is not None and not ref_intact:
                    state = "ref_integrity_failed"
                elif selected_result is not None and recorded is not None:
                    state = "recorded"
                elif selected_result is not None:
                    state = "signed_result_unledgered"
                elif selected_claim is not None:
                    state = "claimed_result_indeterminate"
                elif now > parse_utc_timestamp(
                    approval["challenge_expires_at"], "challenge_expires_at"
                ):
                    state = "expired_unclaimed"
                else:
                    state = "awaiting_signature"
                statuses.append(
                    {
                        "challenge_id": challenge_id_value,
                        "application_id": approval["application_id"],
                        "approval_sha256": application_approval_sha256(approval),
                        "issued_at": approval["issued_at"],
                        "challenge_expires_at": approval["challenge_expires_at"],
                        "reviewer_identity": approval["reviewer_identity"],
                        "target_ref": approval["target_ref"],
                        "state": state,
                        "claim": copy.deepcopy(selected_claim),
                        "result": copy.deepcopy(selected_result),
                        "ledger_recorded": recorded is not None,
                        "ref_integrity_verified": ref_intact,
                        "automatic_retry_allowed": False,
                        "eligible_for_canary_review": bool(
                            state == "recorded" and ref_intact
                        ),
                        "eligible_for_live_activation": False,
                        "authority_granted": False,
                    }
                )
            return {
                "proposal_id": proposal_id_text,
                "candidate_id": candidate_id_text,
                "candidate_sha256": candidate["candidate_sha256"],
                "applications": statuses,
                "application_contract": application_contract(),
                "eligible_for_live_activation": False,
                "authority_granted": False,
            }

    def prepare_canary(
        self,
        *,
        proposal_id: Any,
        candidate_id: Any,
        application_result_id: Any,
        expected_application_result_sha256: Any,
    ) -> dict[str, Any]:
        """Issue a signed plan for one externally supervised transient canary."""
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        candidate_id_text = _required_text(candidate_id, "candidate_id", max_length=100)
        application_result_id_text = _required_text(
            application_result_id, "application_result_id", max_length=100
        )
        application_digest = _required_text(
            expected_application_result_sha256,
            "expected_application_result_sha256",
            max_length=64,
        ).lower()
        if not re.fullmatch(r"siar-[0-9a-f]{32}", application_result_id_text):
            raise SelfIterationError("application_result_id is malformed")
        if not re.fullmatch(r"[0-9a-f]{64}", application_digest):
            raise SelfIterationError("expected_application_result_sha256 is malformed")

        with self._lock:
            try:
                ledger = self._load_ledger()
                proposal = self._find_proposal(ledger, proposal_id_text)
                now = self._now_utc()
                state = self._patch_eligible_state(
                    proposal,
                    expected_content_sha256=proposal["content_sha256"],
                    now=now,
                )
                source_fingerprint = self._assert_current_proposal_source(proposal)
                candidate = self._patch_sandbox.load_manifest(candidate_id_text)
                self._assert_candidate_binding(
                    proposal=proposal, candidate=candidate, state=state
                )
                application_result = self._passing_application_result(
                    proposal=proposal,
                    candidate=candidate,
                    application_result_id=application_result_id_text,
                    expected_result_sha256=application_digest,
                )
                application_approval = application_result["approval"]
                if application_approval[
                    "source_fingerprint"
                ] != source_fingerprint or application_approval[
                    "active_attestation_ids"
                ] != sorted(
                    state["active_attestation_ids"]
                ):
                    raise SelfIterationError(
                        "proposal source or verification changed after application"
                    )

                recorded_at = _isoformat(now)
                receipt = self._server_provenance(recorded_at)
                reviewer_identity = self._identity_from_provenance(
                    receipt,
                    label="canary review request",
                    required=True,
                )
                assert reviewer_identity is not None
                verifier_identities = self._active_verifier_identities(proposal, state)
                execution_events = [
                    event
                    for event in proposal["events"]
                    if event.get("type") == "isolated_execution_recorded"
                    and event.get("execution_id") == application_result["execution_id"]
                ]
                if len(execution_events) != 1:
                    raise SelfIterationError(
                        "canary review requires one recorded execution chain"
                    )
                execution_event = execution_events[0]
                prior_ids = {
                    identity.get("id")
                    for identity in [
                        proposal.get("proposer_identity"),
                        execution_event.get("approver_identity"),
                        application_approval["reviewer_identity"],
                        *verifier_identities,
                    ]
                    if isinstance(identity, dict)
                }
                prior_ids.update(
                    {
                        execution_event.get("result_signer_id"),
                        application_result["signature"]["signer_id"],
                    }
                )
                reviewer_id = reviewer_identity["id"]
                if reviewer_id in prior_ids:
                    raise SelfIterationError(
                        "canary reviewer must differ from all prior participants"
                    )
                reviewer_key = self._resolve_verifier_key(reviewer_identity)

                configured_supervisor_id = os.environ.get(CANARY_SIGNER_ID_ENV)
                if (
                    not isinstance(configured_supervisor_id, str)
                    or not configured_supervisor_id
                ):
                    raise SelfIterationError(
                        f"{CANARY_SIGNER_ID_ENV} must name the dedicated supervisor signer"
                    )
                if configured_supervisor_id in {reviewer_id, *prior_ids}:
                    raise SelfIterationError(
                        "canary supervisor signer must differ from all participants"
                    )
                supervisor_identity = validate_supervisor_identity(
                    self._canary_supervisor.probe()
                )
                result_signer = supervisor_identity.get("result_signer")
                if (
                    supervisor_identity.get("supervisor_id") != configured_supervisor_id
                    or not isinstance(result_signer, dict)
                    or result_signer.get("id") != configured_supervisor_id
                ):
                    raise SelfIterationError(
                        "canary supervisor identity does not match configuration"
                    )
                supervisor_key = self._resolve_verifier_key(
                    {
                        "kind": "service_signer",
                        "id": configured_supervisor_id,
                        "issuer": None,
                    },
                    result_signer.get("key_id"),
                )
                approval = build_canary_approval(
                    application_result=application_result,
                    reviewer_identity=reviewer_identity,
                    reviewer_key_id=reviewer_key.key_id,
                    supervisor_identity=supervisor_identity,
                    issued_at=now,
                )
                if (
                    approval["supervisor_identity"]["result_signer"]["key_id"]
                    != supervisor_key.key_id
                ):
                    raise SelfIterationError(
                        "canary supervisor signing key binding is malformed"
                    )
                event = {
                    "type": "canary_review_challenge_issued",
                    "at": recorded_at,
                    "approval": copy.deepcopy(approval),
                    "approval_sha256": canary_approval_sha256(approval),
                    "requester_identity": reviewer_identity,
                    "provenance": receipt,
                    "activation_performed": False,
                    "baseline_restore_attempted": False,
                    "persistent_activation_retained": False,
                    "authority_granted": False,
                }
                proposal["events"].append(event)
                self._save_ledger(ledger)
            except (CanaryError, PatchSandboxError) as exc:
                raise SelfIterationError(str(exc)) from exc

        return {
            "approval": approval,
            "approval_sha256": canary_approval_sha256(approval),
            "signing_input_b64": canary_signing_input_b64(approval),
            "signature": {
                "algorithm": SIGNATURE_ALGORITHM,
                "key_id": reviewer_key.key_id,
                "assurance": "symmetric_mac_server_verifiable",
            },
            "next_step": (
                "The authenticated canary reviewer signs these exact bytes, then "
                "submits run_canary before expiry. The claim is consumed before the "
                "external supervisor may activate the transient candidate."
            ),
            "authority_granted": False,
        }

    def run_canary(
        self,
        *,
        proposal_id: Any,
        challenge_id: Any,
        signature: Any,
    ) -> dict[str, Any]:
        """Consume one review and request its fixed transient canary exactly once."""
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        challenge_id_text = _required_text(challenge_id, "challenge_id", max_length=100)
        signature_text = _required_text(signature, "signature", max_length=64).lower()
        if not re.fullmatch(r"sicc-[0-9a-f]{32}", challenge_id_text):
            raise SelfIterationError("canary challenge_id is malformed")
        if not re.fullmatch(r"[0-9a-f]{64}", signature_text):
            raise SelfIterationError("canary approval signature is malformed")

        with self._lock:
            try:
                ledger = self._load_ledger()
                proposal = self._find_proposal(ledger, proposal_id_text)
                challenge_event = self._canary_challenge_event(
                    proposal, challenge_id_text
                )
                approval = validate_canary_approval(challenge_event["approval"])
                now = self._now_utc()
                issued = parse_utc_timestamp(approval["issued_at"], "issued_at")
                expires = parse_utc_timestamp(
                    approval["challenge_expires_at"], "challenge_expires_at"
                )
                if now < issued - timedelta(seconds=30) or now > expires:
                    raise SelfIterationError(
                        "canary approval is expired or not yet valid"
                    )
                receipt = self._server_provenance(_isoformat(now))
                reviewer_identity = self._identity_from_provenance(
                    receipt,
                    label="transient canary request",
                    required=True,
                )
                assert reviewer_identity is not None
                if reviewer_identity != approval["reviewer_identity"]:
                    raise SelfIterationError(
                        "only the authenticated canary reviewer may consume this challenge"
                    )
                reviewer_key = self._resolve_verifier_key(
                    reviewer_identity, approval["reviewer_key_id"]
                )
                if not verify_canary_approval_signature(
                    approval, signature_text, reviewer_key
                ):
                    raise SelfIterationError("canary approval signature is invalid")

                state = self._patch_eligible_state(
                    proposal,
                    expected_content_sha256=approval["proposal_content_sha256"],
                    now=now,
                )
                self._assert_current_proposal_source(proposal)
                candidate = self._patch_sandbox.load_manifest(approval["candidate_id"])
                if candidate.get("candidate_sha256") != approval["candidate_sha256"]:
                    raise SelfIterationError("canary candidate digest is stale")
                self._assert_candidate_binding(
                    proposal=proposal, candidate=candidate, state=state
                )
                application_result = self._passing_application_result(
                    proposal=proposal,
                    candidate=candidate,
                    application_result_id=approval["application_result_id"],
                    expected_result_sha256=approval["application_result_sha256"],
                )
                if (
                    application_result["application_id"] != approval["application_id"]
                    or application_result["application_approval_sha256"]
                    != approval["application_approval_sha256"]
                    or application_result["target_ref"] != approval["target_ref"]
                    or application_result["parent_revision"]
                    != approval["baseline_revision"]
                    or application_result["commit_oid"]
                    != approval["candidate_commit_oid"]
                    or application_result["tree_oid"] != approval["candidate_tree_oid"]
                ):
                    raise SelfIterationError(
                        "reviewed application changed before canary execution"
                    )
                if (
                    validate_supervisor_identity(self._canary_supervisor.probe())
                    != approval["supervisor_identity"]
                ):
                    raise SelfIterationError(
                        "canary supervisor identity changed after review"
                    )
                supervisor_signer = approval["supervisor_identity"]["result_signer"]
                self._resolve_verifier_key(
                    {
                        "kind": "service_signer",
                        "id": supervisor_signer["id"],
                        "issuer": None,
                    },
                    supervisor_signer["key_id"],
                )

                requested_at = _isoformat(now)
                claim = self._canary_claim_record(
                    approval=approval,
                    approval_signature=signature_text,
                    reviewer_identity=reviewer_identity,
                    claimed_at=requested_at,
                )
                self._patch_sandbox.claim_canary(
                    approval["candidate_id"], challenge_id_text, claim
                )

                result = self._canary_supervisor.evaluate(
                    approval=approval,
                    approval_signature=signature_text,
                    requested_at=requested_at,
                )
                result = validate_signed_canary_result(
                    result, self._verifier_key_provider
                )
                expected_request = build_canary_request(
                    approval=approval,
                    approval_signature=signature_text,
                    requested_at=requested_at,
                )
                if (
                    result["approval"] != approval
                    or result["approval_signature"] != claim["approval_signature"]
                    or result["request_sha256"] != expected_request["request_sha256"]
                    or result["supervisor_identity"] != approval["supervisor_identity"]
                ):
                    raise SelfIterationError(
                        "signed canary result does not match its one-use request"
                    )
                self._patch_sandbox.store_canary_result(
                    approval["candidate_id"], result
                )

                fresh_ledger = self._load_ledger()
                fresh_proposal = self._find_proposal(fresh_ledger, proposal_id_text)
                self._canary_challenge_event(fresh_proposal, challenge_id_text)
                if any(
                    event.get("type") == "transient_canary_recorded"
                    and event.get("challenge_id") == challenge_id_text
                    for event in fresh_proposal["events"]
                ):
                    raise SelfIterationError(
                        "canary challenge already has a recorded result"
                    )
                fresh_proposal["events"].append(self._canary_result_event(result))
                self._save_ledger(fresh_ledger)
            except (CanaryError, PatchSandboxError) as exc:
                raise SelfIterationError(str(exc)) from exc

        return {
            "result": result,
            "canary_contract": canary_contract(),
            "next_step": (
                "The candidate is no longer live. A passing restored canary may be "
                "reviewed for merge; no result grants persistent activation authority."
            ),
            "authority_granted": False,
        }

    def canary_status(
        self,
        *,
        proposal_id: Any,
        candidate_id: Any,
    ) -> dict[str, Any]:
        """Reconcile canary reviews, claims, signed results, and ledger events."""
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        candidate_id_text = _required_text(candidate_id, "candidate_id", max_length=100)
        with self._lock:
            ledger = self._load_ledger()
            proposal = self._find_proposal(ledger, proposal_id_text)
            try:
                candidate = self._patch_sandbox.load_manifest(candidate_id_text)
                self._assert_candidate_binding(proposal=proposal, candidate=candidate)
                raw_claims = self._patch_sandbox.load_canary_claims(candidate_id_text)
                raw_results = self._patch_sandbox.load_canary_results(candidate_id_text)
            except PatchSandboxError as exc:
                raise SelfIterationError(str(exc)) from exc
            challenge_events = [
                event
                for event in proposal["events"]
                if event.get("type") == "canary_review_challenge_issued"
                and event.get("approval", {}).get("candidate_id") == candidate_id_text
            ]
            approvals = {
                event["approval"]["challenge_id"]: event["approval"]
                for event in challenge_events
            }
            claims: dict[str, dict[str, Any]] = {}
            for raw_claim in raw_claims:
                challenge_id_value = raw_claim.get("challenge_id")
                if not isinstance(challenge_id_value, str):
                    raise SelfIterationError(
                        "canary claim challenge identifier is malformed"
                    )
                approval = approvals.get(challenge_id_value)
                if approval is None or challenge_id_value in claims:
                    raise SelfIterationError(
                        "canary claim has no unique ledger-recorded approval"
                    )
                claims[challenge_id_value] = self._validate_canary_claim(
                    raw_claim, approval=approval
                )
            results: dict[str, dict[str, Any]] = {}
            for raw_result in raw_results:
                try:
                    result = validate_signed_canary_result(
                        raw_result, self._verifier_key_provider
                    )
                except CanaryError as exc:
                    raise SelfIterationError(
                        "signed canary result artifact is invalid"
                    ) from exc
                challenge_id_value = result["challenge_id"]
                approval = approvals.get(challenge_id_value)
                claim = claims.get(challenge_id_value)
                if approval is None or claim is None or challenge_id_value in results:
                    raise SelfIterationError(
                        "signed canary result has no unique one-use approval"
                    )
                expected_request = build_canary_request(
                    approval=approval,
                    approval_signature=claim["approval_signature"]["value"],
                    requested_at=claim["claimed_at"],
                )
                if (
                    result["approval"] != approval
                    or result["approval_signature"] != claim["approval_signature"]
                    or result["request_sha256"] != expected_request["request_sha256"]
                ):
                    raise SelfIterationError(
                        "signed canary result does not match its one-use approval"
                    )
                results[challenge_id_value] = result

            recorded_events = [
                event
                for event in proposal["events"]
                if event.get("type") == "transient_canary_recorded"
                and event.get("candidate_id") == candidate_id_text
            ]
            recorded_by_challenge = {
                event["challenge_id"]: event for event in recorded_events
            }
            now = self._now_utc()
            statuses: list[dict[str, Any]] = []
            for challenge_id_value, approval in approvals.items():
                selected_claim = claims.get(challenge_id_value)
                selected_result = results.get(challenge_id_value)
                recorded = recorded_by_challenge.get(challenge_id_value)
                if recorded is not None and (
                    selected_result is None
                    or recorded != self._canary_result_event(selected_result)
                ):
                    raise SelfIterationError(
                        "ledger canary event does not match its signed result artifact"
                    )
                application_ref_intact = False
                try:
                    application_result = self._passing_application_result(
                        proposal=proposal,
                        candidate=candidate,
                        application_result_id=approval["application_result_id"],
                        expected_result_sha256=approval["application_result_sha256"],
                    )
                except SelfIterationError:
                    if selected_result is not None:
                        raise
                else:
                    application_ref_intact = bool(
                        application_result["commit_oid"]
                        == approval["candidate_commit_oid"]
                    )
                if (
                    selected_result is not None
                    and selected_result["baseline_restored"] is not True
                ):
                    state = "recorded_recovery_required"
                elif selected_result is not None and recorded is not None:
                    state = "recorded"
                elif selected_result is not None:
                    state = "signed_result_unledgered"
                elif selected_claim is not None:
                    state = "claimed_result_indeterminate"
                elif now > parse_utc_timestamp(
                    approval["challenge_expires_at"], "challenge_expires_at"
                ):
                    state = "expired_unclaimed"
                else:
                    state = "awaiting_signature"
                statuses.append(
                    {
                        "challenge_id": challenge_id_value,
                        "canary_id": approval["canary_id"],
                        "approval_sha256": canary_approval_sha256(approval),
                        "issued_at": approval["issued_at"],
                        "challenge_expires_at": approval["challenge_expires_at"],
                        "reviewer_identity": approval["reviewer_identity"],
                        "supervisor_identity": approval["supervisor_identity"],
                        "state": state,
                        "claim": copy.deepcopy(selected_claim),
                        "result": copy.deepcopy(selected_result),
                        "ledger_recorded": recorded is not None,
                        "application_ref_intact": application_ref_intact,
                        "automatic_retry_allowed": False,
                        "persistent_activation_retained": False,
                        "eligible_for_merge_review": bool(
                            selected_result is not None
                            and recorded is not None
                            and selected_result["eligible_for_merge_review"] is True
                            and application_ref_intact
                        ),
                        "eligible_for_live_activation": False,
                        "authority_granted": False,
                    }
                )
            return {
                "proposal_id": proposal_id_text,
                "candidate_id": candidate_id_text,
                "candidate_sha256": candidate["candidate_sha256"],
                "canaries": statuses,
                "canary_contract": canary_contract(),
                "persistent_activation_retained": False,
                "eligible_for_live_activation": False,
                "authority_granted": False,
            }

    def record_outcome(
        self,
        *,
        proposal_id: Any,
        decision: Any,
        observed_outcome: Any,
        evidence: Any,
        implementation_ref: Any,
        claimed_measurement_source: Any = "self_observation",
    ) -> dict[str, Any]:
        proposal_id_text = _required_text(proposal_id, "proposal_id", max_length=100)
        if not isinstance(decision, str) or decision not in {
            "keep",
            "revert",
            "inconclusive",
        }:
            raise SelfIterationError(
                "decision must be one of: keep, revert, inconclusive"
            )
        observed_text = _required_text(observed_outcome, "observed_outcome")
        evidence_items = _string_list(evidence, "evidence")
        implementation_text = _required_text(
            implementation_ref, "implementation_ref", max_length=500
        )
        allowed_measurement_sources = {
            "automated_test",
            "caretaker",
            "governance",
            "self_observation",
        }
        if (
            not isinstance(claimed_measurement_source, str)
            or claimed_measurement_source not in allowed_measurement_sources
        ):
            raise SelfIterationError(
                "claimed_measurement_source must be one of: "
                + ", ".join(sorted(allowed_measurement_sources))
            )
        status_for_decision = {
            "keep": "retained",
            "revert": "reverted",
            "inconclusive": "measurement_inconclusive",
        }

        with self._lock:
            ledger = self._load_ledger()
            proposal = self._find_proposal(ledger, proposal_id_text)
            recorded_at = _isoformat(self._clock())
            event = {
                "type": "outcome_recorded",
                "at": recorded_at,
                "decision": decision,
                "observed_outcome": observed_text,
                "evidence": evidence_items,
                "evidence_epistemic_status": "caller_asserted",
                "implementation_ref": implementation_text,
                "measurement_source_claim": _claim_envelope(
                    claimed_measurement_source,
                    field="claimed_measurement_source",
                ),
                "provenance": self._server_provenance(recorded_at),
                "trust_policy": _zero_weight_trust_policy(),
                "code_fingerprint": self._code_fingerprint(),
            }
            proposal.setdefault("events", []).append(event)
            proposal["status"] = status_for_decision[decision]
            self._save_ledger(ledger)
        return self._public_proposal(proposal)


_system: SelfIterationSystem | None = None
_system_lock = threading.Lock()


def get_self_iteration_system() -> SelfIterationSystem:
    """Return the process-wide self-iteration system."""
    global _system
    if _system is None:
        with _system_lock:
            if _system is None:
                _system = SelfIterationSystem()
    return _system


__all__ = [
    "SelfIterationError",
    "SelfIterationSystem",
    "get_self_iteration_system",
]
