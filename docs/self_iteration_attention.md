# Self-iteration attention projection

The attention projection makes the bounded self-iteration state visible without
granting any new authority. It is a read-only view derived from the signed
review artifacts, integrity-checked proposal ledger, and reconciled patch,
execution, application, and canary artifacts. Proposal source labels and
evidence remain caller claims until an independent verification event upgrades
their policy weight; the projection preserves that distinction rather than
turning receipt provenance into claim truth.

## Agent surface

`self_iteration(action="attention")` returns stable attention records with:

- proposal and candidate identifiers;
- the current stage and state;
- a bounded priority and factual summary;
- the distinct role required for the next review;
- a read-only status query; and
- compact claim provenance (caller-claim status, request authentication, and
  independent-verification status); and
- a stable attention identifier suitable for downstream de-duplication.

`next_steps` folds active records into its normal priority ordering. Default
`get_lumen_context` calls also include the compact attention projection, so an
agent following the usual wake-up flow can discover pending reviews without
already knowing a proposal identifier.

Terminal measured outcomes remain in the projection as inactive notification
records. They can be delivered once by downstream observers, but they do not
remain as agent next steps.

## Priority semantics

- `critical`: indeterminate one-use claims, unledgered signed results,
  application-ref integrity failure, rollback failure, or reconciliation
  failure. Operator recovery is required and automatic retry remains forbidden.
- `high`: an independent signed review or human merge decision is ready.
- `medium`: bounded construction/evaluation work, an expired unclaimed review,
  or a rejected candidate needs inspection.
- `low`: terminal measured outcome notification only.

## Notification boundary

The projection contains no patch body, signature, signing input, arbitrary
command, or approval-consuming operation. Its `status_query` is read-only.
Every record states:

```text
acknowledgement_is_approval=false
authority_granted=false
```

A Discord bridge or other observer may poll the projection and acknowledge
delivery. Such acknowledgement never satisfies the distinct authenticated
signature required by verification, execution, application, or canary review.
The local integrity-checked ledger and reconciled signed review artifacts remain
the source of state. Discord, `next_steps`, and context responses are attention
surfaces only. The projection explicitly reports that request provenance does
not verify claim truth.
