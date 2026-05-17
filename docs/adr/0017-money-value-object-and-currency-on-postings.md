# Money value object; functional-for-balance, transaction-as-provenance

**`Money`** is a value object `(integer minor units, Currency)`, immutable. No
floats. Same-currency arithmetic only; cross-currency conversion happens *only*
through an explicit `Rate`, producing a new `Money` that carries that rate as
provenance. No implicit conversion anywhere.

**Ledger postings balance in functional MYR.** Invariant 1 (Σ debits = Σ
credits) is always evaluated in MYR; a journal entry never mixes currencies in
its balance check.

**A posting may carry an optional `originalAmount` (transaction-currency
`Money`) + the booking rate**, as provenance only. It never enters the balance
check; it exists so realized FX (ADR-0005) can be computed at settlement and so
the owner can be shown *both numbers* to adjudicate "settled in full (FX loss)"
vs "still owes."

Considered and rejected: MYR-only `Decimal` posting amounts with no
transaction-currency original retained. Simpler for the MYR tracer thread, but
when an SGD invoice settles for fewer MYR than booked (ADR-0005, the CONTEXT
example dialogue) the system structurally *cannot* present both numbers — the
human-adjudication contract breaks — and `Decimal` invites unquantized drift.
Retrofitting currency onto a MYR-only store after FX arrives is the textbook
"next engineer fixes it wrong" trap (cf. ADR-0007). Only this model satisfies
invariant 1 and ADR-0005 simultaneously. The guided-journal path (used by
increments 1/4/5) remains a thickening concern, not thread-1 architecture.
