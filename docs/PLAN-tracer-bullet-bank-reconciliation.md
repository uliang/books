# Tracer-bullet plan — Bank Reconciliation (core domain)

> Companion to `CONTEXT.md` and `docs/adr/0002`, `0004`, `0005`, `0009`.
> This plan is **step 1**. Interface/architecture design (step 2) is built
> *around* the acceptance test below, not before it.

## Why a tracer bullet here

Bank Reconciliation is the core domain (ADR-0002): it is where the system's
value (trustworthy books) and its integration risk (Invoicing → Ledger →
Reconciliation → Reporting) both concentrate. A horizontal-layer build would
finish the Ledger, then Invoicing, then Reconciliation — and only discover the
seam mismatches last. The tracer drives **one scenario through every seam
first**, production-grade but thin, then thickens.

The bullet has *hit* when one acceptance test is green end-to-end. Everything
after that reuses the same spine.

## The first thread (the thinnest end-to-end slice)

One MYR invoice, paid, banked, imported, matched, cleared, tied out, reported.
Crosses every non-generic context plus Party-by-id. Deliberately the maximum
integration surface in the minimum scenario.

**Held thin on purpose** (each is a later increment, not a gap):
- MYR only — no transaction currency, no FX.
- Exactly one statement line, one posting, exact amount + date.
- Happy path only — no unmatched line, no stale exception.
- No period-close interaction.
- No guided-journal path (no statement-only items / bank fees).
- Match is *proposed* on exact `(account, amount, date-window)` and
  *human-confirmed* — assisted, not autonomous (per CONTEXT out-of-v1).

## Acceptance test (the executable definition of "bullet hit")

**Given**
- Party `Acme` (customer role).
- Chart of Accounts incl. `Bank` (asset), `Accounts Receivable` (asset,
  control), `Revenue` (income).
- Invoice #1 → Acme, MYR 1,000, issued 2026-01-10.
  Ledger (event-fed): `Dr AR 1,000 / Cr Revenue 1,000`, AR line dim `Party=Acme`.
- Invoice #1 marked **Paid** 2026-01-15.
  Ledger: `Dr Bank 1,000 / Cr AR 1,000` (`Party=Acme`). Bank posting **uncleared**.

**When**
- January statement imported: opening 0; one line `2026-01-15 +1,000 "ACME
  TRANSFER"`; closing 1,000.
- System **proposes** matching that line to the uncleared Bank posting.
- Owner **confirms** the match.

**Then**
- Bank posting clearance flips `uncleared → cleared`, carrying the statement
  line reference + match timestamp.
- Confirmed cash = Σ cleared bank postings = 1,000 — **invariant 3**.
- Reconciled bank balance = statement closing = 1,000; zero unexplained lines;
  zero reconciling items — **invariant 4**.
- January reconciliation report: statement 1,000 / ledger bank 1,000 / cleared
  1,000 / difference 0 / no exceptions.

Green ⇒ proven in one shot: Invoicing→Ledger event translation, bank-posting
representation, clearance-state ownership, the match operation, cash invariants
3 & 4, and the Reporting projection.

## Thickening increments (each = one new test, same spine, no rework)

Ordered by core-domain risk/value, not by ease:

1. **No-match + reconciling-item classification.** A statement line with no
   posting and/or an uncleared posting with no line. Unmatched line stays
   *explicitly unexplained* (guided-journal candidate, e.g. bank fee);
   uncleared posting becomes a reconciling item classified *timing difference*
   vs *stale exception* against the owner-configurable threshold. Proves the
   "raise discrepancy for review" responsibility — the real core; the happy
   path barely is.
2. **Soft-close carry-forward (ADR-0009).** A January posting matched by a
   February statement line on a *soft-closed* January. Proves clearance
   mutation is exempt from the period lock and items age across the boundary —
   the highest-subtlety contract in the domain.
3. **SGD/FX adjudication (ADR-0005).** SGD 1,000 invoice booked at rate → AR
   MYR 3,200; statement shows MYR 3,180. System guesses nothing: surfaces both
   numbers; owner adjudicates *settled in full (realized FX loss 20)* vs *still
   owes 20*; realized-FX posting via guided-journal path.
4. **Hard-close gate (ADR-0009).** Year-end blocked until every uncleared item
   is a classified year-end reconciling item or adjudicated. Proves the
   blocking contract + guided-journal closing path.

## What this plan forces step 2 (architecture) to decide

The tracer can't sidestep these; the architecture is designed to satisfy the
test above:

- **Clearance ownership seam** (the one genuine fork): does Bank
  Reconciliation *mutate a flag on the Ledger posting*, or keep its own match
  records referencing posting ids? CONTEXT says it "owns the posting's
  clearance state" — that constrains, but doesn't settle, the mechanism.
- **Invoicing→Ledger contract**: event names/payloads (`InvoiceIssued`,
  `PaymentRecorded`); in-process dispatch for v1.
- **Statement import adapter**: input format (CSV first) and the import boundary.
- **Reporting projection**: how the read model is built/rebuilt.
- **Persistence + per-context module layout** under `src/books/`.
- **Interfaces (MCP + web)**: which operations the tracer exposes — import
  statement, propose/confirm match, view reconciliation report.
