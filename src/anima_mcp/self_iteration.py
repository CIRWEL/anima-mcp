"""Bounded source awareness and self-iteration proposals for Lumen.

This module deliberately separates *understanding* and *requesting* a code
change from implementing one.  The running creature may inspect a structural
map of its source, persist an evidence-backed proposal, and record the measured
outcome of an externally implemented change.  It never edits source, executes
proposal text, invokes Git mutation commands, or deploys code.

The boundary is architectural rather than prompt-based: this module exposes no
method that writes inside the repository.  Its only write is an atomic ledger
under ``~/.anima``.
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
    validate_evidence,
    validate_recorded_attestation,
    verification_contract,
    verifier_key_from_env,
    verify_attestation_signature,
)

SCHEMA_VERSION = 3
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

# Initial autonomous eligibility is intentionally narrow.  This module still
# only proposes changes; a future isolated runner may use this field without
# silently expanding its own authority.
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
        clock: Callable[[], datetime] = _utc_now,
        provenance_provider: Callable[
            [str], dict[str, Any]
        ] = _collect_server_provenance,
        verifier_key_provider: VerifierKeyProvider = verifier_key_from_env,
    ) -> None:
        self.repo_root = repo_root.resolve() if repo_root else _discover_repo_root()
        self.ledger_path = ledger_path or Path.home() / ".anima" / "self_iteration.json"
        self._clock = clock
        self._provenance_provider = provenance_provider
        self._verifier_key_provider = verifier_key_provider
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
            "autonomy_level": "proposal_only",
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
                "accept_caller_supplied_provenance": False,
                "weight_unverified_ledger_claims": False,
                "verification_grants_implementation_authority": False,
                "write_source": False,
                "execute_proposal_text": False,
                "commit_or_push": False,
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
                    "A separate caretaker or isolated runner must implement, test, "
                    "review, and deploy every proposal."
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
                    "to_schema": SCHEMA_VERSION,
                    "verification_status": "unverified",
                    "authority_granted": False,
                }
            )
        ledger["schema_version"] = SCHEMA_VERSION
        ledger["verification_contract"] = verification_contract()
        ledger["migrations"].append(
            {
                "type": "schema_migration",
                "at": migrated_at,
                "from_schema": PROVENANCE_SCHEMA_VERSION,
                "to_schema": SCHEMA_VERSION,
                "classification": "verification_requires_signed_attestation",
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
            migrated = True
        elif version == SCHEMA_VERSION:
            self._validate_v3(data)
        else:
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
            (item["risk_floor"] for item in boundaries), key=_RISK_ORDER.get
        )
        effective_risk = max((str(risk), risk_floor), key=_RISK_ORDER.get)
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
