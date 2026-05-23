# Period-Close MCP Tracer — Design

**Date:** 2026-05-23
**Status:** Approved (brainstorming) → ready for plan
**Related:** ADR-0008 (fiscal period & two-tier close), ADR-0009 (close ↔ clearance
contract), ADR-0006 (guided journal), ADR-0019 (surface, don't auto-decide).
Parallels the buy-side expense rail and the sell-side invoicing rail (PR #2).

## Goal

Expose the already-built two-tier period close over MCP as thin adapters, so the
owner can soft-close a month, write off a phantom bank posting, and hard-close a
fiscal year through the agent. The domain (`LedgerService.soft_close` /
`write_off` / `hard_close`, `ReportingService.year_end_blockers`) is built and
tested but reachable from no interface today. One small domain read is added; no
other domain change.

## Architecture

Thin adapters over `App.ledger` and `App.reporting`, mirroring the existing
rails. Two new modules — `interfaces/mcp/tools/closing.py` and
`interfaces/mcp/resources/closing.py` — each registered in the existing single
wiring points (`tools/__init__.py`, `resources/__init__.py`). Dates cross the
wire as `YYYY-MM` (period keys) and `YYYY-MM-DD` (write-off date, parsed via
`forms.date_from`); years as plain ints.

No new event flows: `soft_close`, `write_off`, and `hard_close` are direct
ledger operations (the latter two post via the existing guided-journal path).
The blocker check delegates to Reporting, the sanctioned cross-context reader,
exactly as the domain's late-bound `year_end_blockers` gate already does.

## Components

### Tools — `interfaces/mcp/tools/closing.py`

- **`soft_close(period: str) -> dict`**
  Calls `ledger.soft_close(period)`. Returns `{"status": "soft_closed",
  "period": period}`. Idempotent; never blocks on uncleared items (ADR-0009).

- **`write_off(posting_ref: int, on: str) -> dict`**
  Calls `ledger.write_off(posting_ref, date_from(on))`. Returns
  `{"status": "written_off", "posting_ref": posting_ref}`. An unknown ref raises
  `LookupError` in the domain and surfaces as an MCP error result.

- **`hard_close(year: int) -> dict`**
  Reads `reporting.year_end_blockers(year)` first.
  - Blockers present → return
    `{"status": "blocked", "blockers": [{"ref", "amount_minor", "currency",
    "age_days"}, ...]}` — no exception. The agent narrates the blockers and
    guides the owner to `write_off` / adjudicate each (surface, don't
    auto-decide; ADR-0019 spirit).
  - Clear → `ledger.hard_close(year)`, return `{"status": "closed",
    "year": year}`.

  This pre-flight read derives the structured status rather than catching the
  domain `ValueError` — the same shape as `mark_paid` reading
  `settlement_picture` to decide `paid` vs `awaiting_adjudication`.

### Resources — `interfaces/mcp/resources/closing.py`

- **`closings://`** → `[{"period", "kind"}, ...]` from a new
  `ledger.locked_periods()`, ordered by period. "What's already closed" — lets
  the agent answer close-status questions and avoid blind re-closes.

- **`year-end-blockers://{year}`** → `[{"ref", "amount_minor", "currency",
  "age_days", "classification"}, ...]` from `reporting.year_end_blockers(int(
  year))`. Path params arrive as strings, so coerce `year` to int before lookup
  (same idiom as `invoices://{invoice_id}/settlement`). Pre-flight before a hard
  close.

### Domain read added — `general_ledger`

- `LedgerRepository.list_period_locks(session) -> list[tuple[str, str]]`
  An ordered `select(_PeriodClose.period, _PeriodClose.kind)` ordered by
  `period`.
- `LedgerService.locked_periods() -> list[PeriodLockView]` where `PeriodLockView`
  is a frozen slotted dataclass `{period: str, kind: str}`. Mirrors how
  `InvoiceView` / `list_invoices` was added for the invoice rail — a read view,
  no behaviour.

## Data Flow

- **Soft close:** tool → `ledger.soft_close(period)` → `repo.lock_period(period,
  kind="soft")`. Subsequent economic entries dated into that period are rejected
  by the existing `append_entry` lock guard.
- **Write-off:** tool → `ledger.write_off(ref, on)` → guided-journal Dr Write-off
  / Cr Bank; the posting leaves the uncleared set (`written_off_refs`), so it no
  longer blocks the hard close.
- **Hard close:** tool → `reporting.year_end_blockers(year)`; if empty,
  `ledger.hard_close(year)` sweeps net P&L → Owner's Equity via the guided
  journal and locks all 12 months (kind `hard`), after which the year is
  immutable.

## Error Handling

- Unknown `posting_ref` on write-off → `LookupError` → MCP error result.
- Blocked hard close → **structured** `{"status": "blocked", ...}`, never an
  error.
- Posting into a locked month → existing `ValueError` in `append_entry` (the
  invariant lives with the write that violates it); surfaces through the other
  rails' tools, not introduced here.

## Testing

TDD with the in-memory `mcp_client` helper, new `tests/test_mcp_period_close.py`,
following `test_mcp_invoice_fx.py` setup style (chart helper creating the
required account rows: Bank, Owner's Equity, Write-off, plus a P&L pair so the
hard close has a net to sweep).

1. **Soft close locks a month.** `soft_close("2026-03")` → `closings://` lists
   `{period: "2026-03", kind: "soft"}`; a later economic entry dated in March is
   rejected.
2. **Hard close happy path.** Clean books with a net P&L → `hard_close(2026)`
   returns `{"status": "closed"}`; Owner's Equity carries the swept net;
   `closings://` shows 12 `hard` periods for the year.
3. **Hard close blocked then resolved.** A stale uncleared bank posting present →
   first `hard_close(2026)` returns `{"status": "blocked"}` with the item; then
   `write_off` that posting; second `hard_close(2026)` returns
   `{"status": "closed"}`.
4. **Blockers resource.** `year-end-blockers://2026` reflects the stale item
   before write-off and is empty after.

## Out of Scope (YAGNI)

- Web UI for close (MCP-only tracer, as with the prior rails).
- Configurable fiscal-year-end — ADR-0008 fixes Jan–Dec for the sole prop.
- Reopening / unlocking a closed period.
- Soft-close period-format validation (the domain accepts the `YYYY-MM` string
  as-is; the tracer passes it through).
