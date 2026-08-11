"""Signed, bounded verification primitives for self-iteration proposals.

The verifier registry uses symmetric HMAC keys because Anima's Raspberry Pi
runtime deliberately has no heavyweight cryptography dependency.  This gives
server-verifiable integrity, not public-key non-repudiation.  The surrounding
self-iteration system therefore permits a valid attestation to affect proposal
priority only; it never grants implementation, merge, or deployment authority.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

ATTESTATION_SCHEMA = "anima.self_iteration.attestation.v1"
SIGNATURE_ALGORITHM = "hmac-sha256"
VERIFIER_KEYS_ENV = "ANIMA_SELF_ITERATION_VERIFIER_KEYS"
MAX_ATTESTATION_VALIDITY = timedelta(days=7)
CHALLENGE_VALIDITY = timedelta(minutes=10)
MAX_CLOCK_SKEW = timedelta(minutes=5)

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
_CHALLENGE_ID_RE = re.compile(r"^sic-[0-9a-f]{32}$")
_ATTESTATION_ID_RE = re.compile(r"^sia-[0-9a-f]{32}$")
_EVIDENCE_KINDS = {"artifact", "canary", "ci_run", "review", "test"}

_PROPOSAL_CONTENT_FIELDS = (
    "id",
    "created_at",
    "source_claim",
    "proposer_identity",
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
)


class VerificationError(ValueError):
    """Raised when a verifier key, challenge, or attestation is invalid."""


@dataclass(frozen=True)
class VerifierKey:
    """One rotatable symmetric key bound to an authenticated verifier ID."""

    verifier_id: str
    key_id: str
    secret: bytes = field(repr=False)


VerifierKeyProvider = Callable[[str, str | None], VerifierKey | None]


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc_timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise VerificationError(f"{field_name} must be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerificationError(f"{field_name} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise VerificationError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VerificationError("attestation content must be canonical JSON") from exc


def authenticated_identity(provenance: Any) -> dict[str, str | None]:
    """Extract a stable identity only from authenticated server provenance."""
    if not isinstance(provenance, dict):
        raise VerificationError("authenticated provenance is unavailable")
    authentication = provenance.get("authentication")
    actor = provenance.get("actor")
    trust = provenance.get("trust")
    if (
        not isinstance(authentication, dict)
        or authentication.get("verified") is not True
        or not isinstance(actor, dict)
        or actor.get("verified") is not True
        or not isinstance(trust, dict)
        or trust.get("actor_authenticated") is not True
    ):
        raise VerificationError("authenticated provenance is unavailable")

    identifier = actor.get("id")
    if (
        not isinstance(identifier, str)
        or not identifier.strip()
        or len(identifier.strip()) > 500
    ):
        raise VerificationError("authenticated actor identity is malformed")
    kind = actor.get("kind", "authenticated_actor")
    if not isinstance(kind, str) or not kind.strip() or len(kind.strip()) > 100:
        raise VerificationError("authenticated actor kind is malformed")
    issuer = actor.get("issuer")
    if issuer is not None and (
        not isinstance(issuer, str) or not issuer.strip() or len(issuer.strip()) > 1000
    ):
        raise VerificationError("authenticated actor issuer is malformed")
    return {
        "kind": kind.strip(),
        "id": identifier.strip(),
        "issuer": issuer.strip() if isinstance(issuer, str) else None,
    }


def proposal_content(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        field_name: proposal.get(field_name) for field_name in _PROPOSAL_CONTENT_FIELDS
    }


def proposal_content_sha256(proposal: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(proposal_content(proposal))).hexdigest()


def proposal_subject_fingerprint(proposal: dict[str, Any]) -> dict[str, Any]:
    fingerprint = proposal.get("code_fingerprint")
    if not isinstance(fingerprint, dict):
        raise VerificationError("proposal code fingerprint is unavailable")
    manifest = fingerprint.get("manifest_sha256")
    if not isinstance(manifest, str) or not _SHA256_RE.fullmatch(manifest):
        raise VerificationError("proposal manifest fingerprint is unavailable")
    revision = fingerprint.get("revision")
    if revision is not None and (
        not isinstance(revision, str)
        or not re.fullmatch(r"[0-9a-fA-F]{7,64}", revision)
    ):
        raise VerificationError("proposal revision fingerprint is malformed")
    return {
        "revision": revision.lower() if isinstance(revision, str) else None,
        "manifest_sha256": manifest.lower(),
    }


def verification_contract() -> dict[str, Any]:
    return {
        "schema": ATTESTATION_SCHEMA,
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "signature_assurance": "symmetric_mac_server_verifiable",
        "authenticated_verifier_required": True,
        "authenticated_proposer_required": True,
        "verifier_must_differ_from_proposer": True,
        "proposal_content_bound": True,
        "source_fingerprint_bound": True,
        "evidence_digests_bound": True,
        "evidence_content_fetched_by_server": False,
        "evidence_assurance": "verifier_attested_digest_references",
        "one_time_challenge_required": True,
        "maximum_validity_seconds": int(MAX_ATTESTATION_VALIDITY.total_seconds()),
        "verified_priority_eligible": True,
        "verified_automation_eligible": False,
        "verified_authority_eligible": False,
        "log_completeness_assurance": "local_log_not_externally_anchored",
    }


def validate_evidence(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise VerificationError(
            "verification_evidence must be a non-empty list of digest records"
        )
    if len(value) > 20:
        raise VerificationError("verification_evidence may contain at most 20 items")

    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"kind", "uri", "sha256"}:
            raise VerificationError(
                "each verification_evidence item must contain only kind, uri, and sha256"
            )
        kind = item.get("kind")
        uri = item.get("uri")
        digest = item.get("sha256")
        if not isinstance(kind, str) or kind not in _EVIDENCE_KINDS:
            raise VerificationError(
                "verification evidence kind must be one of: "
                + ", ".join(sorted(_EVIDENCE_KINDS))
            )
        if not isinstance(uri, str) or not uri.strip() or len(uri.strip()) > 1000:
            raise VerificationError(
                "verification evidence uri must be 1 to 1000 characters"
            )
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise VerificationError(
                "verification evidence sha256 must be exactly 64 hexadecimal characters"
            )
        record = (kind, uri.strip(), digest.lower())
        if record in seen:
            raise VerificationError("verification_evidence may not contain duplicates")
        seen.add(record)
        normalized.append({"kind": record[0], "uri": record[1], "sha256": record[2]})
    return normalized


def _decode_key(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise VerificationError("configured verifier key is malformed")
    try:
        secret = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (ValueError, TypeError) as exc:
        raise VerificationError("configured verifier key is malformed") from exc
    if not 32 <= len(secret) <= 128:
        raise VerificationError("configured verifier key must decode to 32-128 bytes")
    return secret


def verifier_key_from_env(
    verifier_id: str, requested_key_id: str | None = None
) -> VerifierKey | None:
    """Resolve a key without ever returning or logging configured key text."""
    raw = os.environ.get(VERIFIER_KEYS_ENV)
    if raw is None:
        return None
    if len(raw) > 65_536:
        raise VerificationError("verifier key registry exceeds the size limit")
    try:
        registry = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VerificationError("verifier key registry is malformed") from exc
    if not isinstance(registry, dict):
        raise VerificationError("verifier key registry is malformed")
    entry = registry.get(verifier_id)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise VerificationError("configured verifier entry is malformed")
    active_key_id = entry.get("active_key_id")
    keys = entry.get("keys")
    key_id = requested_key_id or active_key_id
    if (
        not isinstance(key_id, str)
        or not _KEY_ID_RE.fullmatch(key_id)
        or not isinstance(keys, dict)
    ):
        raise VerificationError("configured verifier entry is malformed")
    encoded_key = keys.get(key_id)
    if encoded_key is None:
        return None
    return VerifierKey(
        verifier_id=verifier_id,
        key_id=key_id,
        secret=_decode_key(encoded_key),
    )


def attestation_signing_bytes(attestation: dict[str, Any]) -> bytes:
    return canonical_json_bytes(attestation)


def attestation_signing_input_b64(attestation: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(attestation_signing_bytes(attestation)).decode(
        "ascii"
    )


def sign_attestation(attestation: dict[str, Any], key: VerifierKey) -> str:
    """Sign an attestation; exposed for offline verifier clients and tests."""
    if attestation.get("verifier_id") != key.verifier_id:
        raise VerificationError("attestation verifier does not match the signing key")
    if attestation.get("key_id") != key.key_id:
        raise VerificationError("attestation key ID does not match the signing key")
    if not isinstance(key.secret, bytes) or not 32 <= len(key.secret) <= 128:
        raise VerificationError("signing key must contain 32-128 bytes")
    return hmac.new(
        key.secret, attestation_signing_bytes(attestation), hashlib.sha256
    ).hexdigest()


def verify_attestation_signature(
    attestation: dict[str, Any], signature: Any, key: VerifierKey
) -> bool:
    if not isinstance(signature, str) or not _SHA256_RE.fullmatch(signature):
        return False
    try:
        expected = sign_attestation(attestation, key)
    except VerificationError:
        return False
    return hmac.compare_digest(expected, signature.lower())


def build_attestation(
    *,
    proposal: dict[str, Any],
    verifier_key: VerifierKey,
    verifier_identity: dict[str, str | None],
    decision: str,
    statement: str,
    evidence: list[dict[str, str]],
    issued_at: datetime,
    expires_at: datetime | None,
    challenge_id: str,
    attestation_id: str,
    target_attestation_id: str | None,
) -> dict[str, Any]:
    if decision not in {"verified", "rejected", "revoke"}:
        raise VerificationError(
            "verification_decision must be one of: verified, rejected, revoke"
        )
    if not isinstance(statement, str) or not statement.strip():
        raise VerificationError("verification_statement must be a non-empty string")
    if len(statement.strip()) > 4000:
        raise VerificationError(
            "verification_statement must be at most 4000 characters"
        )
    if decision == "revoke":
        if not isinstance(target_attestation_id, str) or not target_attestation_id:
            raise VerificationError(
                "target_attestation_id is required for a revocation"
            )
        if expires_at is not None:
            raise VerificationError("revocation attestations may not expire")
    elif target_attestation_id is not None:
        raise VerificationError("target_attestation_id is only valid for a revocation")
    elif expires_at is None:
        raise VerificationError("expires_at is required for a verification verdict")

    try:
        proposer_identity = authenticated_identity(proposal.get("provenance"))
    except VerificationError as exc:
        raise VerificationError(
            "proposal lacks authenticated proposer provenance"
        ) from exc
    if proposal.get("proposer_identity") != proposer_identity:
        raise VerificationError("proposal proposer identity is inconsistent")
    if verifier_identity.get("id") != verifier_key.verifier_id:
        raise VerificationError("verifier identity does not match the signing key")
    if verifier_identity == proposer_identity:
        raise VerificationError("a proposer may not verify its own proposal")

    issued = issued_at.astimezone(timezone.utc)
    return {
        "schema": ATTESTATION_SCHEMA,
        "attestation_id": attestation_id,
        "challenge_id": challenge_id,
        "proposal_id": proposal.get("id"),
        "proposal_content_sha256": proposal_content_sha256(proposal),
        "subject_fingerprint": proposal_subject_fingerprint(proposal),
        "proposer_identity": proposer_identity,
        "verifier_identity": verifier_identity,
        "verifier_id": verifier_key.verifier_id,
        "key_id": verifier_key.key_id,
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "decision": decision,
        "target_attestation_id": target_attestation_id,
        "statement": statement.strip(),
        "evidence": evidence,
        "issued_at": _isoformat(issued),
        "challenge_expires_at": _isoformat(issued + CHALLENGE_VALIDITY),
        "expires_at": _isoformat(expires_at) if expires_at is not None else None,
    }


def validate_recorded_attestation(
    *,
    proposal: dict[str, Any],
    event: dict[str, Any],
    event_index: int,
    key_provider: VerifierKeyProvider,
    now: datetime,
) -> dict[str, Any]:
    events = proposal.get("events")
    if (
        not isinstance(events, list)
        or isinstance(event_index, bool)
        or not isinstance(event_index, int)
        or not 0 <= event_index < len(events)
        or events[event_index] is not event
    ):
        raise VerificationError("attestation event position is malformed")
    attestation = event.get("attestation")
    signature = event.get("signature")
    if not isinstance(attestation, dict) or not isinstance(signature, dict):
        raise VerificationError("attestation event is malformed")
    if (
        set(signature) != {"algorithm", "key_id", "value", "assurance"}
        or signature.get("assurance") != "symmetric_mac_server_verifiable"
    ):
        raise VerificationError("attestation signature fields are malformed")
    required_fields = {
        "schema",
        "attestation_id",
        "challenge_id",
        "proposal_id",
        "proposal_content_sha256",
        "subject_fingerprint",
        "proposer_identity",
        "verifier_identity",
        "verifier_id",
        "key_id",
        "signature_algorithm",
        "decision",
        "target_attestation_id",
        "statement",
        "evidence",
        "issued_at",
        "challenge_expires_at",
        "expires_at",
    }
    if set(attestation) != required_fields:
        raise VerificationError("attestation payload fields are malformed")
    if attestation.get("schema") != ATTESTATION_SCHEMA:
        raise VerificationError("attestation schema is unsupported")
    if signature.get("algorithm") != SIGNATURE_ALGORITHM:
        raise VerificationError("attestation signature algorithm is unsupported")
    if attestation.get("signature_algorithm") != SIGNATURE_ALGORITHM:
        raise VerificationError("attestation payload algorithm is unsupported")
    if signature.get("key_id") != attestation.get("key_id"):
        raise VerificationError("attestation key IDs do not match")
    attestation_id = attestation.get("attestation_id")
    challenge_id = attestation.get("challenge_id")
    if not isinstance(attestation_id, str) or not _ATTESTATION_ID_RE.fullmatch(
        attestation_id
    ):
        raise VerificationError("attestation ID is malformed")
    if not isinstance(challenge_id, str) or not _CHALLENGE_ID_RE.fullmatch(
        challenge_id
    ):
        raise VerificationError("challenge ID is malformed")
    if event.get("challenge_id") != challenge_id:
        raise VerificationError("attestation event challenge ID does not match")
    duplicate_ids = sum(
        1
        for candidate in events
        if isinstance(candidate, dict)
        and candidate.get("type") == "verification_attested"
        and isinstance(candidate.get("attestation"), dict)
        and candidate["attestation"].get("attestation_id") == attestation_id
    )
    if duplicate_ids != 1:
        raise VerificationError("attestation ID is not unique")
    challenge_uses = sum(
        1
        for candidate in events
        if isinstance(candidate, dict)
        and candidate.get("type") == "verification_attested"
        and candidate.get("challenge_id") == challenge_id
    )
    if challenge_uses != 1:
        raise VerificationError("verification challenge was replayed")

    challenges = [
        (index, candidate)
        for index, candidate in enumerate(events)
        if isinstance(candidate, dict)
        and candidate.get("type") == "verification_challenge_issued"
        and candidate.get("challenge_id") == challenge_id
    ]
    if len(challenges) != 1 or challenges[0][0] >= event_index:
        raise VerificationError("a unique prior verification challenge is required")
    challenge = challenges[0][1]
    if challenge.get("attestation") != attestation:
        raise VerificationError("attestation does not match its issued challenge")
    signing_digest = hashlib.sha256(canonical_json_bytes(attestation)).hexdigest()
    if challenge.get("signing_sha256") != signing_digest:
        raise VerificationError("verification challenge signing digest is malformed")
    if attestation.get("proposal_id") != proposal.get("id"):
        raise VerificationError("attestation belongs to another proposal")
    if attestation.get("proposal_content_sha256") != proposal_content_sha256(proposal):
        raise VerificationError("attestation proposal digest is stale")
    if attestation.get("subject_fingerprint") != proposal_subject_fingerprint(proposal):
        raise VerificationError("attestation source fingerprint is stale")

    proposer_identity = authenticated_identity(proposal.get("provenance"))
    if proposal.get("proposer_identity") != proposer_identity:
        raise VerificationError("proposal proposer identity is inconsistent")
    if attestation.get("proposer_identity") != proposer_identity:
        raise VerificationError("attestation proposer identity is stale")

    verifier_identity = attestation.get("verifier_identity")
    if not isinstance(verifier_identity, dict):
        raise VerificationError("attestation verifier identity is malformed")
    event_identity = authenticated_identity(event.get("provenance"))
    challenge_identity = authenticated_identity(challenge.get("provenance"))
    if verifier_identity != event_identity or verifier_identity != challenge_identity:
        raise VerificationError("attestation verifier provenance does not match")
    if verifier_identity == proposer_identity:
        raise VerificationError("a proposer may not verify its own proposal")

    verifier_id = attestation.get("verifier_id")
    key_id = attestation.get("key_id")
    if (
        not isinstance(verifier_id, str)
        or verifier_id != verifier_identity.get("id")
        or not isinstance(key_id, str)
        or not _KEY_ID_RE.fullmatch(key_id)
    ):
        raise VerificationError("attestation verifier identity is malformed")
    try:
        key = key_provider(verifier_id, key_id)
    except Exception as exc:
        raise VerificationError("verifier key lookup failed") from exc
    if key is None:
        raise VerificationError("verifier key is unavailable")
    if (
        not isinstance(key, VerifierKey)
        or key.verifier_id != verifier_id
        or key.key_id != key_id
        or not isinstance(key.secret, bytes)
        or not 32 <= len(key.secret) <= 128
    ):
        raise VerificationError("verifier key registry returned a malformed key")
    if not verify_attestation_signature(attestation, signature.get("value"), key):
        raise VerificationError("attestation signature is invalid")

    decision = attestation.get("decision")
    if decision not in {"verified", "rejected", "revoke"}:
        raise VerificationError("attestation decision is malformed")
    statement = attestation.get("statement")
    if (
        not isinstance(statement, str)
        or not statement.strip()
        or statement != statement.strip()
        or len(statement) > 4000
    ):
        raise VerificationError("attestation statement is malformed")
    if validate_evidence(attestation.get("evidence")) != attestation.get("evidence"):
        raise VerificationError("attestation evidence is not normalized")
    issued_at = parse_utc_timestamp(attestation.get("issued_at"), "issued_at")
    current = now.astimezone(timezone.utc)
    if issued_at > current + MAX_CLOCK_SKEW:
        raise VerificationError("attestation issued_at is in the future")
    challenge_expires_at = parse_utc_timestamp(
        attestation.get("challenge_expires_at"), "challenge_expires_at"
    )
    if challenge_expires_at != issued_at + CHALLENGE_VALIDITY:
        raise VerificationError("attestation challenge validity is malformed")
    if challenge.get("at") != attestation.get("issued_at"):
        raise VerificationError("verification challenge time is malformed")
    recorded_at = parse_utc_timestamp(event.get("at"), "attestation recorded_at")
    if recorded_at < issued_at or recorded_at >= challenge_expires_at:
        raise VerificationError("attestation was recorded outside its challenge window")
    expires_at_value = attestation.get("expires_at")
    if decision == "revoke":
        target_attestation_id = attestation.get("target_attestation_id")
        if not isinstance(
            target_attestation_id, str
        ) or not _ATTESTATION_ID_RE.fullmatch(target_attestation_id):
            raise VerificationError("revocation target is malformed")
        if expires_at_value is not None:
            raise VerificationError("revocation attestation may not expire")
        expires_at = None
    else:
        if attestation.get("target_attestation_id") is not None:
            raise VerificationError("verification verdict may not have a target")
        expires_at = parse_utc_timestamp(expires_at_value, "expires_at")
        if expires_at <= issued_at:
            raise VerificationError("attestation expires_at must follow issued_at")
        if expires_at - issued_at > MAX_ATTESTATION_VALIDITY:
            raise VerificationError("attestation validity exceeds seven days")

    return {
        "event": event,
        "event_index": event_index,
        "attestation": attestation,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "expired": expires_at is not None and current >= expires_at,
    }


def evaluate_verification(
    proposal: dict[str, Any],
    *,
    key_provider: VerifierKeyProvider,
    now: datetime,
) -> dict[str, Any]:
    validated: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    events = proposal.get("events")
    if not isinstance(events, list):
        events = []

    for event_index, event in enumerate(events):
        if not isinstance(event, dict) or event.get("type") != "verification_attested":
            continue
        attestation = event.get("attestation")
        attestation_id = (
            attestation.get("attestation_id")
            if isinstance(attestation, dict)
            else "unknown"
        )
        try:
            validated.append(
                validate_recorded_attestation(
                    proposal=proposal,
                    event=event,
                    event_index=event_index,
                    key_provider=key_provider,
                    now=now,
                )
            )
        except VerificationError as exc:
            invalid.append({"attestation_id": str(attestation_id), "reason": str(exc)})

    by_id = {item["attestation"].get("attestation_id"): item for item in validated}
    revoked: set[str] = set()
    for item in validated:
        attestation = item["attestation"]
        if attestation.get("decision") != "revoke":
            continue
        target_id = attestation.get("target_attestation_id")
        target = by_id.get(target_id)
        if target is None or target["attestation"].get("decision") == "revoke":
            invalid.append(
                {
                    "attestation_id": str(attestation.get("attestation_id")),
                    "reason": "revocation target is unavailable",
                }
            )
            continue
        if (
            target["event_index"] >= item["event_index"]
            or target["issued_at"] > item["issued_at"]
        ):
            invalid.append(
                {
                    "attestation_id": str(attestation.get("attestation_id")),
                    "reason": "revocation target does not precede the revocation",
                }
            )
            continue
        if target["attestation"].get("verifier_identity") != attestation.get(
            "verifier_identity"
        ):
            invalid.append(
                {
                    "attestation_id": str(attestation.get("attestation_id")),
                    "reason": "revocation verifier does not own the target attestation",
                }
            )
            continue
        revoked.add(str(target_id))

    verdicts = [
        item
        for item in validated
        if item["attestation"].get("decision") in {"verified", "rejected"}
    ]
    expired = {
        str(item["attestation"].get("attestation_id"))
        for item in verdicts
        if item["expired"]
    }
    active = [
        item
        for item in verdicts
        if not item["expired"]
        and str(item["attestation"].get("attestation_id")) not in revoked
    ]
    decisions = {item["attestation"].get("decision") for item in active}

    if invalid:
        status = "invalid"
    elif decisions == {"verified"}:
        status = "verified"
    elif decisions == {"rejected"}:
        status = "rejected"
    elif len(decisions) > 1:
        status = "conflicted"
    elif verdicts and all(
        str(item["attestation"].get("attestation_id")) in revoked for item in verdicts
    ):
        status = "revoked"
    elif verdicts and all(item["expired"] for item in verdicts):
        status = "expired"
    else:
        status = "unverified"

    trusted = status == "verified"
    return {
        "status": status,
        "effective_weight": 1.0 if trusted else 0.0,
        "priority_eligible": trusted,
        "automation_eligible": False,
        "authority_eligible": False,
        "signature_assurance": "symmetric_mac_server_verifiable",
        "weight_scope": "proposal_prioritization_only",
        "evidence_assurance": "verifier_attested_digest_references_not_server_fetched",
        "log_completeness_assurance": "local_log_not_externally_anchored",
        "valid_attestation_ids": sorted(
            str(item["attestation"].get("attestation_id")) for item in validated
        ),
        "active_attestation_ids": sorted(
            str(item["attestation"].get("attestation_id")) for item in active
        ),
        "active_verifiers": sorted(
            {str(item["attestation"].get("verifier_id")) for item in active}
        ),
        "revoked_attestation_ids": sorted(revoked),
        "expired_attestation_ids": sorted(expired),
        "invalid_attestations": invalid,
    }


__all__ = [
    "ATTESTATION_SCHEMA",
    "CHALLENGE_VALIDITY",
    "MAX_ATTESTATION_VALIDITY",
    "SIGNATURE_ALGORITHM",
    "VERIFIER_KEYS_ENV",
    "VerificationError",
    "VerifierKey",
    "VerifierKeyProvider",
    "authenticated_identity",
    "attestation_signing_input_b64",
    "build_attestation",
    "canonical_json_bytes",
    "evaluate_verification",
    "parse_utc_timestamp",
    "proposal_content_sha256",
    "proposal_subject_fingerprint",
    "sign_attestation",
    "validate_evidence",
    "validate_recorded_attestation",
    "verify_attestation_signature",
    "verification_contract",
    "verifier_key_from_env",
]
