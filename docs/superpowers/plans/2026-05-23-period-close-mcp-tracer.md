# Period-Close MCP Tracer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the already-built two-tier period close (soft close, write-off, hard close) and its read surfaces over MCP as thin adapters.

**Architecture:** Two new MCP adapter modules (`tools/closing.py`, `resources/closing.py`) registered in the existing single wiring points, plus one small read added to the General Ledger (`LedgerService.locked_periods()`). All tools/resources delegate to `App.ledger` / `App.reporting`; no new domain behaviour, no event flows.

**Tech Stack:** Python 3.13, `uv`, FastMCP, SQLAlchemy, pytest. Run tests with `uv run pytest --timeout=60`, lint with `uv run ruff check src tests`, boundaries with `uv run lint-imports`.

**Spec:** `docs/superpowers/specs/2026-05-23-period-close-mcp-tracer-design.md`
**Domain reference (mirror its behaviour through MCP):** `tests/test_increment_4_hard_close_gate.py`
**Adapter references (copy these patterns):** `src/books/interfaces/mcp/tools/invoicing.py`, `src/books/interfaces/mcp/resources/invoicing.py`, `tests/test_mcp_errors.py`.

## Key domain facts (already built — do not reimplement)

- `LedgerService.soft_close(period: str)` — locks `YYYY-MM`; idempotent; never blocks.
- `LedgerService.write_off(posting_ref: int, on: date)` — guided-journal Dr Write-off / Cr Bank; unknown ref raises `LookupError`.
- `LedgerService.hard_close(year: int)` — raises `ValueError` if `year_end_blockers` non-empty; else sweeps net P&L → Owner's Equity and locks all 12 months.
- `ReportingService.year_end_blockers(year: int) -> list[ReconcilingItem]` where `ReconcilingItem` is frozen `{ref: int, amount: Money, age_days: int, classification: str}`.
- Roles `owners_equity` ("Owner's Equity") and `write_off` ("Write-off") are seeded by default; the **account rows** still need `create_account`.
- Money on the wire: integer minor units; `Money.minor_units` and `Money.currency.value` read them back. `Money.myr(n)` builds an MYR amount.
- A bank posting is created by `mark_paid` (Dr Bank / Cr AR). One dated early in the year is stale (> 30 days) and uncleared by year-end → a hard-close blocker.

## File Structure

- **Create** `src/books/interfaces/mcp/tools/closing.py` — `soft_close`, `write_off`, `hard_close` tools.
- **Create** `src/books/interfaces/mcp/resources/closing.py` — `closings://`, `year-end-blockers://{year}` resources.
- **Create** `tests/test_period_locks_read.py` — domain unit test for the new read.
- **Create** `tests/test_mcp_period_close.py` — MCP end-to-end tests.
- **Modify** `src/books/general_ledger/persistence/repository.py` — add `list_period_locks`.
- **Modify** `src/books/general_ledger/service.py` — add `PeriodLockView` + `locked_periods()`.
- **Modify** `src/books/interfaces/mcp/tools/__init__.py` — register closing tools.
- **Modify** `src/books/interfaces/mcp/resources/__init__.py` — register closing resources.

---

### Task 1: Domain read — `LedgerService.locked_periods()`

**Files:**
- Modify: `src/books/general_ledger/persistence/repository.py` (add `list_period_locks` after `is_period_locked`, ~line 147)
- Modify: `src/books/general_ledger/service.py` (add `PeriodLockView` after the `Account` dataclass ~line 91; add `locked_periods()` after `accounts()` ~line 333)
- Test: `tests/test_period_locks_read.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_period_locks_read.py`:

```python
"""General Ledger read: locked_periods() lists every closed period and its
kind (soft/hard), period-ordered. Backs the closings:// MCP resource.
"""

from __future__ import annotations

from books import create_app


def test_locked_periods_lists_soft_in_period_order():
    app = create_app("sqlite://")
    app.ledger.soft_close("2026-03")
    app.ledger.soft_close("2026-01")

    locks = app.ledger.locked_periods()

    assert [(lk.period, lk.kind) for lk in locks] == [
        ("2026-01", "soft"),
        ("2026-03", "soft"),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_period_locks_read.py -v`
Expected: FAIL with `AttributeError: 'LedgerService' object has no attribute 'locked_periods'`

- [ ] **Step 3: Add the repository query**

In `src/books/general_ledger/persistence/repository.py`, add this method immediately after `is_period_locked` (the method ending at ~line 147):

```python
    def list_period_locks(self, session: Session) -> list[tuple[str, str]]:
        """Every locked period and its kind (soft/hard), period-ordered."""
        return [
            (row.period, row.kind)
            for row in session.execute(
                select(_PeriodClose).order_by(_PeriodClose.period)
            ).scalars()
        ]
```

(`_PeriodClose` and `select` are already imported in this file.)

- [ ] **Step 4: Add the view + service read**

In `src/books/general_ledger/service.py`, add this dataclass immediately after the `Account` dataclass (the block ending ~line 91):

```python
@dataclass(frozen=True, slots=True)
class PeriodLockView:
    """A closed period and its kind (soft/hard) — a read view, no behaviour."""

    period: str
    kind: str
```

Then add this method to `LedgerService`, immediately after `accounts()` (ending ~line 333):

```python
    def locked_periods(self) -> list[PeriodLockView]:
        """Every closed period and its kind (soft/hard), period-ordered."""
        with self._repo.unit_of_work() as session:
            return [
                PeriodLockView(period=period, kind=kind)
                for period, kind in self._repo.list_period_locks(session)
            ]
```

(`dataclass` and `field` are already imported at the top of this file.)

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_period_locks_read.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_period_locks_read.py src/books/general_ledger/persistence/repository.py src/books/general_ledger/service.py
git commit -m "feat(general_ledger): locked_periods() read view"
```

---

### Task 2: `closings://` resource

**Files:**
- Create: `src/books/interfaces/mcp/resources/closing.py`
- Modify: `src/books/interfaces/mcp/resources/__init__.py`
- Test: `tests/test_mcp_period_close.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_period_close.py`:

```python
"""MCP period-close tracer (ADR-0008 / ADR-0009), end-to-end through the
in-memory client. Mirrors test_increment_4_hard_close_gate.py via the MCP
adapter: soft close, write-off, and the two-tier hard-close gate.
"""

from __future__ import annotations

import json

from _mcp_helpers import mcp_client, run
from books import create_app
from books.platform.money import Money


def test_closings_resource_lists_soft_closed_period_via_mcp():
    app = create_app("sqlite://")
    app.ledger.soft_close("2026-03")

    async def scenario():
        async with mcp_client(app) as client:
            rows = json.loads(
                (await client.read_resource("closings://")).contents[0].text
            )
            assert rows == [{"period": "2026-03", "kind": "soft"}]

    run(scenario())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_period_close.py -v`
Expected: FAIL — unknown resource `closings://` (error result / no matching resource).

- [ ] **Step 3: Create the resource module**

Create `src/books/interfaces/mcp/resources/closing.py`:

```python
"""Period-close resources: what's already closed, and what blocks a hard
close (ADR-0008 / ADR-0009).

- closings:// — every locked period and its kind (soft/hard).
- year-end-blockers://{year} — stale uncleared bank postings standing in
  the way of the annual hard close.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from books import App


def register(mcp: FastMCP, books: App) -> None:
    @mcp.resource("closings://")
    def list_closings() -> str:
        """Every locked period and its kind (soft/hard), period-ordered."""
        return json.dumps(
            [
                {"period": lk.period, "kind": lk.kind}
                for lk in books.ledger.locked_periods()
            ]
        )
```

- [ ] **Step 4: Register the resource**

In `src/books/interfaces/mcp/resources/__init__.py`, add the import and call alongside the existing ones inside `register`:

```python
def register(mcp: FastMCP, books: App) -> None:
    from books.interfaces.mcp.resources.closing import register as register_closing
    from books.interfaces.mcp.resources.invoicing import register as register_invoicing
    from books.interfaces.mcp.resources.postings import register as register_postings
    from books.interfaces.mcp.resources.setup import register as register_setup

    register_setup(mcp, books)
    register_postings(mcp, books)
    register_invoicing(mcp, books)
    register_closing(mcp, books)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_period_close.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/books/interfaces/mcp/resources/closing.py src/books/interfaces/mcp/resources/__init__.py tests/test_mcp_period_close.py
git commit -m "feat(mcp): closings:// resource — locked periods"
```

---

### Task 3: `year-end-blockers://{year}` resource

**Files:**
- Modify: `src/books/interfaces/mcp/resources/closing.py` (add a second resource)
- Test: `tests/test_mcp_period_close.py` (add a test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mcp_period_close.py`:

```python
def test_year_end_blockers_resource_shows_stale_bank_posting_via_mcp():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    customer = app.party.register_party(name="Acme", role="customer")

    async def scenario():
        async with mcp_client(app) as client:
            issued = json.loads(
                (
                    await client.call_tool(
                        "issue_invoice",
                        {
                            "number": 1,
                            "party_id": customer.id,
                            "amount_minor": 1000_00,
                            "currency": "MYR",
                            "issued_on": "2026-01-10",
                        },
                    )
                )
                .content[0]
                .text
            )
            # mark_paid posts Dr Bank / Cr AR — an uncleared, soon-stale
            # bank posting that blocks the year-end hard close.
            await client.call_tool(
                "mark_paid",
                {"invoice_id": issued["invoice_id"], "paid_on": "2026-03-01"},
            )

            blockers = json.loads(
                (await client.read_resource("year-end-blockers://2026"))
                .contents[0]
                .text
            )
            assert len(blockers) == 1
            assert blockers[0]["amount_minor"] == 1000_00
            assert blockers[0]["currency"] == "MYR"

    run(scenario())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_period_close.py::test_year_end_blockers_resource_shows_stale_bank_posting_via_mcp -v`
Expected: FAIL — unknown resource `year-end-blockers://2026`.

- [ ] **Step 3: Add the second resource**

In `src/books/interfaces/mcp/resources/closing.py`, add this resource inside `register`, after `list_closings`:

```python
    @mcp.resource("year-end-blockers://{year}")
    def year_end_blockers(year: str) -> str:
        """Stale uncleared bank postings blocking the {year} hard close.
        Path params arrive as strings, so coerce to int before lookup."""
        return json.dumps(
            [
                {
                    "ref": b.ref,
                    "amount_minor": b.amount.minor_units,
                    "currency": b.amount.currency.value,
                    "age_days": b.age_days,
                    "classification": b.classification,
                }
                for b in books.reporting.year_end_blockers(int(year))
            ]
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_period_close.py -v`
Expected: PASS (both resource tests)

- [ ] **Step 5: Commit**

```bash
git add src/books/interfaces/mcp/resources/closing.py tests/test_mcp_period_close.py
git commit -m "feat(mcp): year-end-blockers:// resource"
```

---

### Task 4: `soft_close` tool

**Files:**
- Create: `src/books/interfaces/mcp/tools/closing.py`
- Modify: `src/books/interfaces/mcp/tools/__init__.py`
- Test: `tests/test_mcp_period_close.py` (add a test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mcp_period_close.py`:

```python
def test_soft_close_locks_month_via_mcp():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    customer = app.party.register_party(name="Acme", role="customer")

    async def scenario():
        async with mcp_client(app) as client:
            result = json.loads(
                (await client.call_tool("soft_close", {"period": "2026-03"}))
                .content[0]
                .text
            )
            assert result == {"status": "soft_closed", "period": "2026-03"}

            rows = json.loads(
                (await client.read_resource("closings://")).contents[0].text
            )
            assert {"period": "2026-03", "kind": "soft"} in rows

            # A new economic entry dated into the locked month is rejected.
            rejected = await client.call_tool(
                "issue_invoice",
                {
                    "number": 1,
                    "party_id": customer.id,
                    "amount_minor": 500_00,
                    "currency": "MYR",
                    "issued_on": "2026-03-15",
                },
            )
            assert rejected.isError is True
            text = rejected.content[0].text
            assert "2026-03" in text or "closed" in text.lower()

    run(scenario())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_period_close.py::test_soft_close_locks_month_via_mcp -v`
Expected: FAIL — unknown tool `soft_close`.

- [ ] **Step 3: Create the tools module**

Create `src/books/interfaces/mcp/tools/closing.py`:

```python
"""Period-close tools: the two-tier close (ADR-0008 / ADR-0009).

- soft_close: locks a completed month against casual edits; idempotent,
  never blocks on uncleared items.
- write_off: guided-journal Dr Write-off / Cr Bank that clears a phantom
  bank posting out of the uncleared set (unblocks a hard close).
- hard_close: blocks while stale uncleared items remain (returns them as a
  structured "blocked" result, ADR-0019 spirit); otherwise sweeps net P&L
  to Owner's Equity and locks the whole fiscal year.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from books import App
from books.interfaces.mcp.forms import date_from


def register(mcp: FastMCP, books: App) -> None:
    @mcp.tool()
    def soft_close(period: str) -> dict:
        """Soft-close a completed month (YYYY-MM). Locks it against new
        economic entries; corrections still flow via the guided-journal
        path. Idempotent; never blocks on uncleared items (ADR-0009)."""
        books.ledger.soft_close(period)
        return {"status": "soft_closed", "period": period}
```

- [ ] **Step 4: Register the tool**

In `src/books/interfaces/mcp/tools/__init__.py`, add the import and call alongside the existing ones inside `register`:

```python
def register(mcp: FastMCP, books: App) -> None:
    from books.interfaces.mcp.tools.closing import register as register_closing
    from books.interfaces.mcp.tools.expense import register as register_expense
    from books.interfaces.mcp.tools.invoicing import register as register_invoicing
    from books.interfaces.mcp.tools.setup import register as register_setup

    register_setup(mcp, books)
    register_expense(mcp, books)
    register_invoicing(mcp, books)
    register_closing(mcp, books)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_period_close.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 6: Commit**

```bash
git add src/books/interfaces/mcp/tools/closing.py src/books/interfaces/mcp/tools/__init__.py tests/test_mcp_period_close.py
git commit -m "feat(mcp): soft_close tool"
```

---

### Task 5: `write_off` tool

**Files:**
- Modify: `src/books/interfaces/mcp/tools/closing.py` (add a second tool)
- Test: `tests/test_mcp_period_close.py` (add a test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mcp_period_close.py`:

```python
def test_write_off_clears_blocker_via_mcp():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(code="Write-off", name="Write-off", type="expense")
    customer = app.party.register_party(name="Acme", role="customer")

    async def scenario():
        async with mcp_client(app) as client:
            issued = json.loads(
                (
                    await client.call_tool(
                        "issue_invoice",
                        {
                            "number": 1,
                            "party_id": customer.id,
                            "amount_minor": 1000_00,
                            "currency": "MYR",
                            "issued_on": "2026-01-10",
                        },
                    )
                )
                .content[0]
                .text
            )
            await client.call_tool(
                "mark_paid",
                {"invoice_id": issued["invoice_id"], "paid_on": "2026-03-01"},
            )

            before = json.loads(
                (await client.read_resource("year-end-blockers://2026"))
                .contents[0]
                .text
            )
            assert len(before) == 1
            ref = before[0]["ref"]

            result = json.loads(
                (
                    await client.call_tool(
                        "write_off", {"posting_ref": ref, "on": "2026-12-31"}
                    )
                )
                .content[0]
                .text
            )
            assert result == {"status": "written_off", "posting_ref": ref}

            after = json.loads(
                (await client.read_resource("year-end-blockers://2026"))
                .contents[0]
                .text
            )
            assert after == []

    run(scenario())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_period_close.py::test_write_off_clears_blocker_via_mcp -v`
Expected: FAIL — unknown tool `write_off`.

- [ ] **Step 3: Add the tool**

In `src/books/interfaces/mcp/tools/closing.py`, add this tool inside `register`, after `soft_close`:

```python
    @mcp.tool()
    def write_off(posting_ref: int, on: str) -> dict:
        """Write off a phantom bank posting (ADR-0006): a guided-journal
        Dr Write-off / Cr Bank reversal that removes the posting from the
        uncleared set so it no longer blocks the hard close. An unknown
        posting_ref surfaces as an error."""
        books.ledger.write_off(posting_ref=posting_ref, on=date_from(on))
        return {"status": "written_off", "posting_ref": posting_ref}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_period_close.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Commit**

```bash
git add src/books/interfaces/mcp/tools/closing.py tests/test_mcp_period_close.py
git commit -m "feat(mcp): write_off tool"
```

---

### Task 6: `hard_close` tool (blocked + closed paths)

**Files:**
- Modify: `src/books/interfaces/mcp/tools/closing.py` (add the third tool)
- Test: `tests/test_mcp_period_close.py` (add two tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_period_close.py`:

```python
def test_hard_close_sweeps_pnl_to_owners_equity_via_mcp():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(
        code="Owner's Equity", name="Owner's Equity", type="equity"
    )
    customer = app.party.register_party(name="Acme", role="customer")

    async def scenario():
        async with mcp_client(app) as client:
            # Accrued revenue only — no bank posting, so nothing blocks.
            await client.call_tool(
                "issue_invoice",
                {
                    "number": 1,
                    "party_id": customer.id,
                    "amount_minor": 1500_00,
                    "currency": "MYR",
                    "issued_on": "2026-02-01",
                },
            )
            result = json.loads(
                (await client.call_tool("hard_close", {"year": 2026}))
                .content[0]
                .text
            )
            assert result == {"status": "closed", "year": 2026}

            closings = json.loads(
                (await client.read_resource("closings://")).contents[0].text
            )
            hard = [c for c in closings if c["kind"] == "hard"]
            assert len(hard) == 12

    run(scenario())
    assert app.ledger.account_balance(code="Revenue") == Money.myr(0)
    assert app.ledger.account_balance(code="Owner's Equity") == Money.myr(-1500_00)


def test_hard_close_blocked_then_closes_after_write_off_via_mcp():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(code="Write-off", name="Write-off", type="expense")
    app.ledger.create_account(
        code="Owner's Equity", name="Owner's Equity", type="equity"
    )
    customer = app.party.register_party(name="Acme", role="customer")

    async def scenario():
        async with mcp_client(app) as client:
            issued = json.loads(
                (
                    await client.call_tool(
                        "issue_invoice",
                        {
                            "number": 1,
                            "party_id": customer.id,
                            "amount_minor": 1000_00,
                            "currency": "MYR",
                            "issued_on": "2026-01-10",
                        },
                    )
                )
                .content[0]
                .text
            )
            await client.call_tool(
                "mark_paid",
                {"invoice_id": issued["invoice_id"], "paid_on": "2026-03-01"},
            )

            blocked = json.loads(
                (await client.call_tool("hard_close", {"year": 2026}))
                .content[0]
                .text
            )
            assert blocked["status"] == "blocked"
            assert len(blocked["blockers"]) == 1
            ref = blocked["blockers"][0]["ref"]

            await client.call_tool(
                "write_off", {"posting_ref": ref, "on": "2026-12-31"}
            )

            closed = json.loads(
                (await client.call_tool("hard_close", {"year": 2026}))
                .content[0]
                .text
            )
            assert closed == {"status": "closed", "year": 2026}

    run(scenario())
    # Net P&L: Revenue 1,000 booked, Write-off 1,000 → zero swept to equity.
    assert app.ledger.account_balance(code="Revenue") == Money.myr(0)
    assert app.ledger.account_balance(code="Write-off") == Money.myr(0)
    assert app.ledger.account_balance(code="Owner's Equity") == Money.myr(0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_period_close.py -k hard_close -v`
Expected: FAIL — unknown tool `hard_close`.

- [ ] **Step 3: Add the tool**

In `src/books/interfaces/mcp/tools/closing.py`, add this tool inside `register`, after `write_off`:

```python
    @mcp.tool()
    def hard_close(year: int) -> dict:
        """Annual hard close (ADR-0008 / ADR-0009). Pre-checks the year-end
        blockers: if any stale uncleared item remains, returns a structured
        "blocked" result listing them — the agent guides the owner to write
        each off or adjudicate; the system never auto-decides (ADR-0019).
        Otherwise sweeps net P&L to Owner's Equity via the guided-journal
        path, locks all 12 months, and the fiscal year becomes immutable."""
        blockers = books.reporting.year_end_blockers(year)
        if blockers:
            return {
                "status": "blocked",
                "blockers": [
                    {
                        "ref": b.ref,
                        "amount_minor": b.amount.minor_units,
                        "currency": b.amount.currency.value,
                        "age_days": b.age_days,
                    }
                    for b in blockers
                ],
            }
        books.ledger.hard_close(year)
        return {"status": "closed", "year": year}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_period_close.py -v`
Expected: PASS (all period-close tests)

- [ ] **Step 5: Commit**

```bash
git add src/books/interfaces/mcp/tools/closing.py tests/test_mcp_period_close.py
git commit -m "feat(mcp): hard_close tool — structured blocked-or-closed"
```

---

### Task 7: Full-suite gate + boundaries

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest --timeout=60`
Expected: PASS (all prior tests + the new period-close tests).

- [ ] **Step 2: Lint**

Run: `uv run ruff check src tests`
Expected: no errors.

- [ ] **Step 3: Boundary contracts**

Run: `uv run lint-imports`
Expected: `Contracts: 6 kept, 0 broken`. (The MCP adapter importing `books.App` is the existing sanctioned pattern; no new contract needed.)

- [ ] **Step 4: Final review**

Dispatch a final code reviewer over the whole branch diff, then proceed to `superpowers:finishing-a-development-branch`.

---

## Self-Review

**Spec coverage:**
- soft_close tool → Task 4. write_off tool → Task 5. hard_close tool (structured blocked + closed) → Task 6. ✓
- `closings://` → Task 2. `year-end-blockers://{year}` → Task 3. ✓
- Domain read `locked_periods()` + `PeriodLockView` + repo `list_period_locks` → Task 1. ✓
- Error handling: unknown write-off ref surfaces as error (covered by domain `LookupError`; the existing `test_mcp_errors.py` pattern confirms FastMCP wrapping — not re-tested here as it's not new behaviour); blocked hard close is structured, asserted in Task 6; locked-month post rejected, asserted in Task 4. ✓
- Out-of-scope items (web UI, configurable FYE, reopening, format validation) → no tasks, correct. ✓

**Placeholder scan:** No TBD/TODO/"similar to"/"add error handling" left; every code step shows complete code. ✓

**Type consistency:** `PeriodLockView{period, kind}` used identically in Tasks 1 and 2. `locked_periods()` / `list_period_locks` names match across repo, service, resource. Tool return shapes (`soft_closed`/`written_off`/`closed`/`blocked`) match their test assertions. Blocker dict keys (`ref`, `amount_minor`, `currency`, `age_days`) consistent between the `hard_close` tool and the `year-end-blockers://` resource (resource additionally carries `classification`). ✓
