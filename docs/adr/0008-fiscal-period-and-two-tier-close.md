# Fiscal period and two-tier close

The business is a **sole proprietorship**. Malaysian individuals are assessed
on a calendar-year basis, so the **fiscal year is fixed to Jan–Dec** (single
configurable setting, defaulting to calendar) and year-end profit closes to
**Owner's Equity** — consistent with the owner-draw/capital model in ADR-0006.
Sub-period granularity is the **month**.

"Closing accounts" (original requirement) is split into two distinct
operations:

- **Monthly soft close** — locks a completed month against casual edits;
  corrections still possible *only* via the guided-journal path with a reason.
  No closing entries posted.
- **Annual hard close** — posts closing entries (net P&L → Owner's Equity) via
  the guided-journal path, then the fiscal year becomes immutable.

Considered and rejected: a single annual close. The soft monthly lock is what
makes month-by-month reporting trustworthy without prematurely posting
closing entries. Becoming a Sdn Bhd later would reopen this (free FYE choice,
Retained Earnings instead of Owner's Equity).
