# Signed transient canary evaluation

Phase 6 closes the autonomous evaluation loop without turning Anima into a
release manager. A separately reviewed Phase 5 branch may be activated only as
a transient canary by an external, locally configured supervisor. The
supervisor must measure the fixed health profile and restore the baseline even
when the candidate is healthy.

## Boundary

The Anima process has no shell, arbitrary-command, service-control, checkout,
push, merge, or deployment primitive. It communicates with one external
supervisor through an exact absolute Unix-socket path. TCP endpoints and socket
symlinks are rejected.

The fixed `lumen_transient_canary_v1` profile requires:

- a 120-second observation window;
- MCP health, broker-state freshness, and display-heartbeat checks;
- activation of the exact reviewed commit and target ref;
- restoration of the exact baseline revision before a healthy result may be
  eligible for merge review;
- no persistent candidate activation and no caller-supplied parameters.

The external supervisor remains trusted computing base. It owns activation,
health measurement, and rollback mechanics; this repository defines and
verifies only the narrow signed protocol.

## Review and execution flow

1. `prepare_canary` revalidates the signed application artifact, compact ledger
   event, dedicated Git ref, commit, tree, parent, proposal, verification, and
   passing execution chain.
2. A new authenticated canary reviewer must differ from every prior proposer,
   verifier, approver, reviewer, and service signer.
3. The reviewer signs a ten-minute plan binding the exact application result,
   supervisor identity, fixed profile, candidate commit, and baseline revision.
4. `run_canary` revalidates those bindings and persists a one-use claim before
   contacting the external supervisor.
5. The supervisor returns a complete result signed by its dedicated key. The
   artifact is stored before its compact ledger event is appended.
6. `canary_status` reconciles approval, claim, signed result, ledger event, and
   the still-intact Phase 5 candidate ref.

A crash or disconnect after the durable claim is
`claimed_result_indeterminate`. Anima never retries it: an operator must first
establish the actual live revision and baseline-restoration state.

## Result semantics

A `passed` result is valid only when all fixed health checks passed, activation
occurred, restoration was attempted, the baseline was restored, and the live
revision after evaluation equals the signed baseline revision. It recommends
`keep_candidate_for_merge_review`; it does not merge or activate anything.

Failures recommend `reject_candidate`. A missing restoration or
`rollback_failed` result recommends `operator_recovery_required` and is never
eligible for merge review. Every result records:

```text
persistent_activation_retained=false
eligible_for_live_activation=false
authority_granted=false
```

## Operator configuration

Configure the supervisor outside Anima:

```text
ANIMA_SELF_ITERATION_CANARY_SOCKET=/run/anima/canary-supervisor.sock
ANIMA_SELF_ITERATION_CANARY_SUPERVISOR_SIGNER_ID=anima-canary-supervisor
```

The reviewer and supervisor identities need distinct keys in
`ANIMA_SELF_ITERATION_VERIFIER_KEYS`. The socket owner must implement the exact
probe/evaluation JSON-lines protocol, reject arbitrary profiles or commands,
verify the review signature, activate only the bound commit, and enforce
baseline restoration independently of client disconnects.
