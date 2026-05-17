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
