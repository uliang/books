# Period-Close State Machine — Design

**Date:** 2026-05-23
**Status:** Approved (brainstorming) → ready for plan
**Amends:** ADR-0008 (fiscal period & two-tier close), ADR-0009 (close ↔ clearance
contract). No new ADR — this *realizes* their stated intent.
**Follows:** the period-close MCP rail (PR #3, merged `06fb2c9`), whose live trial
surfaced the issue.

## Goal

Give the period-close `kind` ("soft"/"hard") real behaviour by modelling a period's
close status as an explicit state machine — so soft and hard close gate *different*
actions, as ADR-0008 always intended but the code never enforced.

## Background — why now

Trying the merged MCP rail live surfaced two defects, one visible and one latent:

1. **`kind` is behaviourally inert.** The lock guard `is_period_locked`
   (`repository.py`) — which `append_entry` consults — checks only row *existence*,
   never `kind`. So a soft lock and a hard lock block postings *identically*. The
   `PeriodLockView` docstring says it outright: "a read view, no behaviour." After
   `hard_close(2026)`, January (already soft-closed) stayed `kind="soft"` in
   `closings://`, because `lock_period` is idempotent skip-if-exists and never
   upgrades — harmless only *because* `kind` means nothing.

2. **Latent crash.** `hard_close` posts the year-end P&L sweep dated 31 Dec, then
   locks the months. If December was *already* soft-closed, the current blanket
   guard rejects the sweep (`period 2026-12 is closed`). A disciplined owner who
   soft-closes the final month before the annual close cannot close the year. No
   test hit this because nobody soft-closes the last month first.

ADR-0008 intends soft = "locks against casual edits; corrections still possible
*only via the guided-journal path, with a reason*" and hard = "the fiscal year
becomes *immutable*." That difference was never implemented. This design implements
it, and the distinguishing axis — established with the owner — is **bank
reconciliation**: a soft-closed period still accepts the late bank statement that
clears its postings; a hard-closed period is fully reconciled and accepts nothing.

## Domain model — the lifecycle

A period (`YYYY-MM`) has one of three close states:

```
        soft_close (month)            hard_close (year)
 OPEN ────────────────────▶ SOFT ───────────────────────▶ HARD (terminal)
 (no row)                 (kind=soft)                    (kind=hard)
   │                                                        ▲
   └──────────────── hard_close (year), the shortcut ───────┘
```

- **OPEN → SOFT** via `soft_close(period)`: owner-asserted ("done entering this
  month"); no precondition; never blocks (ADR-0009).
- **SOFT → HARD** and **OPEN → HARD** via the annual `hard_close(year)`: drives every
  month of the year to HARD. The `OPEN → HARD` shortcut is allowed — months never
  soft-closed are swept up directly (monthly soft-close is a convenience, not a
  required gate).
- **HARD is terminal.** No reopen. The only way to change a soft-closed month is a
  guarded guided-journal correction (below); a hard-closed period changes never.

"Reconciled" is **not** a fourth state. It is a *computed guard* on the transition
to HARD, derived from the clearance projection (ADR-0014), not stored.

## The policy — a pure module (the heart)

New `src/books/general_ledger/period_lifecycle.py`, no I/O, the single authoritative
home for the rules:

- `class PeriodState(Enum)`: `OPEN`, `SOFT`, `HARD`.
- `may_post(state: PeriodState, source_kind: str) -> bool`
  - `OPEN`: `True` for any `source_kind`.
  - `SOFT`: `True` iff `source_kind == "GuidedJournal"` (the guarded correction
    channel, ADR-0006); `False` for every event source_kind (InvoiceIssued,
    PaymentRecorded, SettlementAdjudicated, OwnerPaidExpenseRecorded, ContractorPaid,
    OwnerReimbursed).
  - `HARD`: `False` always.
- `may_reconcile(state: PeriodState) -> bool`: `True` for `OPEN`/`SOFT`, `False` for
  `HARD`.
- Transition helpers (raise on illegal transitions):
  - `on_soft_close(state)`: `OPEN`/`SOFT` → `SOFT`; `HARD` → error.
  - `on_hard_close(state)`: `OPEN`/`SOFT` → `HARD`; `HARD` → error.

### Gating matrix (the contract this module encodes)

| Action | OPEN | SOFT | HARD |
|---|---|---|---|
| Casual economic entry (event-driven posting) | ✅ | ❌ | ❌ |
| Guided-journal correction (guarded, with a reason) | ✅ | ✅ | ❌ |
| Reconciliation / clearance update (`confirm_match`) | ✅ | ✅ | ❌ |

## Who consults the policy

- **`append_entry`** (`general_ledger/persistence/repository.py`): replace the boolean
  `is_period_locked` guard with `may_post(state, source_kind)`, where `state` is
  derived from the `_PeriodClose` row for `period_of(on)`. On `False`, raise a
  `ValueError` naming the period and state. This is what lets a guided-journal
  correction into a soft month while keeping invoices out, and freezes hard months
  entirely.
- **`hard_close(year)`** (`general_ledger/service.py`), in order:
  1. Reject if the year is already hard-closed (prevents a double P&L sweep).
  2. **Reconciliation gate** (below): block if any bank posting in the year is
     uncleared.
  3. Post the net-P&L → Owner's Equity sweep (a `GuidedJournal` dated 31 Dec) — now
     permitted even if December is SOFT, because `may_post(SOFT, "GuidedJournal")` is
     `True`. (Fixes the latent crash.)
  4. Transition all twelve months to HARD via an upgrade-capable `lock_period`
     (insert HARD, or update SOFT → HARD). (Fixes January-stays-soft.)
- **`confirm_match(line_ref, posting_ref)`** (`bank_reconciliation/service.py`, the
  sole clearance write, ADR-0015): consult an injected
  `posting_is_reconcilable(posting_ref) -> bool` reader; if `False`, raise. The reader
  is a plain boolean callable (not the `PeriodState` enum) so Reconciliation stays
  ignorant of the Ledger's state vocabulary. The read-only `propose_matches` needs no
  guard. `import_statement` is out of scope for the guard (it stores an artifact; it
  changes no clearance state until a match is confirmed).

## The strengthened hard-close gate

The gate moves from "no *stale* exceptions" to **"no *uncleared* bank postings at
all"**: every bank posting dated in the year must be matched-to-statement
(`matched_posting_refs`) *or* written-off (`written_off_refs`). Consequences:

- `reporting.year_end_blockers(year)` changes from returning the *stale subset* to
  returning *all uncleared* postings (a rename to reflect this, e.g.
  `unreconciled_at_year_end`, is in scope). The hard-close gate and the MCP
  `hard_close` tool / `year-end-blockers://` resource all key off this — their
  behaviour shifts to "any uncleared blocks," which is correct and consistent.
- `stale_after_days` stops being a *gate* parameter and becomes purely a *reporting*
  parameter.

### Classification: demoted, not deleted

The `timing_difference` / `stale_exception` labels survive **only** in
`reporting.reconciliation_report` as the owner's *mid-year triage* signal ("this
uncleared item is suspiciously old — likely a phantom, write it off now" vs "just
awaiting a statement"). They no longer feed any gate. There is no "timing difference
at the year boundary" anymore: by hard-close time the year is fully reconciled
(zero uncleared), so the label is meaningful only within the year. **Kept** (it
already exists, costs nothing, and gives early phantom warning).

## Cross-context wiring

At the composition root (`src/books/__init__.py`), inject
`posting_is_reconcilable` into `BankReconciliationService`, mirroring how
`year_end_blockers` is already injected *into* the Ledger today. The Ledger owns
period state and the posting→date→period mapping and returns a plain boolean;
Reconciliation asks. Synchronous, in-process, no duplicated state (ADR-0011). The
event-driven alternative (publish `PeriodHardClosed`, mirror state into
Reconciliation) is rejected as needless duplication for a single-process app.

## State representation / persistence

Keep the `_PeriodClose` table (`period` PK, `kind`). State derivation: no row →
`OPEN`; `kind="soft"` → `SOFT`; `kind="hard"` → `HARD`. `lock_period` becomes
transition-aware (insert, or upgrade SOFT → HARD via UPDATE), driven by the policy's
transition helpers. The merged `PeriodLockView` docstring ("a read view, no
behaviour") is corrected; `closings://` now reports the true post-close kinds (all
`hard` after a year close).

## Components / files

- **New:** `src/books/general_ledger/period_lifecycle.py` — pure policy (state, matrix,
  transitions).
- **Modify:** `general_ledger/persistence/repository.py` — `append_entry` gate via
  `may_post`; `lock_period` upgrade-capable; a `period_kind(period)` / state query.
- **Modify:** `general_ledger/service.py` — `hard_close` (already-closed check +
  strengthened gate + transitions); `soft_close` (reject on HARD); add
  `posting_is_reconcilable(posting_ref)` read (delegates to `may_reconcile` over the
  posting's period state); correct `PeriodLockView` docstring.
- **Modify:** `reporting/service.py` — `year_end_blockers` → all-uncleared (rename);
  `reconciliation_report` keeps the classification.
- **Modify:** `bank_reconciliation/service.py` — `confirm_match` consults injected
  `posting_is_reconcilable`, rejects when `False`.
- **Modify:** `src/books/__init__.py` — inject `posting_is_reconcilable` into Bank
  Reconciliation.
- **Modify (MCP ripple):** `interfaces/mcp/tools/closing.py`,
  `interfaces/mcp/resources/closing.py`, and `tests/test_mcp_period_close.py` — the
  `hard_close` tool / `year-end-blockers://` resource follow the new gate; existing
  tests updated.
- **Modify (ADRs):** `docs/adr/0008-*.md`, `docs/adr/0009-*.md`.

## Testing

- **Pure** `period_lifecycle` tests (no DB): the full `may_post` / `may_reconcile`
  matrix and every transition (legal + illegal).
- **Ledger:** `append_entry` rejects an event posting into SOFT, admits a
  `GuidedJournal` into SOFT, rejects everything into HARD; soft→hard upgrade leaves
  `closings://` all-`hard`.
- **Strengthened gate:** `hard_close` blocks on *any* uncleared posting (not just
  stale); passes once every posting is matched or written-off.
- **Double-sweep:** a second `hard_close(year)` is rejected, P&L not swept twice.
- **Regression (the motivating bug):** soft-close December, then `hard_close(year)`
  succeeds (sweep posts as a guided journal).
- **Cross-context:** `confirm_match` on a HARD-period posting is rejected; on a SOFT
  posting it succeeds.
- **MCP rail:** update `tests/test_mcp_period_close.py` for the all-uncleared gate.

## Build order

Ledger-first (lifecycle policy → `append_entry` gate → `hard_close` transitions +
strengthened gate → MCP ripple), then the cross-context reconciliation freeze
(`confirm_match` guard + composition-root wiring) as the last slice. One spec.

## Out of scope (YAGNI)

- Reopening a closed period (no Soft→Open or Hard→anything).
- Per-month *hard* close (hard remains annual per ADR-0008).
- Gating `import_statement` (only `confirm_match` mutates clearance).
- Configurable fiscal-year-end (ADR-0008 fixes Jan–Dec).
- A web UI for any of this.

## Decisions resolved during brainstorming

- Distinguishing axis is **reconciliation**, not economic-entry corrections in the
  abstract (corrections are the *mechanism*; reconciliation is the *trigger*).
- Hard close requires **full** reconciliation (any uncleared blocks); the
  timing-difference-carries-across-the-boundary idea from ADR-0009 is **removed**
  (the statement is merely late; it shares the transaction's date, so it reconciles —
  you wait, then close).
- Reconciliation-discovered economic corrections go in via the **guided journal**
  (option 2), not a reopen and not a current-period booking — a closed month must
  stay accurate, and a missing entry is an alarming, reason-bearing event.
- State graph is **Open→Soft→Hard with an Open→Hard shortcut**; no reopen; monthly
  soft-close optional.
- Classification (timing/stale) **kept** as mid-year reporting triage only.
