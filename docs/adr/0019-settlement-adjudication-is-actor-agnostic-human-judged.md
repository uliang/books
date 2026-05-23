# Settlement adjudication is human-judged but actor-agnostic; the explicit outcome is always supplied

A foreign-currency invoice that banks fewer MYR than its carrying value is
**ambiguous** — adverse FX or underpayment — and is never auto-resolved
(CONTEXT, ADR-0005). The system surfaces both numbers (the `SettlementPicture`)
and a human decides *settled in full* (recognize a realized FX loss) or *still
owes* (AR stays open). Exposing this on an LLM-driven MCP surface
(`adjudicate_settlement`) raises the same question ADR-0015 flagged for
`confirm_match`: who is allowed to assert the judgment?

The contract is **actor-agnostic**, exactly like the explicit-pair confirm:

- `mark_paid(...)` — read what banked vs what was carried; returns the status
  (`paid` or `awaiting_adjudication`). No judgment, no FX recognition.
- `adjudicate_settlement(invoiceRef, outcome, on)` — the **only** call that
  resolves the ambiguity. `outcome ∈ {settled_in_full, still_owes}` is always
  **supplied explicitly** by the caller. The system never infers it from the
  shortfall, for either interface. `settled_in_full` recognizes the realized FX
  loss via the guided-journal path (ADR-0006); `still_owes` leaves AR open.

The decision may be **LLM-asserted on the owner's behalf** — provenance is
preserved either way and the deliberation, not the actor identity, is the
control. What is architecturally forbidden is the *system* (or the adapter)
auto-choosing the outcome from the numbers: that would collapse the
human-adjudication boundary the core domain exists to protect, the same failure
ADR-0015 rejects for batch auto-confirm.

Considered and rejected: an `auto_adjudicate()` / threshold rule that treats a
small shortfall as FX and a large one as underpayment. Convenient, but it
guesses the exact thing CONTEXT says never to guess. Accepted cost: every
foreign shortfall requires an explicit outcome — acceptable for a single owner,
where that explicit call *is* the judgment being recorded.
