# On-demand computed reporting; no materialized read model in v1

Reporting computes the tie-out (invariants 3 & 4), AR control (invariant 2),
and the reconciliation report as **queries/joins over the owning contexts'
tables at request time** (Reporting is the sole sanctioned cross-table reader,
ADR-0013). No stored projection, no event-driven denormalization, no rebuild
machinery. Reports are consistent with source by construction.

Considered and rejected: a materialized read model maintained by subscribing
to events. It earns its cost at scale, with expensive aggregations, or under
read/write asymmetry — none of which apply to a single-owner ledger (hundreds
to thousands of postings/year, where on-demand joins are trivially fast and
never stale). Worse, after a guided-journal phantom-payment reversal (tracer
increment 1) a missed or buggy projection handler would yield a **wrong but
confident** reconciliation report — the single worst failure mode for a
control whose entire job is to be trusted. Recompute-on-demand is also the
most faithful expression of the "compute and display, never assume" invariant
doctrine. If one specific report ever gets slow, materialize that one behind
the same query API without touching callers (cf. ADR-0011 deferral logic).
