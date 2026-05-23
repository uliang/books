# Period close ↔ clearance contract

Clearance (Bank Reconciliation, the core domain) and period close (Ledger) are
**orthogonal axes**. Conflating them is unworkable because bank statements lag
reality.

- **Soft close never blocks on uncleared items.** A completed month locks even
  with uncleared bank postings; they **carry forward as reconciling items**,
  classified as *timing difference* (benign, expected to clear) or *stale
  exception* (uncleared beyond an **owner-configurable threshold** — the real
  control signal). Reconciliation ages and escalates these across the boundary.
- **Clearance-state mutation is exempt from the period lock.** Matching an
  April statement line to a March posting flips the orthogonal cleared flag; it
  does not alter entry economics (amount/account/date), so it is permitted on a
  soft-closed month. Without this exemption reconciliation would stop working
  the moment a month closes.
- **Annual hard close blocks** until every uncleared item is either classified
  as a legitimate year-end reconciling item (Dec deposit clearing in Jan) or
  adjudicated via the guided-journal path (e.g. reverse a phantom payment,
  invoice back to unpaid; or write off). No silent stale uncleared item is
  frozen into an immutable fiscal year.

This is a core-domain contract: it defines how the control (Reconciliation)
and the system-of-record (Ledger) interact across time boundaries.

## Amendment (2026-05-23): full reconciliation gates the hard close

The "timing difference carries across the boundary and does not block" provision
is removed. A late bank statement shares its transaction's date, so it reconciles
the original period once it arrives — you wait for it, reconcile, then close. The
annual hard close therefore requires **full** reconciliation: every bank posting
must be matched to a statement or written off; *any* uncleared item blocks,
regardless of age. Clearance remains exempt from the *soft* lock but is
**forbidden under hard** (a hard-closed period is settled — `confirm_match`
refuses it). The timing/stale classification survives only as mid-year reporting
triage, no longer as a gate.
