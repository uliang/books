# Every journal entry carries provenance

No journal entry posts anonymously. Each entry records a **provenance
reference** discriminating its origin:

- **Event-fed** — source event kind + identifier (e.g. `PaymentRecorded`,
  Invoice #1). The Ledger's event handler already holds this at the
  Invoicing→Ledger seam.
- **Guided-journal** — the mandated human reason (ADR-0006).

Consequences:

- Reconciliation can trace an uncleared bank posting **back to the invoice
  that caused it** — required by ADR-0009's phantom-payment remedy ("reverse
  the payment, invoice back to unpaid"), which is tracer increment 1, not a
  future nicety.
- "No silent posting" is a structural invariant, consistent with the
  trustworthy-books value proposition.

Considered and rejected: provenance only on guided-journal entries, event-fed
postings anonymous. Cheaper, but retrofitting a provenance chain onto an
already-anonymous posting store is the classic "next engineer fixes it wrong"
trap (cf. ADR-0007), and it breaks the core domain's after-the-fact audit
chain.
