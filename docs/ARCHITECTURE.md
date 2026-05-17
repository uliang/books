# Architecture — built around the tracer acceptance test

> Companion to `docs/PLAN-tracer-bullet-bank-reconciliation.md`. Every decision
> below is an accepted ADR (0010–0018). This document shows the spine as a
> whole and maps it onto the thread-1 acceptance test, seam by seam.

## The spine

| Concern | Decision | ADR |
|---|---|---|
| Clearance ownership | Reconciliation holds match records; "cleared" is derived; Ledger posting immutable | 0010 |
| Topology + integration | Modular monolith; in-process synchronous domain-event dispatch | 0011 |
| Provenance | Every journal entry records what caused it | 0012 |
| Persistence + layout | One SQLite/SQLAlchemy DB; per-module table ownership; `import-linter`-enforced boundaries; Reporting sole cross-table reader | 0013 |
| Core aggregates | `BankStatement` (immutable) + `Match` (small, cross-period); no `Reconciliation` root; tie-out is a projection | 0014 |
| Interface contract | Side-effect-free `propose`; explicit-pair `confirm_match` is the only reconciliation write; no batch/auto-confirm | 0015 |
| Reporting | On-demand computed; no materialized read model | 0016 |
| Money | `Money` VO; postings balance in functional MYR; transaction currency rides as provenance | 0017 |
| Statement import | ACL with retained, hashed raw evidence + parser port (one CSV adapter) | 0018 |

## The acceptance test, mapped to seams

Test from the tracer plan, annotated with the architecture each step exercises:

1. **Invoice #1 issued (MYR 1,000)** → Invoicing publishes `InvoiceIssued`
   (0011) → Ledger handler posts `Dr AR / Cr Revenue` in functional MYR `Money`
   (0017), entry tagged provenance `InvoiceIssued#1` (0012), AR line dim
   `Party=Acme` (CONTEXT). One transaction (0013).
2. **Invoice #1 marked Paid** → `PaymentRecorded` (0011) → Ledger posts
   `Dr Bank / Cr AR`, provenance `PaymentRecorded#1` (0012). Bank posting
   uncleared = simply *no `Match` references it yet* (0010, 0014).
3. **January statement imported** → import ACL retains + hashes the raw file
   (0018), CSV adapter → canonical `BankStatement`, footing checked at the
   boundary (0014/0018). Hash is the idempotency key (0018).
4. **`propose_matches(Bank, Jan)`** → read-only (0015), Reporting-style join
   over Ledger bank postings ⋈ statement lines (0013/0016), exact
   `(account, amount, date-window)` candidate.
5. **Owner `confirm_match(line, posting)`** → the sole reconciliation write
   (0015); creates one `Match`, uniqueness enforced (0014). Nothing in the
   Ledger mutates (0010).
6. **Tie-out / report** → computed on demand (0016): confirmed cash = Σ
   postings with a `Match` = 1,000 (invariant 3); statement closing 1,000 =
   reconciled balance, zero reconciling items (invariant 4). The left-join
   residue (none here) is what later becomes reconciling items (0014).

Every seam in the spine is hit by this one MYR scenario. That is the tracer.

## Genuinely deferred (to thickening increments, not design forks)

These are decided *when their increment is built*, against this fixed spine —
they do not reopen the architecture:

- **Guided-journal path** shape (increments 1, 4, 5). Flagged thickening, not
  thread-1.
- **Reconciling-item aging / clock injection** (increment 1) — inject a clock;
  trivial against 0014's left-join residue.
- **Soft/hard-close enforcement points** (increments 3, 4) — orthogonal by
  0010/0014 construction; no spine change.
- **FX adjudication flow** (increment 4) — data already preserved by 0017;
  only the adjudication use-case is new.
- **Composition-root wiring mechanism** — manual wiring in `books:main`;
  implementation detail, not a fork at this scale.
