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
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

from .atomic_write import atomic_json_write

SCHEMA_VERSION = 1
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


class SelfIterationError(ValueError):
    """Raised when an inspection or ledger operation violates its contract."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
    ) -> None:
        self.repo_root = repo_root.resolve() if repo_root else _discover_repo_root()
        self.ledger_path = ledger_path or Path.home() / ".anima" / "self_iteration.json"
        self._clock = clock
        self._lock = threading.RLock()

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
            },
            "ledger": self._ledger_summary(),
        }

    def _ledger_summary(self) -> dict[str, Any]:
        try:
            return {
                "proposal_count": len(self._load_ledger()["proposals"]),
                "schema_version": SCHEMA_VERSION,
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
        return {"schema_version": SCHEMA_VERSION, "proposals": []}

    def _load_ledger(self) -> dict[str, Any]:
        if not self.ledger_path.exists():
            return self._empty_ledger()
        try:
            data = json.loads(self.ledger_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise SelfIterationError(
                "self-iteration ledger is unreadable; refusing to overwrite it"
            ) from exc
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            raise SelfIterationError("self-iteration ledger has an unsupported schema")
        if not isinstance(data.get("proposals"), list):
            raise SelfIterationError("self-iteration ledger proposals are malformed")
        return data

    def _save_ledger(self, ledger: dict[str, Any]) -> None:
        atomic_json_write(self.ledger_path, ledger, indent=2)

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
        source: Any = "self_observation",
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
        if not isinstance(source, str) or source not in allowed_sources:
            raise SelfIterationError(
                f"source must be one of: {', '.join(sorted(allowed_sources))}"
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
        proposal = {
            "id": proposal_id,
            "created_at": created_at,
            "source": source,
            "status": status,
            "observation": observation_text,
            "hypothesis": hypothesis_text,
            "expected_outcome": expected_text,
            "evidence": evidence_items,
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

        with self._lock:
            ledger = self._load_ledger()
            ledger["proposals"].append(proposal)
            self._save_ledger(ledger)
        return proposal

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
        proposals = list(reversed(proposals))[:limit]
        return {"count": len(proposals), "proposals": proposals}

    def record_outcome(
        self,
        *,
        proposal_id: Any,
        decision: Any,
        observed_outcome: Any,
        evidence: Any,
        implementation_ref: Any,
        measurement_source: Any = "self_observation",
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
            not isinstance(measurement_source, str)
            or measurement_source not in allowed_measurement_sources
        ):
            raise SelfIterationError(
                "measurement_source must be one of: "
                + ", ".join(sorted(allowed_measurement_sources))
            )
        status_for_decision = {
            "keep": "retained",
            "revert": "reverted",
            "inconclusive": "measurement_inconclusive",
        }

        with self._lock:
            ledger = self._load_ledger()
            proposal = next(
                (
                    item
                    for item in ledger["proposals"]
                    if item.get("id") == proposal_id_text
                ),
                None,
            )
            if proposal is None:
                raise SelfIterationError(f"proposal not found: {proposal_id_text}")
            event = {
                "type": "outcome_recorded",
                "at": _isoformat(self._clock()),
                "decision": decision,
                "observed_outcome": observed_text,
                "evidence": evidence_items,
                "implementation_ref": implementation_text,
                "measurement_source": measurement_source,
                "code_fingerprint": self._code_fingerprint(),
            }
            proposal.setdefault("events", []).append(event)
            proposal["status"] = status_for_decision[decision]
            self._save_ledger(ledger)
        return proposal


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
