# Reviewed self-iteration application

Phase 5 turns one passing, signed Phase 4 execution into a reviewable Git
commit without changing the checkout that runs Anima. "Application" means one
new local branch under `refs/heads/anima/self-iteration/`; it does not mean
activation, deployment, or permission to affect the live creature.

## Review and application flow

1. `prepare_application` revalidates the proposal, active verification,
   quarantined candidate, signed passing execution, clean committed source,
   candidate-applied tree digest, and absent server-derived target ref.
2. The authenticated application reviewer must differ from the proposer, every
   active verifier, the execution approver, and the execution result signer.
3. The server returns a canonical ten-minute plan. It binds all prior digests,
   the exact parent revision, target ref, Git backend identity, deterministic
   commit policy, reviewer key, and a separate application-result signer.
4. The same reviewer signs those exact bytes and calls `apply_candidate`.
5. After checking the signature and every current binding, the server persists
   a one-use application claim. A crash after this point is indeterminate and
   cannot be retried automatically.
6. Git plumbing creates candidate blobs, a tree, a commit, and the dedicated
   ref. A dedicated service key signs the complete result before the compact
   ledger event is appended.
7. `application_status` reconciles the approval, claim, signed artifact,
   ledger event, and actual ref/tree/parent relationship.

## Git containment boundary

The writer uses an isolated temporary `GIT_INDEX_FILE` and only these classes
of plumbing operations: `read-tree`, `hash-object`, `update-index`,
`write-tree`, `commit-tree`, and an atomic create-only `update-ref`. It also
uses read-only inspection commands before and after the write.

The contract requires:

- exact, clean `HEAD` matching the signed parent revision;
- one deterministic target ref derived from the candidate ID;
- regular tracked target files only, with existing executable mode preserved;
- hooks disabled and commit signing disabled for this contained operation;
- no checkout, reset, merge, rebase, worktree write, or candidate execution;
- no push, fetch, network operation, restart, service control, or deployment;
- `HEAD` and the worktree unchanged after the ref is created.

The immutable Git object database and the dedicated ref are the only repository
state this phase may change. If the branch already exists, application fails
closed. Ref creation uses an all-zero expected old object ID, so a concurrent
creator cannot be overwritten.

## Operator configuration

Set a dedicated service-signer identity:

```text
ANIMA_SELF_ITERATION_APPLIER_SIGNER_ID=anima-application-writer
```

That identity and each eligible reviewer must have keys in
`ANIMA_SELF_ITERATION_VERIFIER_KEYS`. The application signer must differ from
every prior participant and the application reviewer. An optional
`ANIMA_SELF_ITERATION_GIT_BINARY` may pin Git to an absolute executable path;
otherwise the server resolves `git` from its restricted command path.

HMAC signatures provide server-verifiable integrity and separation among
configured principals, not public-key non-repudiation. The host, Git object
database, key registry, and Python process remain trusted computing base.

## Failure and recovery states

`application_status` reports `awaiting_signature`, `expired_unclaimed`,
`claimed_result_indeterminate`, `signed_result_unledgered`, `recorded`, or
`ref_integrity_failed`. It never recreates or repairs a ref. Operators must
inspect an indeterminate or integrity-failed application and deliberately
create a new candidate/review path if recovery is warranted.

Even a fully recorded result is only `eligible_for_canary_review`. Phase 6 may
submit it to a separately configured transient-canary supervisor, but the
baseline must be restored before a healthy result becomes eligible for human
merge review. Application always records `eligible_for_live_activation=false`,
`pushed=false`, `merged=false`, `deployed=false`, and
`authority_granted=false`.
