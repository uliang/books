# No Reconciliation aggregate; tie-out is a derived projection

The Bank Reconciliation core has exactly two transactional aggregates. There is
deliberately **no `Reconciliation` aggregate root**.

- **`BankStatement`** — immutable once imported. Invariant enforced at import:
  `opening + Σ lines = closing`. A statement that does not foot internally is
  rejected; this is the first line of defense.
- **`Match`** — small. `(statementLineRef, ledgerPostingRef, confirmedAt,
  provenance)`. Uniqueness invariants — a statement line matched at most once,
  a bank posting matched at most once — enforced by DB constraint plus the
  confirm-command guard. A `Match` may span periods (April line ↔ March
  posting) by construction.
- **Reconciliation tie-out** — statement closing vs Σ cleared postings,
  unexplained lines, reconciling items aged per the owner threshold — is
  **computed by Reporting** (invariants 3 & 4 as the read model, per
  ADR-0010). It is a view, not a root.

Considered and rejected: a `Reconciliation` aggregate owning `Match` entities
per (account, period). It forces an answer to "which period's aggregate
transactionally owns a cross-period match?" and a lock carve-out for the closed
period — the exact disease ADR-0010 rejected. Treating tie-out as a projection
keeps ADR-0009's close↔clearance orthogonality structurally true and matches
the "compute, never assume" invariant philosophy. Accepted cost: tie-out is
always a query, never a one-hop stored read (already true under ADR-0010).
