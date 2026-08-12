# Isolated self-iteration execution

Phase 4 lets Lumen test one narrow class of self-authored candidate without
executing it in the Anima server process or changing the live checkout. It is
an evaluation capability, not source-editing authority.

The supported candidate is one to three existing `.py` files directly beneath
`src/anima_mcp/display/eras/`. It must already belong to a low-risk proposal,
carry a current independent verification attestation, and pass the Phase 3
non-executing static evaluator. The static result remains
`eligible_for_execution: false`; a separate signed execution approval is what
permits one bounded test attempt.

## Approval and execution flow

1. The authenticated proposer creates and statically evaluates a quarantined
   candidate.
2. A third authenticated principal calls `prepare_execution`. This approver
   must differ from both the proposer and every active proposal verifier.
3. The server returns a canonical ten-minute approval plan and
   `signing_input_b64`. The plan binds the proposal, active attestations,
   candidate, passing static evaluation, clean Git revision, candidate-applied
   tree digest, fixed test profile, resource limits, local image identity, and
   dedicated result signer.
4. That same approver signs the exact bytes with its configured HMAC key and
   calls `execute_candidate` with the challenge ID and signature.
5. After revalidating every binding, the server durably claims the challenge.
   The claim is one-use and is persisted before candidate code can start.
6. The server reconstructs the workspace from committed Git blobs, substitutes
   only the approved candidate bytes, mounts it read-only, and runs the fixed
   profile in Docker.
7. The approver's MAC is retained in the one-use claim and result artifact. A
   dedicated service signer then signs the complete bounded result, including
   the original approval and its MAC. The result artifact is durably stored
   before its compact ledger event is appended.

If the process stops after the one-use claim but before a valid signed result
is stored, `execution_status` reports `claimed_result_indeterminate`. Automatic
retry is forbidden because the system cannot prove that the prior attempt did
not start. An operator must inspect and issue a new candidate or approval.

## Fixed isolation envelope

The runner accepts no caller-supplied command or image. The only profile is
`display_era_pytest_v1`, which invokes `/usr/local/bin/python -m pytest` for the
five server-owned display-era test modules. Its current limits are part of the
signed plan:

- 180-second host-enforced timeout
- 512 MiB memory and swap ceiling
- 1 CPU
- 128 PIDs/processes
- 256 open files
- 64 MiB writable `/tmp`
- 64 KiB captured prefix per output stream
- 4 MiB combined stdout/stderr termination ceiling

Docker is invoked with a local Unix socket and a digest-pinned image already
present on the host. Pulling and building are disabled. The container uses:

- `--network=none`, `--ipc=none`, and a private cgroup namespace
- a read-only root filesystem and read-only `/workspace` bind mount
- only a `noexec,nosuid,nodev` tmpfs at `/tmp` for writable runtime state
- UID/GID `65534:65534`
- all Linux capabilities dropped and `no-new-privileges=true`
- image health checks disabled and images declaring writable volumes rejected
- no Docker socket mount, host PID namespace, host network, or forwarded host
  environment/secrets
- no host-execution fallback

Bytes observed before the hard combined ceiling are hashed and byte-counted,
while only bounded prefixes are retained. The runner stops reading and kills the
Docker client as soon as a byte would cross that ceiling, then force-removes the
named container. It uses the `output_limit_exceeded` outcome only when cleanup
is confirmed. Captured prefixes are returned by
`execution_status(include_output=true)` only to an authenticated caller;
metadata and hashes are available without the prefixes.

## Operator configuration

Provision and audit the runner image outside this feature. It must contain a
Linux Python runtime, pytest, and the dependencies needed by the fixed display
tests. Record and configure the immutable repository digest, not a mutable tag.
The runtime never pulls or builds it.

Configure these environment variables for the Anima service:

```text
ANIMA_SELF_ITERATION_RUNNER_IMAGE=registry.example/anima-runner@sha256:<64 lowercase hex>
ANIMA_SELF_ITERATION_DOCKER_SOCKET=/var/run/docker.sock
ANIMA_SELF_ITERATION_DOCKER_BINARY=/usr/bin/docker
ANIMA_SELF_ITERATION_RUNNER_SIGNER_ID=anima-isolated-runner
```

`ANIMA_SELF_ITERATION_DOCKER_BINARY` is optional, but when present it must be an
absolute executable path. The socket may also use an absolute `unix://` URI.
TCP Docker endpoints are rejected.

The approver and result signer use the existing
`ANIMA_SELF_ITERATION_VERIFIER_KEYS` JSON registry. The result signer needs an
active 32–128-byte base64url-encoded key and must be distinct from the proposer,
active verifier(s), and approver. For example, the registry shape is:

```json
{
  "authenticated-approver-id": {
    "active_key_id": "approval-2026-08",
    "keys": {"approval-2026-08": "<base64url secret>"}
  },
  "anima-isolated-runner": {
    "active_key_id": "result-2026-08",
    "keys": {"result-2026-08": "<different base64url secret>"}
  }
}
```

Keep the registry in the service's protected environment file. It is never
mounted into the container or included in execution output. HMAC provides
server-verifiable integrity and principal separation within this deployment;
it does not provide public-key non-repudiation. A future remote/multi-operator
deployment should replace this registry boundary with hardware-backed or
public-key signatures before treating approvals as evidence outside the host.
When rotating keys, retain referenced inactive keys while their ledger and
artifact records still need to be audited.

The optional real-container test is disabled by default. On a prepared host,
set `ANIMA_SELF_ITERATION_RUN_DOCKER_TESTS=1` along with the runner variables,
then run:

```text
uv run pytest -q tests/test_self_iteration_execution.py
```

The optional test confirms that the configured image can run pytest while the
workspace is unwritable, a host canary secret is absent, and outbound network
connection attempts fail.

## Deliberate non-capabilities

A passing signed result is only `eligible_for_external_review`. Neither the
execution approval nor its result grants application authority. Phase 5 may
consume that result only after a new distinct review, and may create one
dedicated local branch; it still cannot write the live worktree, push, merge,
restart the service, or deploy.

Docker and the configured runner image remain trusted computing base. Anyone
with control of the Docker daemon is effectively a host administrator, and an
image can contain unexpected code even when its digest is stable. Operators
must therefore restrict socket access, review image provenance, rotate signing
keys, and treat changes to the image digest or execution profile as security
reviews rather than routine candidate iteration.
