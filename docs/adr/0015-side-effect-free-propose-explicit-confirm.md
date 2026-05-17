# Side-effect-free propose; explicit-pair confirm is the sole reconciliation write

Interfaces (web, MCP) are thin adapters over each context's application API
(ADR-0013); one composition root wires infrastructure and exposes both. The
reconciliation match interaction has a fixed contract that makes "assists,
never autonomous" (CONTEXT) and "audits, doesn't gate, never guesses"
(ADR-0004) **architectural properties of the port**, not UI conventions:

- `propose_matches(account, period)` — **read-only**, returns ranked
  candidates (tracer: exact `(account, amount, date-window)`). No state change.
- `confirm_match(statementLineRef, ledgerPostingRef)` — the **only**
  reconciliation write. Explicit pair required; rejects if either side is
  already matched (ADR-0014 uniqueness); idempotent on identical re-submit.
  **No "confirm all", no auto-confirm — for both interfaces.**
- `import_statement(...)` — returns the statement + footing result; rejects a
  non-footing statement (ADR-0014).

Considered and rejected: a fused / batch-confirmable `reconcile()` call. Fewer
round-trips, but an LLM-driven MCP caller could rubber-stamp a phantom-payment
match in one shot, destroying the very control the core domain exists to
provide. Enforcing the deliberate per-pair confirm at the application API is
the only way the human-adjudication boundary survives an agentic interface.
Accepted cost: more round-trips, no bulk confirm in v1 — acceptable for a
single owner, where the deliberation *is* the control.
