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

## Amendment (2026-05-23): the soft/hard distinction is enforced

Originally `kind` was descriptive only — soft and hard locks blocked postings
identically. The distinction is now realized as a period state machine
(`general_ledger/period_lifecycle.py`): **soft** permits guarded guided-journal
corrections (with a reason, the channel reconciliation uses to fix a discovered
error) and bank reconciliation; **hard** permits nothing — the year is immutable.
The annual hard close upgrades any soft month to hard and may sweep up
never-soft-closed months directly (monthly soft-close is a convenience, not a
required gate).
