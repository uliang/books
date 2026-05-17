# Reconciliation owns clearance; the Ledger posting stays immutable

Bank Reconciliation (the core domain) owns clearance state by **holding its own
match records** `(postingId, statementLineId, matchedAt, ...)`, not by mutating
a `cleared` flag on the Ledger posting.

- A bank posting is **cleared iff a match record references it**. "Cleared" is
  *derived*, never stored on the posting.
- Invariant 3 (confirmed cash = Σ cleared bank postings) is a **join** between
  Ledger bank postings and Reconciliation match records, computed by Reporting.
- Reconciling items (ADR-0009) are the **left-join residue**: bank postings
  with no match record, aged against the owner-configurable threshold.

Considered and rejected: a `cleared` column on the Ledger posting. Cheaper
reads, but it forces a permanent carve-out in the Ledger's period lock so that
clearing an April statement against a soft-closed March posting can mutate a
locked row (ADR-0009). With match records, the Ledger posting is genuinely
immutable, the period lock needs no exception, and the close↔clearance
orthogonality of ADR-0009 becomes **structurally true** rather than enforced by
a special case. The core domain owns its own state instead of reaching into a
Supporting context. Accepted cost: clearance and reconciled-balance are joins,
not column reads — but that join belongs in Reporting, which already exists to
compute, not assume (ADR-0007, invariants).
