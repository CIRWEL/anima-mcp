"""Quarantined patch artifacts and non-executing static evaluation.

This module is intentionally not a code-execution sandbox.  It can materialize
whole-file replacement candidates beneath a dedicated directory outside the
source repository, validate their integrity, and parse them with deterministic
static checks.  It never applies a patch, imports candidate code, starts a
process, runs tests, invokes Git, or grants implementation authority.
"""

from __future__ import annotations

import ast
import copy
import difflib
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .atomic_write import atomic_json_write
from .self_iteration_verification import canonical_json_bytes

CANDIDATE_SCHEMA = "anima.self_iteration.patch_candidate.v1"
EVALUATION_SCHEMA = "anima.self_iteration.patch_evaluation.v1"
SANDBOX_CONTRACT_SCHEMA = "anima.self_iteration.sandbox_contract.v1"
STATIC_EVALUATOR_ID = "anima-mcp.static-patch-evaluator.v1"

MAX_CANDIDATE_FILES = 3
MAX_FILE_BYTES = 128 * 1024
MAX_TOTAL_BYTES = 256 * 1024
MAX_PATCH_BYTES = 512 * 1024
MAX_CHANGED_LINES = 800
MAX_MANIFEST_BYTES = 256 * 1024
MAX_EVALUATION_BYTES = 256 * 1024

SUPPORTED_SUFFIXES = frozenset({".json", ".md", ".py", ".yaml", ".yml"})

_CANDIDATE_ID_RE = re.compile(r"^sip-[0-9a-f]{32}$")
_EVALUATION_ID_RE = re.compile(r"^sie-[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TEMP_DIR_RE = re.compile(r"^\.sip-tmp-[A-Za-z0-9_-]+$")

_MANIFEST_FIELDS = {
    "schema",
    "candidate_id",
    "candidate_sha256",
    "created_at",
    "proposal_binding",
    "author_identity",
    "files",
    "patch",
    "construction_policy",
    "authority_granted",
}
_PROPOSAL_BINDING_FIELDS = {
    "proposal_id",
    "proposal_content_sha256",
    "source_fingerprint",
    "proposer_identity",
    "active_attestation_ids",
}
_FILE_FIELDS = {
    "path",
    "suffix",
    "base_sha256",
    "candidate_sha256",
    "base_bytes",
    "candidate_bytes",
    "added_lines",
    "removed_lines",
}
_PATCH_FIELDS = {"format", "sha256", "bytes", "changed_lines"}
_EVALUATION_FIELDS = {
    "schema",
    "evaluation_id",
    "evaluation_sha256",
    "candidate_id",
    "candidate_sha256",
    "proposal_binding",
    "evaluated_at",
    "evaluator",
    "files",
    "status",
    "eligible_for_external_review",
    "eligible_for_execution",
    "execution_performed",
    "tests_executed",
    "live_source_writes",
    "authority_granted",
}

_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "aiohttp",
        "ctypes",
        "httpx",
        "multiprocessing",
        "paramiko",
        "requests",
        "shutil",
        "socket",
        "subprocess",
        "urllib",
    }
)
_FORBIDDEN_DIRECT_CALLS = frozenset(
    {"__import__", "breakpoint", "compile", "eval", "exec", "open"}
)
_FORBIDDEN_QUALIFIED_CALLS = frozenset(
    {
        "os.chmod",
        "os.chown",
        "os.makedirs",
        "os.mkdir",
        "os.open",
        "os.popen",
        "os.remove",
        "os.removedirs",
        "os.rename",
        "os.renames",
        "os.replace",
        "os.rmdir",
        "os.system",
        "os.unlink",
    }
)
_FORBIDDEN_ATTRIBUTE_CALLS = frozenset(
    {
        "chmod",
        "chown",
        "execv",
        "execve",
        "hardlink_to",
        "mkdir",
        "open",
        "popen",
        "rename",
        "rmdir",
        "spawnl",
        "spawnv",
        "symlink_to",
        "system",
        "touch",
        "unlink",
        "write_bytes",
        "write_text",
    }
)


class PatchSandboxError(ValueError):
    """Raised when a candidate violates the quarantine contract."""


def _construction_policy() -> dict[str, Any]:
    return {
        "kind": "whole_file_replacement",
        "existing_regular_files_only": True,
        "artifact_storage": "outside_source_repository",
        "live_source_writes": False,
        "candidate_code_imported": False,
        "candidate_code_executed": False,
        "commands_executed": False,
        "tests_executed": False,
        "git_operations_performed": False,
        "authority_granted": False,
    }


def _static_evaluator_contract() -> dict[str, Any]:
    return {
        "id": STATIC_EVALUATOR_ID,
        "kind": "deterministic_nonexecuting_static_checks",
        "python_ast_parse": True,
        "python_capability_heuristic": True,
        "json_parse": True,
        "yaml_safe_load": True,
        "markdown_utf8_validation": True,
        "candidate_code_imported": False,
        "candidate_code_executed": False,
        "commands_executed": False,
        "tests_executed": False,
        "eligible_for_execution": False,
        "heuristic_is_security_boundary": False,
    }


def sandbox_contract() -> dict[str, Any]:
    """Return the immutable public contract for Phase 3 artifacts."""
    return {
        "schema": SANDBOX_CONTRACT_SCHEMA,
        "candidate_schema": CANDIDATE_SCHEMA,
        "evaluation_schema": EVALUATION_SCHEMA,
        "verified_low_risk_proposal_required": True,
        "authenticated_proposer_authorship_required": True,
        "active_attestations_bound": True,
        "source_fingerprint_must_remain_current": True,
        "whole_file_replacements_only": True,
        "existing_regular_files_only": True,
        "supported_suffixes": sorted(SUPPORTED_SUFFIXES),
        "limits": {
            "maximum_files": MAX_CANDIDATE_FILES,
            "maximum_file_bytes": MAX_FILE_BYTES,
            "maximum_total_candidate_bytes": MAX_TOTAL_BYTES,
            "maximum_patch_bytes": MAX_PATCH_BYTES,
            "maximum_changed_lines": MAX_CHANGED_LINES,
        },
        "construction_policy": _construction_policy(),
        "static_evaluator": _static_evaluator_contract(),
        "live_source_writes": False,
        "candidate_code_executed": False,
        "tests_executed": False,
        "git_operations_performed": False,
        "authority_granted": False,
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record_digest(record: dict[str, Any], digest_field: str) -> str:
    payload = copy.deepcopy(record)
    payload.pop(digest_field, None)
    return _sha256(canonical_json_bytes(payload))


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.lower()):
        raise PatchSandboxError(f"{field} must be exactly 64 hexadecimal characters")
    return value.lower()


def _normalize_repo_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PatchSandboxError("change path must be a non-empty string")
    raw = value.strip().replace("\\", "/")
    if "\x00" in raw or raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        raise PatchSandboxError("change path must stay inside the source repository")
    if any(part in {"", ".", ".."} for part in raw.split("/")):
        raise PatchSandboxError("change path contains an ambiguous or escaping segment")
    normalized = str(PurePosixPath(raw))
    if Path(normalized).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise PatchSandboxError(
            "change path has an unsupported suffix; allowed suffixes are: "
            + ", ".join(sorted(SUPPORTED_SUFFIXES))
        )
    return normalized


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _unified_diff(path: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _diff_counts(patch: str) -> tuple[int, int]:
    added = 0
    removed = 0
    for line in patch.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _call_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _python_capability_findings(tree: ast.AST) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in _FORBIDDEN_IMPORT_ROOTS:
                    findings.append(
                        {
                            "kind": "forbidden_import",
                            "symbol": alias.name,
                            "line": node.lineno,
                        }
                    )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root in _FORBIDDEN_IMPORT_ROOTS:
                findings.append(
                    {
                        "kind": "forbidden_import",
                        "symbol": node.module,
                        "line": node.lineno,
                    }
                )
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            leaf = name.rsplit(".", 1)[-1] if name else None
            forbidden_qualified = bool(
                name in _FORBIDDEN_QUALIFIED_CALLS
                or (name and name.startswith(("os.exec", "os.spawn")))
            )
            if (
                name in _FORBIDDEN_DIRECT_CALLS
                or leaf in _FORBIDDEN_ATTRIBUTE_CALLS
                or forbidden_qualified
            ):
                findings.append(
                    {
                        "kind": "forbidden_call",
                        "symbol": name,
                        "line": node.lineno,
                    }
                )
    return sorted(
        findings,
        key=lambda item: (int(item["line"]), str(item["kind"]), str(item["symbol"])),
    )


class PatchSandbox:
    """Construct and inspect inert candidate artifacts outside a repository."""

    def __init__(self, *, repo_root: Path | None, sandbox_root: Path) -> None:
        self.repo_root = repo_root.resolve() if repo_root else None
        self.sandbox_root = sandbox_root.expanduser()

    def _ensure_root(self) -> Path:
        if self.repo_root is None:
            raise PatchSandboxError("source repository not found")
        try:
            repo = self.repo_root.resolve(strict=True)
        except OSError as exc:
            raise PatchSandboxError("source repository is unavailable") from exc
        root = self.sandbox_root.resolve(strict=False)
        try:
            root.relative_to(repo)
        except ValueError:
            pass
        else:
            raise PatchSandboxError(
                "sandbox_root must be outside the source repository"
            )
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not root.is_dir() or root.is_symlink():
            raise PatchSandboxError("sandbox_root must be a regular directory")
        return root.resolve(strict=True)

    def _source_file(self, raw_path: Any) -> tuple[str, Path, bytes]:
        if self.repo_root is None:
            raise PatchSandboxError("source repository not found")
        relative = _normalize_repo_path(raw_path)
        path = self.repo_root / relative
        if path.is_symlink():
            raise PatchSandboxError(f"candidate target is a symlink: {relative}")
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.repo_root)
        except (OSError, ValueError) as exc:
            raise PatchSandboxError(
                f"candidate target must be an existing repository file: {relative}"
            ) from exc
        if not resolved.is_file() or resolved.is_symlink():
            raise PatchSandboxError(
                f"candidate target must be a regular file: {relative}"
            )
        try:
            data = resolved.read_bytes()
            data.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise PatchSandboxError(
                f"candidate target must be readable UTF-8 text: {relative}"
            ) from exc
        if len(data) > MAX_FILE_BYTES:
            raise PatchSandboxError(
                f"candidate target exceeds the {MAX_FILE_BYTES}-byte limit: {relative}"
            )
        return relative, resolved, data

    @staticmethod
    def _candidate_id(value: Any) -> str:
        if not isinstance(value, str) or not _CANDIDATE_ID_RE.fullmatch(value):
            raise PatchSandboxError("candidate_id is malformed")
        return value

    @staticmethod
    def _evaluation_id(value: Any) -> str:
        if not isinstance(value, str) or not _EVALUATION_ID_RE.fullmatch(value):
            raise PatchSandboxError("evaluation_id is malformed")
        return value

    def _candidate_directory(self, candidate_id: Any) -> Path:
        root = self._ensure_root()
        identifier = self._candidate_id(candidate_id)
        path = root / identifier
        if path.is_symlink():
            raise PatchSandboxError("candidate directory may not be a symlink")
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise PatchSandboxError(
                f"candidate artifact not found: {identifier}"
            ) from exc
        if not resolved.is_dir():
            raise PatchSandboxError("candidate artifact is not a directory")
        return resolved

    @staticmethod
    def _read_regular(path: Path, *, maximum: int, label: str) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise PatchSandboxError(f"{label} is missing or not a regular file")
        try:
            size = path.stat().st_size
            if size > maximum:
                raise PatchSandboxError(f"{label} exceeds its size limit")
            return path.read_bytes()
        except OSError as exc:
            raise PatchSandboxError(f"{label} is unreadable") from exc

    @staticmethod
    def _workspace_paths(workspace: Path) -> set[str]:
        if workspace.is_symlink() or not workspace.is_dir():
            raise PatchSandboxError("candidate workspace is malformed")
        files: set[str] = set()
        for current, directories, filenames in os.walk(workspace, followlinks=False):
            current_path = Path(current)
            for directory in directories:
                if (current_path / directory).is_symlink():
                    raise PatchSandboxError("candidate workspace contains a symlink")
            for filename in filenames:
                path = current_path / filename
                if path.is_symlink() or not path.is_file():
                    raise PatchSandboxError(
                        "candidate workspace contains a non-regular file"
                    )
                files.add(path.relative_to(workspace).as_posix())
        return files

    @staticmethod
    def _validate_identity(value: Any, label: str) -> dict[str, Any]:
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("kind"), str)
            or not isinstance(value.get("id"), str)
            or not value["id"].strip()
            or set(value) != {"kind", "id", "issuer"}
            or (
                value.get("issuer") is not None and not isinstance(value["issuer"], str)
            )
        ):
            raise PatchSandboxError(f"{label} identity is malformed")
        return copy.deepcopy(value)

    @staticmethod
    def _validate_source_fingerprint(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != {
            "revision",
            "manifest_sha256",
        }:
            raise PatchSandboxError("proposal source fingerprint is malformed")
        manifest = _require_sha256(
            value.get("manifest_sha256"), "source_fingerprint.manifest_sha256"
        )
        revision = value.get("revision")
        if revision is not None and (
            not isinstance(revision, str)
            or not re.fullmatch(r"[0-9a-fA-F]{7,64}", revision)
        ):
            raise PatchSandboxError("proposal source revision is malformed")
        return {
            "revision": revision.lower() if isinstance(revision, str) else None,
            "manifest_sha256": manifest,
        }

    def construct(
        self,
        *,
        proposal_id: str,
        proposal_content_sha256: str,
        source_fingerprint: dict[str, Any],
        proposer_identity: dict[str, Any],
        author_identity: dict[str, Any],
        active_attestation_ids: list[str],
        changes: Any,
        created_at: str,
    ) -> dict[str, Any]:
        """Materialize a whole-file candidate without touching live source."""
        if not isinstance(changes, list) or not changes:
            raise PatchSandboxError("changes must be a non-empty list")
        if len(changes) > MAX_CANDIDATE_FILES:
            raise PatchSandboxError(
                f"changes may contain at most {MAX_CANDIDATE_FILES} files"
            )
        proposal_digest = _require_sha256(
            proposal_content_sha256, "proposal_content_sha256"
        )
        fingerprint = self._validate_source_fingerprint(source_fingerprint)
        proposer = self._validate_identity(proposer_identity, "proposer")
        author = self._validate_identity(author_identity, "author")
        if proposer != author:
            raise PatchSandboxError(
                "candidate author must match the authenticated proposal author"
            )
        if (
            not isinstance(active_attestation_ids, list)
            or not active_attestation_ids
            or any(
                not isinstance(item, str) or not re.fullmatch(r"sia-[0-9a-f]{32}", item)
                for item in active_attestation_ids
            )
            or len(set(active_attestation_ids)) != len(active_attestation_ids)
        ):
            raise PatchSandboxError("active attestation binding is malformed")

        prepared: list[dict[str, Any]] = []
        seen: set[str] = set()
        total_bytes = 0
        total_changed_lines = 0
        for raw_change in changes:
            if not isinstance(raw_change, dict) or set(raw_change) != {
                "path",
                "expected_sha256",
                "content",
            }:
                raise PatchSandboxError(
                    "each change must contain exactly path, expected_sha256, and content"
                )
            relative, _source_path, base = self._source_file(raw_change.get("path"))
            if relative in seen:
                raise PatchSandboxError("changes may not contain duplicate paths")
            seen.add(relative)
            expected = _require_sha256(
                raw_change.get("expected_sha256"), "expected_sha256"
            )
            if _sha256(base) != expected:
                raise PatchSandboxError(
                    f"base digest changed for {relative}; reconstruct from current source"
                )
            content = raw_change.get("content")
            if not isinstance(content, str):
                raise PatchSandboxError("change content must be a UTF-8 string")
            candidate = content.encode("utf-8")
            if b"\x00" in candidate:
                raise PatchSandboxError("change content may not contain NUL bytes")
            if len(candidate) > MAX_FILE_BYTES:
                raise PatchSandboxError(
                    f"candidate content for {relative} exceeds {MAX_FILE_BYTES} bytes"
                )
            if candidate == base:
                raise PatchSandboxError(
                    f"candidate content for {relative} does not change the file"
                )
            total_bytes += len(candidate)
            if total_bytes > MAX_TOTAL_BYTES:
                raise PatchSandboxError(
                    f"candidate content exceeds {MAX_TOTAL_BYTES} total bytes"
                )
            patch = _unified_diff(
                relative,
                base.decode("utf-8"),
                candidate.decode("utf-8"),
            )
            added, removed = _diff_counts(patch)
            total_changed_lines += added + removed
            prepared.append(
                {
                    "path": relative,
                    "suffix": Path(relative).suffix.lower(),
                    "base": base,
                    "candidate": candidate,
                    "patch": patch,
                    "base_sha256": expected,
                    "candidate_sha256": _sha256(candidate),
                    "base_bytes": len(base),
                    "candidate_bytes": len(candidate),
                    "added_lines": added,
                    "removed_lines": removed,
                }
            )
        if total_changed_lines > MAX_CHANGED_LINES:
            raise PatchSandboxError(
                f"candidate changes exceed the {MAX_CHANGED_LINES}-line limit"
            )

        prepared.sort(key=lambda item: str(item["path"]))
        patch_bytes = "".join(str(item["patch"]) for item in prepared).encode("utf-8")
        if len(patch_bytes) > MAX_PATCH_BYTES:
            raise PatchSandboxError(
                f"candidate patch exceeds the {MAX_PATCH_BYTES}-byte limit"
            )

        candidate_id = f"sip-{uuid.uuid4().hex}"
        manifest: dict[str, Any] = {
            "schema": CANDIDATE_SCHEMA,
            "candidate_id": candidate_id,
            "created_at": created_at,
            "proposal_binding": {
                "proposal_id": proposal_id,
                "proposal_content_sha256": proposal_digest,
                "source_fingerprint": fingerprint,
                "proposer_identity": proposer,
                "active_attestation_ids": sorted(active_attestation_ids),
            },
            "author_identity": author,
            "files": [
                {
                    field: item[field]
                    for field in (
                        "path",
                        "suffix",
                        "base_sha256",
                        "candidate_sha256",
                        "base_bytes",
                        "candidate_bytes",
                        "added_lines",
                        "removed_lines",
                    )
                }
                for item in prepared
            ],
            "patch": {
                "format": "unified_diff",
                "sha256": _sha256(patch_bytes),
                "bytes": len(patch_bytes),
                "changed_lines": total_changed_lines,
            },
            "construction_policy": _construction_policy(),
            "authority_granted": False,
        }
        manifest["candidate_sha256"] = _record_digest(manifest, "candidate_sha256")

        root = self._ensure_root()
        final_directory = root / candidate_id
        if final_directory.exists() or final_directory.is_symlink():
            raise PatchSandboxError("generated candidate identifier already exists")
        temporary = Path(tempfile.mkdtemp(prefix=".sip-tmp-", dir=root))
        try:
            workspace = temporary / "workspace"
            workspace.mkdir()
            for item in prepared:
                _write_bytes(workspace / str(item["path"]), item["candidate"])
            _write_bytes(temporary / "candidate.patch", patch_bytes)
            atomic_json_write(temporary / "manifest.json", manifest, indent=2)
            _fsync_directory(workspace)
            _fsync_directory(temporary)
            os.replace(temporary, final_directory)
            _fsync_directory(root)
        except BaseException:
            if temporary.exists() and _TEMP_DIR_RE.fullmatch(temporary.name):
                shutil.rmtree(temporary, ignore_errors=True)
            raise
        return copy.deepcopy(manifest)

    def _load_candidate(
        self, candidate_id: Any
    ) -> tuple[dict[str, Any], str, dict[str, bytes]]:
        directory = self._candidate_directory(candidate_id)
        manifest_bytes = self._read_regular(
            directory / "manifest.json",
            maximum=MAX_MANIFEST_BYTES,
            label="candidate manifest",
        )
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PatchSandboxError("candidate manifest is malformed") from exc
        if (
            not isinstance(manifest, dict)
            or set(manifest) != _MANIFEST_FIELDS
            or manifest.get("schema") != CANDIDATE_SCHEMA
            or manifest.get("candidate_id") != directory.name
            or manifest.get("authority_granted") is not False
            or manifest.get("construction_policy") != _construction_policy()
        ):
            raise PatchSandboxError("candidate manifest violates its contract")
        digest = manifest.get("candidate_sha256")
        if (
            not isinstance(digest, str)
            or not _SHA256_RE.fullmatch(digest)
            or digest != _record_digest(manifest, "candidate_sha256")
        ):
            raise PatchSandboxError("candidate manifest digest is invalid")

        binding = manifest.get("proposal_binding")
        if not isinstance(binding, dict) or set(binding) != _PROPOSAL_BINDING_FIELDS:
            raise PatchSandboxError("candidate proposal binding is malformed")
        if (
            not isinstance(binding.get("proposal_id"), str)
            or not binding["proposal_id"]
        ):
            raise PatchSandboxError("candidate proposal identifier is malformed")
        _require_sha256(
            binding.get("proposal_content_sha256"), "proposal_content_sha256"
        )
        self._validate_source_fingerprint(binding.get("source_fingerprint"))
        proposer = self._validate_identity(binding.get("proposer_identity"), "proposer")
        author = self._validate_identity(manifest.get("author_identity"), "author")
        if proposer != author:
            raise PatchSandboxError("candidate author binding is inconsistent")
        attestation_ids = binding.get("active_attestation_ids")
        if (
            not isinstance(attestation_ids, list)
            or not attestation_ids
            or attestation_ids != sorted(attestation_ids)
            or len(set(attestation_ids)) != len(attestation_ids)
            or any(
                not isinstance(item, str) or not re.fullmatch(r"sia-[0-9a-f]{32}", item)
                for item in attestation_ids
            )
        ):
            raise PatchSandboxError("candidate attestation binding is malformed")

        patch_metadata = manifest.get("patch")
        if (
            not isinstance(patch_metadata, dict)
            or set(patch_metadata) != _PATCH_FIELDS
            or patch_metadata.get("format") != "unified_diff"
        ):
            raise PatchSandboxError("candidate patch metadata is malformed")
        patch_bytes = self._read_regular(
            directory / "candidate.patch",
            maximum=MAX_PATCH_BYTES,
            label="candidate patch",
        )
        if patch_metadata.get("sha256") != _sha256(patch_bytes) or patch_metadata.get(
            "bytes"
        ) != len(patch_bytes):
            raise PatchSandboxError("candidate patch digest is invalid")
        try:
            patch = patch_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PatchSandboxError("candidate patch is not UTF-8") from exc

        files = manifest.get("files")
        if (
            not isinstance(files, list)
            or not 1 <= len(files) <= MAX_CANDIDATE_FILES
            or any(
                not isinstance(item, dict) or set(item) != _FILE_FIELDS
                for item in files
            )
        ):
            raise PatchSandboxError("candidate file manifest is malformed")
        paths = [item.get("path") for item in files]
        if paths != sorted(paths) or len(set(paths)) != len(paths):
            raise PatchSandboxError("candidate file paths are malformed or duplicated")
        workspace = directory / "workspace"
        if self._workspace_paths(workspace) != set(paths):
            raise PatchSandboxError("candidate workspace file set is inconsistent")

        contents: dict[str, bytes] = {}
        total_bytes = 0
        total_changed_lines = 0
        for item in files:
            relative = _normalize_repo_path(item.get("path"))
            if item.get("suffix") != Path(relative).suffix.lower():
                raise PatchSandboxError("candidate file suffix binding is malformed")
            _require_sha256(item.get("base_sha256"), "base_sha256")
            candidate_digest = _require_sha256(
                item.get("candidate_sha256"), "candidate_sha256"
            )
            content = self._read_regular(
                workspace / relative,
                maximum=MAX_FILE_BYTES,
                label=f"candidate file {relative}",
            )
            try:
                content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PatchSandboxError(
                    f"candidate file is not UTF-8: {relative}"
                ) from exc
            if (
                _sha256(content) != candidate_digest
                or item.get("candidate_bytes") != len(content)
                or not isinstance(item.get("base_bytes"), int)
                or item["base_bytes"] < 0
                or not isinstance(item.get("added_lines"), int)
                or not isinstance(item.get("removed_lines"), int)
                or item["added_lines"] < 0
                or item["removed_lines"] < 0
            ):
                raise PatchSandboxError(
                    f"candidate file digest or metadata is inconsistent: {relative}"
                )
            total_bytes += len(content)
            total_changed_lines += item["added_lines"] + item["removed_lines"]
            contents[relative] = content
        if total_bytes > MAX_TOTAL_BYTES:
            raise PatchSandboxError("candidate total content exceeds its size limit")
        if (
            total_changed_lines != patch_metadata.get("changed_lines")
            or total_changed_lines > MAX_CHANGED_LINES
        ):
            raise PatchSandboxError("candidate changed-line count is inconsistent")
        return manifest, patch, contents

    def load_manifest(self, candidate_id: Any) -> dict[str, Any]:
        manifest, _patch, _contents = self._load_candidate(candidate_id)
        return copy.deepcopy(manifest)

    @staticmethod
    def _evaluate_file(path: str, content: bytes) -> dict[str, Any]:
        text = content.decode("utf-8")
        suffix = Path(path).suffix.lower()
        checks: list[dict[str, Any]] = [
            {"name": "utf8_text", "status": "passed", "findings": []}
        ]
        if suffix == ".py":
            try:
                tree = ast.parse(text, filename=path)
            except SyntaxError as exc:
                checks.append(
                    {
                        "name": "python_ast_parse",
                        "status": "rejected",
                        "findings": [
                            {
                                "kind": "syntax_error",
                                "message": exc.msg,
                                "line": exc.lineno,
                                "offset": exc.offset,
                            }
                        ],
                    }
                )
            else:
                checks.append(
                    {"name": "python_ast_parse", "status": "passed", "findings": []}
                )
                findings = _python_capability_findings(tree)
                checks.append(
                    {
                        "name": "python_capability_heuristic",
                        "status": "rejected" if findings else "passed",
                        "findings": findings,
                    }
                )
        elif suffix == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                checks.append(
                    {
                        "name": "json_parse",
                        "status": "rejected",
                        "findings": [
                            {
                                "kind": "parse_error",
                                "message": exc.msg,
                                "line": exc.lineno,
                                "column": exc.colno,
                            }
                        ],
                    }
                )
            else:
                checks.append(
                    {"name": "json_parse", "status": "passed", "findings": []}
                )
        elif suffix in {".yaml", ".yml"}:
            try:
                yaml.safe_load(text)
            except yaml.YAMLError as exc:
                checks.append(
                    {
                        "name": "yaml_safe_load",
                        "status": "rejected",
                        "findings": [
                            {"kind": "parse_error", "message": str(exc)[:500]}
                        ],
                    }
                )
            else:
                checks.append(
                    {"name": "yaml_safe_load", "status": "passed", "findings": []}
                )
        elif suffix == ".md":
            checks.append(
                {
                    "name": "markdown_utf8_validation",
                    "status": "passed",
                    "findings": [],
                }
            )
        rejected = any(check["status"] == "rejected" for check in checks)
        return {
            "path": path,
            "status": "rejected" if rejected else "passed",
            "checks": checks,
        }

    def evaluate(
        self,
        *,
        candidate_id: Any,
        expected_candidate_sha256: Any,
        evaluated_at: str,
    ) -> dict[str, Any]:
        """Run non-executing parsing and capability heuristics on a candidate."""
        manifest, _patch, contents = self._load_candidate(candidate_id)
        expected = _require_sha256(
            expected_candidate_sha256, "expected_candidate_sha256"
        )
        if manifest["candidate_sha256"] != expected:
            raise PatchSandboxError(
                "candidate digest changed; inspect the candidate again"
            )
        for item in manifest["files"]:
            relative, _path, current = self._source_file(item["path"])
            if _sha256(current) != item["base_sha256"]:
                raise PatchSandboxError(
                    f"live source changed for {relative}; candidate is stale"
                )

        file_results = [
            self._evaluate_file(path, contents[path]) for path in sorted(contents)
        ]
        passed = all(item["status"] == "passed" for item in file_results)
        evaluator_contract = _static_evaluator_contract()
        evaluation: dict[str, Any] = {
            "schema": EVALUATION_SCHEMA,
            "evaluation_id": f"sie-{uuid.uuid4().hex}",
            "candidate_id": manifest["candidate_id"],
            "candidate_sha256": manifest["candidate_sha256"],
            "proposal_binding": copy.deepcopy(manifest["proposal_binding"]),
            "evaluated_at": evaluated_at,
            "evaluator": {
                "id": STATIC_EVALUATOR_ID,
                "contract_sha256": _sha256(canonical_json_bytes(evaluator_contract)),
                "contract": evaluator_contract,
            },
            "files": file_results,
            "status": "static_checks_passed" if passed else "rejected",
            "eligible_for_external_review": passed,
            "eligible_for_execution": False,
            "execution_performed": False,
            "tests_executed": False,
            "live_source_writes": False,
            "authority_granted": False,
        }
        evaluation["evaluation_sha256"] = _record_digest(
            evaluation, "evaluation_sha256"
        )

        directory = self._candidate_directory(manifest["candidate_id"])
        evaluations = directory / "evaluations"
        if evaluations.exists() and (
            evaluations.is_symlink() or not evaluations.is_dir()
        ):
            raise PatchSandboxError("candidate evaluations directory is malformed")
        evaluations.mkdir(exist_ok=True)
        destination = evaluations / f"{evaluation['evaluation_id']}.json"
        if destination.exists() or destination.is_symlink():
            raise PatchSandboxError("generated evaluation identifier already exists")
        atomic_json_write(destination, evaluation, indent=2)
        return copy.deepcopy(evaluation)

    def load_evaluations(self, candidate_id: Any) -> list[dict[str, Any]]:
        directory = self._candidate_directory(candidate_id)
        evaluations = directory / "evaluations"
        if not evaluations.exists():
            return []
        if evaluations.is_symlink() or not evaluations.is_dir():
            raise PatchSandboxError("candidate evaluations directory is malformed")
        results: list[dict[str, Any]] = []
        for path in sorted(evaluations.iterdir(), key=lambda item: item.name):
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise PatchSandboxError(
                    "candidate evaluations contain an invalid entry"
                )
            evaluation_id = path.stem
            self._evaluation_id(evaluation_id)
            raw = self._read_regular(
                path,
                maximum=MAX_EVALUATION_BYTES,
                label="candidate evaluation",
            )
            try:
                evaluation = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PatchSandboxError("candidate evaluation is malformed") from exc
            if (
                not isinstance(evaluation, dict)
                or set(evaluation) != _EVALUATION_FIELDS
                or evaluation.get("schema") != EVALUATION_SCHEMA
                or evaluation.get("evaluation_id") != evaluation_id
                or evaluation.get("candidate_id") != directory.name
                or evaluation.get("eligible_for_execution") is not False
                or evaluation.get("execution_performed") is not False
                or evaluation.get("tests_executed") is not False
                or evaluation.get("live_source_writes") is not False
                or evaluation.get("authority_granted") is not False
            ):
                raise PatchSandboxError("candidate evaluation violates its contract")
            digest = evaluation.get("evaluation_sha256")
            if (
                not isinstance(digest, str)
                or not _SHA256_RE.fullmatch(digest)
                or digest != _record_digest(evaluation, "evaluation_sha256")
            ):
                raise PatchSandboxError("candidate evaluation digest is invalid")
            results.append(evaluation)
        return results

    def status(
        self, candidate_id: Any, *, include_patch: bool = False
    ) -> dict[str, Any]:
        if not isinstance(include_patch, bool):
            raise PatchSandboxError("include_patch must be a boolean")
        manifest, patch, _contents = self._load_candidate(candidate_id)
        result = {
            "candidate": copy.deepcopy(manifest),
            "evaluations": self.load_evaluations(manifest["candidate_id"]),
            "patch_included": include_patch,
        }
        if include_patch:
            result["patch"] = patch
        return result

    def discard_candidate(self, candidate_id: Any) -> None:
        """Remove one exact generated artifact after a failed ledger commit."""
        root = self._ensure_root()
        identifier = self._candidate_id(candidate_id)
        path = root / identifier
        if path.is_symlink():
            path.unlink()
        elif path.is_dir() and path.resolve().parent == root:
            shutil.rmtree(path)

    def discard_evaluation(self, candidate_id: Any, evaluation_id: Any) -> None:
        """Remove one exact generated evaluation after a failed ledger commit."""
        directory = self._candidate_directory(candidate_id)
        identifier = self._evaluation_id(evaluation_id)
        evaluations = directory / "evaluations"
        if evaluations.is_symlink() or not evaluations.is_dir():
            raise PatchSandboxError("candidate evaluations directory is malformed")
        if evaluations.resolve(strict=True).parent != directory:
            raise PatchSandboxError(
                "candidate evaluations directory escaped quarantine"
            )
        path = evaluations / f"{identifier}.json"
        if path.is_symlink() or path.is_file():
            path.unlink()


__all__ = [
    "CANDIDATE_SCHEMA",
    "EVALUATION_SCHEMA",
    "PatchSandbox",
    "PatchSandboxError",
    "STATIC_EVALUATOR_ID",
    "sandbox_contract",
]
