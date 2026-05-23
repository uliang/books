# Sell-side Invoicing MCP Tracer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the full sell-side invoice lifecycle (issue → mark paid → adjudicate FX shortfall) over MCP as thin tools/resources over `App.invoicing`, the parallel of the buy-side expense rail (#1).

**Architecture:** New `tools/invoicing.py` and `resources/invoicing.py` modules wired through the existing single `register` points. One new single-context domain read (`InvoicingService.list_invoices`) backs the `invoices://` resource. No new infrastructure, no new import-linter contracts. FX rate crosses the MCP boundary as integer basis points (×10000) and is converted to `Decimal` in `forms.py`.

**Tech Stack:** Python 3.13, `mcp` SDK (`FastMCP`), SQLAlchemy, pytest, in-memory MCP client harness (`tests/_mcp_helpers.py`).

**Spec:** `docs/superpowers/specs/2026-05-23-sell-side-invoicing-mcp-tracer-design.md`
**ADR:** `docs/adr/0019-settlement-adjudication-is-actor-agnostic-human-judged.md`

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/books/invoicing/persistence/repository.py` | + `InvoiceRepository.list_all(session)` | Modify |
| `src/books/invoicing/service.py` | + `InvoiceView` dataclass, `InvoicingService.list_invoices()` | Modify |
| `src/books/interfaces/mcp/forms.py` | + `rate_from_bp(rate_bp)` | Modify |
| `src/books/interfaces/mcp/tools/invoicing.py` | `issue_invoice`, `mark_paid`, `adjudicate_settlement` tools | Create |
| `src/books/interfaces/mcp/tools/__init__.py` | wire `register_invoicing` | Modify |
| `src/books/interfaces/mcp/resources/invoicing.py` | `invoices://`, `invoices://{invoice_id}/settlement` | Create |
| `src/books/interfaces/mcp/resources/__init__.py` | wire `register_invoicing` | Modify |
| `tests/test_invoicing.py` | + `list_invoices` unit test | Modify |
| `tests/test_mcp_invoicing_tools.py` | issue / mark_paid tool tests + `rate_from_bp` | Create |
| `tests/test_mcp_invoice_fx.py` | adjudicate both branches via MCP | Create |
| `tests/test_mcp_invoicing_resources.py` | `invoices://` + settlement resource | Create |
| `tests/test_mcp_invoicing_tracer.py` | end-to-end spine | Create |
| `tests/test_mcp_errors.py` | + invoicing error cases | Modify |
| `README.md` | + invoicing tools/resources | Modify |

**Account/role facts (verified against `general_ledger/service.py`):** `create_app` seeds default role→code: `ar→"AR"`, `revenue→"Revenue"`, `bank→"Bank"`, `fx_loss→"FX Loss"`. The role codes are seeded but the **accounts must still be created** (`create_account`) or postings fail the FK. `issue_invoice` posts Dr AR / Cr Revenue; `mark_paid` posts Dr Bank / Cr AR; `adjudicate_settlement(settled_in_full)` posts Dr FX Loss / Cr AR.

**Harness facts (verified against `tests/_mcp_helpers.py` and `test_mcp_expense_tracer.py`):** `mcp_client(app)` yields a `ClientSession`; `run(coro)` drives it. Tool results: `result.isError`, `result.content[0].text` (JSON). Resource reads: `(await client.read_resource(uri)).contents[0].text` (note `contents`, plural, for resources vs `content` for tools). A tool returning a `dict` is serialized to JSON text by FastMCP.

---

### Task 1: Domain read — `InvoicingService.list_invoices()`

**Files:**
- Modify: `src/books/invoicing/persistence/repository.py`
- Modify: `src/books/invoicing/service.py`
- Test: `tests/test_invoicing.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_invoicing.py`:

```python
def test_list_invoices_returns_rows_with_resolved_party_name():
    svc, _ = _invoicing()
    svc.issue_invoice(
        number=7,
        party_id=42,
        amount=Money.myr(500_00),
        issued_on=date(2026, 3, 1),
    )

    rows = svc.list_invoices()

    assert len(rows) == 1
    (row,) = rows
    assert row.number == 7
    assert row.party_id == 42
    assert row.party_name == "Acme"  # resolved via the injected resolver
    assert row.currency == "MYR"
    assert row.amount_minor == 500_00
    assert row.carrying_minor == 500_00
    assert row.banked_minor is None
    assert row.status == "issued"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_invoicing.py::test_list_invoices_returns_rows_with_resolved_party_name -v`
Expected: FAIL with `AttributeError: 'InvoicingService' object has no attribute 'list_invoices'`

- [ ] **Step 3: Add the repository query**

In `src/books/invoicing/persistence/repository.py`, add the `select` import and a `list_all` method (mirrors `PartyRepository.list_all`). The import line becomes:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session
```

Add this method to `InvoiceRepository` (after `set_status`):

```python
    def list_all(self, session: Session) -> list[InvoiceRow]:
        rows = session.execute(select(_Invoice).order_by(_Invoice.id)).scalars().all()
        return [_row_to_snapshot(r) for r in rows]
```

- [ ] **Step 4: Add the view + service method**

In `src/books/invoicing/service.py`, add the `InvoiceView` dataclass after `SettlementPicture`:

```python
@dataclass(frozen=True, slots=True)
class InvoiceView:
    """A row for the invoices:// read surface: the persisted invoice plus the
    resolved (cached-name) Party, so an agent can list and target invoices."""

    id: int
    number: int
    party_id: int
    party_name: str
    currency: str  # transaction currency
    amount_minor: int  # transaction currency
    carrying_minor: int  # functional MYR booked into AR
    banked_minor: int | None
    status: str
```

Add this method to `InvoicingService` (after `adjudicate_settlement`):

```python
    def list_invoices(self) -> list[InvoiceView]:
        with self._repo.unit_of_work() as session:
            rows = self._repo.list_all(session)
        return [
            InvoiceView(
                id=r.id,
                number=r.number,
                party_id=r.party_id,
                party_name=self._party_name(r.party_id),
                currency=r.currency,
                amount_minor=r.amount_minor,
                carrying_minor=r.carrying_minor,
                banked_minor=r.banked_minor,
                status=r.status,
            )
            for r in rows
        ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_invoicing.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 6: Commit**

```bash
git add src/books/invoicing/persistence/repository.py src/books/invoicing/service.py tests/test_invoicing.py
git commit -m "feat(invoicing): list_invoices read for the invoices:// surface"
```

---

### Task 2: `rate_from_bp` form + `issue_invoice` tool

**Files:**
- Modify: `src/books/interfaces/mcp/forms.py`
- Create: `src/books/interfaces/mcp/tools/invoicing.py`
- Modify: `src/books/interfaces/mcp/tools/__init__.py`
- Test: `tests/test_mcp_invoicing_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_invoicing_tools.py`:

```python
"""MCP invoicing tools — per-tool acceptance, driven through the adapter.

Parallels test_mcp_expense_tools.py: each sell-side verb exercised over
the in-memory MCP client against a fresh in-memory App.
"""

from __future__ import annotations

import json
from decimal import Decimal

from _mcp_helpers import mcp_client, run
from books import create_app
from books.platform.money import Money


def _chart(app) -> None:
    """The accounts the invoicing rail posts to (role codes are pre-seeded;
    the account rows must exist or postings fail the FK)."""
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")


def test_rate_from_bp_converts_basis_points_to_decimal():
    from books.interfaces.mcp.forms import rate_from_bp

    assert rate_from_bp(10000) == Decimal("1")
    assert rate_from_bp(32000) == Decimal("3.2")


def test_issue_invoice_tool_returns_id_and_books_ar():
    app = create_app("sqlite://")
    _chart(app)
    customer = app.party.register_party(name="Acme Sdn Bhd", role="customer")

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "issue_invoice",
                {
                    "number": 1001,
                    "party_id": customer.id,
                    "amount_minor": 500_000,  # MYR 5,000.00
                    "currency": "MYR",
                    "issued_on": "2026-02-01",
                },
            )
            assert result.isError is False
            payload = json.loads(result.content[0].text)
            assert payload["number"] == 1001
            assert payload["invoice_id"] >= 1

    run(scenario())
    assert app.ledger.account_balance(code="AR") == Money.myr(500_000)
    assert app.ledger.account_balance(code="Revenue") == Money.myr(-500_000)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_invoicing_tools.py -v`
Expected: FAIL — `rate_from_bp` ImportError and `issue_invoice` is an unknown tool (`result.isError is True` / tool-not-found).

- [ ] **Step 3: Add `rate_from_bp` to forms**

In `src/books/interfaces/mcp/forms.py`, add the `Decimal` import and the helper:

```python
from decimal import Decimal
```

```python
def rate_from_bp(rate_bp: int = 10000) -> Decimal:
    """Integer basis points (×10000) → Decimal booking rate. 10000 → 1,
    32000 → 3.2. Mirrors the minor-units convention: no floats on the wire."""
    return Decimal(rate_bp) / Decimal(10000)
```

- [ ] **Step 4: Create the tools module with `issue_invoice`**

Create `src/books/interfaces/mcp/tools/invoicing.py`:

```python
"""Invoicing tools: the sell-side lifecycle (ADR-0005, ADR-0019).

- issue_invoice: emits InvoiceIssued → GL Dr AR / Cr Revenue (MYR carrying).
- mark_paid: emits PaymentRecorded → GL Dr Bank / Cr AR; returns the
  resulting status so the agent knows whether adjudication follows.
- adjudicate_settlement: resolves a foreign-invoice MYR shortfall. The
  outcome is always supplied explicitly (ADR-0019); the system never
  decides FX vs underpayment.

The customer Party (party_id) is mandatory provenance on issue; an unknown
id surfaces as a LookupError (the injected resolver calls PartyService.get).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from books import App
from books.interfaces.mcp.forms import date_from, money_from_minor, rate_from_bp


def register(mcp: FastMCP, books: App) -> None:
    @mcp.tool()
    def issue_invoice(
        number: int,
        party_id: int,
        amount_minor: int,
        currency: str,
        issued_on: str,
        rate_bp: int = 10000,
    ) -> dict:
        """Issue an invoice to a customer.

        Posts Dr AR / Cr Revenue at the MYR carrying value via the
        InvoiceIssued event. `amount_minor`/`currency` are the transaction
        currency (e.g. SGD); `rate_bp` is the txn→MYR booking rate in
        integer basis points (×10000, e.g. 32000 = 3.20). MYR invoices
        ignore `rate_bp` (the domain forces rate 1). The customer
        `party_id` is mandatory provenance.
        """
        inv = books.invoicing.issue_invoice(
            number=number,
            party_id=party_id,
            amount=money_from_minor(amount_minor, currency),
            issued_on=date_from(issued_on),
            rate=rate_from_bp(rate_bp),
        )
        return {"invoice_id": inv.id, "number": inv.number}
```

- [ ] **Step 5: Wire the module**

In `src/books/interfaces/mcp/tools/__init__.py`, add the import and call:

```python
def register(mcp: FastMCP, books: App) -> None:
    from books.interfaces.mcp.tools.expense import register as register_expense
    from books.interfaces.mcp.tools.invoicing import register as register_invoicing
    from books.interfaces.mcp.tools.setup import register as register_setup

    register_setup(mcp, books)
    register_expense(mcp, books)
    register_invoicing(mcp, books)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_invoicing_tools.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/books/interfaces/mcp/forms.py src/books/interfaces/mcp/tools/invoicing.py src/books/interfaces/mcp/tools/__init__.py tests/test_mcp_invoicing_tools.py
git commit -m "feat(mcp): issue_invoice tool + rate_from_bp"
```

---

### Task 3: `mark_paid` tool

**Files:**
- Modify: `src/books/interfaces/mcp/tools/invoicing.py`
- Test: `tests/test_mcp_invoicing_tools.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mcp_invoicing_tools.py`:

```python
def test_mark_paid_full_returns_paid_status():
    from datetime import date

    app = create_app("sqlite://")
    _chart(app)
    customer = app.party.register_party(name="Acme", role="customer")
    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=customer.id,
        amount=Money.myr(500_000),
        issued_on=date(2026, 2, 1),
    )

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "mark_paid",
                {"invoice_id": inv.id, "paid_on": "2026-02-20"},
            )
            assert result.isError is False
            assert json.loads(result.content[0].text)["status"] == "paid"

    run(scenario())
    assert app.ledger.account_balance(code="AR") == Money.myr(0)
    assert app.ledger.account_balance(code="Bank") == Money.myr(500_000)


def test_mark_paid_short_returns_awaiting_adjudication():
    from datetime import date
    from decimal import Decimal

    from books.platform.money import Currency

    app = create_app("sqlite://")
    _chart(app)
    customer = app.party.register_party(name="Acme", role="customer")
    # SGD 1,000 @ 3.20 → carrying MYR 3,200.
    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=customer.id,
        amount=Money(100_000, Currency.SGD),
        issued_on=date(2026, 1, 10),
        rate=Decimal("3.20"),
    )

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "mark_paid",
                {
                    "invoice_id": inv.id,
                    "paid_on": "2026-01-20",
                    "banked_minor": 318_000,  # MYR 3,180 — MYR 20 short
                },
            )
            assert result.isError is False
            assert json.loads(result.content[0].text)["status"] == "awaiting_adjudication"

    run(scenario())
    assert app.ledger.account_balance(code="AR") == Money.myr(20_00)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_invoicing_tools.py::test_mark_paid_full_returns_paid_status -v`
Expected: FAIL — `mark_paid` is an unknown tool (`result.isError is True`).

- [ ] **Step 3: Add the `mark_paid` tool**

Append inside `register(...)` in `src/books/interfaces/mcp/tools/invoicing.py`:

```python
    @mcp.tool()
    def mark_paid(
        invoice_id: int,
        paid_on: str,
        banked_minor: int | None = None,
        banked_currency: str = "MYR",
    ) -> dict:
        """Mark an invoice paid — the owner's assertion that funds were seen
        (CONTEXT / ADR-0004). Posts Dr Bank / Cr AR via PaymentRecorded.

        `banked_minor=None` means the full MYR carrying value landed (the
        domestic case). For a foreign invoice that banked fewer MYR, pass the
        actual MYR received; the shortfall stays open and the returned status
        is "awaiting_adjudication" (ADR-0005). Otherwise the status is "paid".
        """
        banked = (
            money_from_minor(banked_minor, banked_currency)
            if banked_minor is not None
            else None
        )
        books.invoicing.mark_paid(
            invoice_id=invoice_id,
            paid_on=date_from(paid_on),
            banked=banked,
        )
        picture = books.invoicing.settlement_picture(invoice_id)
        status = "paid" if picture.shortfall.minor_units <= 0 else "awaiting_adjudication"
        return {"status": status}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_invoicing_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/books/interfaces/mcp/tools/invoicing.py tests/test_mcp_invoicing_tools.py
git commit -m "feat(mcp): mark_paid tool returning settlement status"
```

---

### Task 4: `adjudicate_settlement` tool

**Files:**
- Modify: `src/books/interfaces/mcp/tools/invoicing.py`
- Test: `tests/test_mcp_invoice_fx.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_invoice_fx.py`:

```python
"""MCP sell-side FX adjudication (ADR-0005 / ADR-0019), end-to-end.

A foreign invoice that banks fewer MYR than carried is ambiguous. The agent
relays the owner's explicit outcome; the system never auto-decides. Mirrors
test_increment_3_fx_adjudication.py through the MCP adapter.
"""

from __future__ import annotations

import json

from _mcp_helpers import mcp_client, run
from books import create_app
from books.platform.money import Money


def _fx_chart(app) -> None:
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(code="FX Loss", name="Realized FX Loss", type="expense")


def test_foreign_invoice_settled_in_full_recognizes_fx_loss_via_mcp():
    app = create_app("sqlite://")
    _fx_chart(app)
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
                            "amount_minor": 100_000,  # SGD 1,000.00
                            "currency": "SGD",
                            "issued_on": "2026-01-10",
                            "rate_bp": 32000,  # 3.20 → carrying MYR 3,200
                        },
                    )
                ).content[0].text
            )
            invoice_id = issued["invoice_id"]

            paid = json.loads(
                (
                    await client.call_tool(
                        "mark_paid",
                        {
                            "invoice_id": invoice_id,
                            "paid_on": "2026-01-20",
                            "banked_minor": 318_000,  # MYR 3,180
                        },
                    )
                ).content[0].text
            )
            assert paid["status"] == "awaiting_adjudication"

            adj = json.loads(
                (
                    await client.call_tool(
                        "adjudicate_settlement",
                        {
                            "invoice_id": invoice_id,
                            "outcome": "settled_in_full",
                            "on": "2026-01-25",
                        },
                    )
                ).content[0].text
            )
            assert adj["status"] == "paid"

    run(scenario())
    assert app.ledger.account_balance(code="AR") == Money.myr(0)
    assert app.ledger.account_balance(code="FX Loss") == Money.myr(20_00)


def test_foreign_invoice_still_owes_leaves_ar_open_via_mcp():
    app = create_app("sqlite://")
    _fx_chart(app)
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
                            "amount_minor": 100_000,
                            "currency": "SGD",
                            "issued_on": "2026-01-10",
                            "rate_bp": 32000,
                        },
                    )
                ).content[0].text
            )
            invoice_id = issued["invoice_id"]
            await client.call_tool(
                "mark_paid",
                {
                    "invoice_id": invoice_id,
                    "paid_on": "2026-01-20",
                    "banked_minor": 318_000,
                },
            )
            adj = json.loads(
                (
                    await client.call_tool(
                        "adjudicate_settlement",
                        {
                            "invoice_id": invoice_id,
                            "outcome": "still_owes",
                            "on": "2026-01-25",
                        },
                    )
                ).content[0].text
            )
            assert adj["status"] == "partially_paid"

    run(scenario())
    assert app.ledger.account_balance(code="AR") == Money.myr(20_00)
    assert app.ledger.account_balance(code="FX Loss") == Money.myr(0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_invoice_fx.py -v`
Expected: FAIL — `adjudicate_settlement` is an unknown tool (`result.isError is True` at the adjudicate call).

- [ ] **Step 3: Add the `adjudicate_settlement` tool**

Append inside `register(...)` in `src/books/interfaces/mcp/tools/invoicing.py`:

```python
    @mcp.tool()
    def adjudicate_settlement(invoice_id: int, outcome: str, on: str) -> dict:
        """Resolve a foreign-invoice MYR shortfall (ADR-0005 / ADR-0019).

        `outcome` is supplied explicitly by the caller — the system never
        infers FX vs underpayment:
        - "settled_in_full": the gap is realized FX loss; emits
          SettlementAdjudicated → GL Dr FX Loss / Cr AR. Status → "paid".
        - "still_owes": a genuine underpayment; AR stays open, no FX posted.
          Status → "partially_paid".
        Any other outcome raises ValueError (surfaces as an error result).
        """
        books.invoicing.adjudicate_settlement(
            invoice_id=invoice_id,
            outcome=outcome,
            on=date_from(on),
        )
        return {"status": "paid" if outcome == "settled_in_full" else "partially_paid"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_invoice_fx.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/books/interfaces/mcp/tools/invoicing.py tests/test_mcp_invoice_fx.py
git commit -m "feat(mcp): adjudicate_settlement tool (ADR-0019, both branches)"
```

---

### Task 5: Resources — `invoices://` and `invoices://{invoice_id}/settlement`

**Files:**
- Create: `src/books/interfaces/mcp/resources/invoicing.py`
- Modify: `src/books/interfaces/mcp/resources/__init__.py`
- Test: `tests/test_mcp_invoicing_resources.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_invoicing_resources.py`:

```python
"""MCP invoicing resources: invoices:// list + per-id settlement picture.

Parallels test_mcp_setup_resources.py / test_mcp_postings_resource.py.
"""

from __future__ import annotations

import json

from _mcp_helpers import mcp_client, run
from books import create_app


def _chart(app) -> None:
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")


def test_invoices_resource_empty_then_lists_issued_invoice():
    app = create_app("sqlite://")
    _chart(app)
    customer = app.party.register_party(name="Acme Sdn Bhd", role="customer")

    async def scenario():
        async with mcp_client(app) as client:
            empty = json.loads(
                (await client.read_resource("invoices://")).contents[0].text
            )
            assert empty == []

            await client.call_tool(
                "issue_invoice",
                {
                    "number": 1001,
                    "party_id": customer.id,
                    "amount_minor": 500_000,
                    "currency": "MYR",
                    "issued_on": "2026-02-01",
                },
            )
            rows = json.loads(
                (await client.read_resource("invoices://")).contents[0].text
            )
            assert len(rows) == 1
            assert rows[0]["number"] == 1001
            assert rows[0]["party_name"] == "Acme Sdn Bhd"
            assert rows[0]["currency"] == "MYR"
            assert rows[0]["carrying_minor"] == 500_000
            assert rows[0]["banked_minor"] is None
            assert rows[0]["status"] == "issued"

    run(scenario())


def test_settlement_resource_shows_both_numbers():
    app = create_app("sqlite://")
    _chart(app)
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
                            "amount_minor": 100_000,  # SGD 1,000.00
                            "currency": "SGD",
                            "issued_on": "2026-01-10",
                            "rate_bp": 32000,  # carrying MYR 3,200
                        },
                    )
                ).content[0].text
            )
            invoice_id = issued["invoice_id"]
            await client.call_tool(
                "mark_paid",
                {
                    "invoice_id": invoice_id,
                    "paid_on": "2026-01-20",
                    "banked_minor": 318_000,  # MYR 3,180
                },
            )

            s = json.loads(
                (
                    await client.read_resource(f"invoices://{invoice_id}/settlement")
                ).contents[0].text
            )
            assert s["transaction_currency"] == "SGD"
            assert s["transaction_amount_minor"] == 100_000
            assert s["carrying_minor"] == 320_000
            assert s["banked_minor"] == 318_000
            assert s["shortfall_minor"] == 2_000

    run(scenario())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_invoicing_resources.py -v`
Expected: FAIL — reading `invoices://` errors (unknown resource).

- [ ] **Step 3: Create the resources module**

Create `src/books/interfaces/mcp/resources/invoicing.py`:

```python
"""Invoicing resources: the agent's invoice lookup and the both-numbers
settlement picture used to adjudicate a foreign-currency shortfall.

- invoices:// — every invoice (list), so mark_paid / adjudicate have an id.
- invoices://{invoice_id}/settlement — the SettlementPicture (ADR-0005):
  transaction amount, MYR carrying, MYR banked, MYR shortfall.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from books import App


def register(mcp: FastMCP, books: App) -> None:
    @mcp.resource("invoices://")
    def list_invoices() -> str:
        """Every invoice in the books, in issue order."""
        return json.dumps(
            [
                {
                    "id": i.id,
                    "number": i.number,
                    "party_id": i.party_id,
                    "party_name": i.party_name,
                    "currency": i.currency,
                    "amount_minor": i.amount_minor,
                    "carrying_minor": i.carrying_minor,
                    "banked_minor": i.banked_minor,
                    "status": i.status,
                }
                for i in books.invoicing.list_invoices()
            ]
        )

    @mcp.resource("invoices://{invoice_id}/settlement")
    def settlement(invoice_id: str) -> str:
        """The both-numbers settlement picture for one invoice. Path params
        arrive as strings, so coerce to int before lookup."""
        pic = books.invoicing.settlement_picture(int(invoice_id))
        return json.dumps(
            {
                "transaction_amount_minor": pic.transaction_amount.minor_units,
                "transaction_currency": pic.transaction_amount.currency.value,
                "carrying_minor": pic.carrying.minor_units,
                "banked_minor": pic.banked.minor_units,
                "shortfall_minor": pic.shortfall.minor_units,
            }
        )
```

- [ ] **Step 4: Wire the module**

In `src/books/interfaces/mcp/resources/__init__.py`:

```python
def register(mcp: FastMCP, books: App) -> None:
    from books.interfaces.mcp.resources.invoicing import register as register_invoicing
    from books.interfaces.mcp.resources.postings import register as register_postings
    from books.interfaces.mcp.resources.setup import register as register_setup

    register_setup(mcp, books)
    register_postings(mcp, books)
    register_invoicing(mcp, books)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_invoicing_resources.py -v`
Expected: PASS

> If FastMCP rejects registering the static `invoices://` alongside the
> templated `invoices://{invoice_id}/settlement` (URI conflict), rename the
> list resource to `invoices://list` and update the two list-resource reads
> in the tests accordingly. The static + template pair is expected to work
> (they are distinct templates), so try as written first.

- [ ] **Step 6: Commit**

```bash
git add src/books/interfaces/mcp/resources/invoicing.py src/books/interfaces/mcp/resources/__init__.py tests/test_mcp_invoicing_resources.py
git commit -m "feat(mcp): invoices:// list + settlement resources"
```

---

### Task 6: End-to-end tracer spine

**Files:**
- Test: `tests/test_mcp_invoicing_tracer.py`

This task adds no production code — it asserts the assembled slice works through the MCP surface only, the way `test_mcp_expense_tracer.py` does for the buy-side.

- [ ] **Step 1: Write the tracer test**

Create `tests/test_mcp_invoicing_tracer.py`:

```python
"""MCP tracer — the agent's sell-side spine, end-to-end.

The MCP-side parallel of test_mcp_expense_tracer.py: drives issue → list →
mark paid → verify, exclusively through the MCP adapter.
"""

from __future__ import annotations

import json

from _mcp_helpers import mcp_client, run
from books import create_app
from books.platform.money import Money


def test_agent_issues_and_settles_invoice_end_to_end_via_mcp():
    app = create_app("sqlite://")
    # Role codes are pre-seeded; create the account rows the rail posts to.
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")

    async def scenario():
        async with mcp_client(app) as client:
            # 1. Agent inspects invoices://; finds it empty.
            invoices = json.loads(
                (await client.read_resource("invoices://")).contents[0].text
            )
            assert invoices == []

            # 2. Agent registers the customer.
            customer = json.loads(
                (
                    await client.call_tool(
                        "register_party",
                        {"name": "Acme Sdn Bhd", "role": "customer"},
                    )
                ).content[0].text
            )

            # 3. Agent issues the invoice.
            issued = json.loads(
                (
                    await client.call_tool(
                        "issue_invoice",
                        {
                            "number": 1001,
                            "party_id": customer["id"],
                            "amount_minor": 500_000,  # MYR 5,000.00
                            "currency": "MYR",
                            "issued_on": "2026-02-01",
                        },
                    )
                ).content[0].text
            )
            invoice_id = issued["invoice_id"]

            # 4. invoices:// now lists it, status "issued".
            invoices = json.loads(
                (await client.read_resource("invoices://")).contents[0].text
            )
            assert len(invoices) == 1
            assert invoices[0]["status"] == "issued"
            assert invoices[0]["party_name"] == "Acme Sdn Bhd"
            assert invoices[0]["carrying_minor"] == 500_000

            # 5. Owner saw the money; agent marks it paid (full).
            paid = json.loads(
                (
                    await client.call_tool(
                        "mark_paid",
                        {"invoice_id": invoice_id, "paid_on": "2026-02-20"},
                    )
                ).content[0].text
            )
            assert paid["status"] == "paid"

            # 6. postings://AR — the issue and payment legs both present.
            ar_postings = json.loads(
                (await client.read_resource("postings://AR")).contents[0].text
            )
            assert len(ar_postings) == 2

    run(scenario())

    # Cross-check the books directly: AR cleared, cash in, revenue booked.
    assert app.ledger.account_balance(code="AR") == Money.myr(0)
    assert app.ledger.account_balance(code="Bank") == Money.myr(500_000)
    assert app.ledger.account_balance(code="Revenue") == Money.myr(-500_000)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_invoicing_tracer.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_invoicing_tracer.py
git commit -m "test(mcp): sell-side invoicing tracer spine end-to-end"
```

---

### Task 7: Error translation cases

**Files:**
- Modify: `tests/test_mcp_errors.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mcp_errors.py`. First extend the imports at the top of the file:

```python
from datetime import date

from books.platform.money import Money
```

Then add the cases:

```python
def test_unknown_invoice_id_on_mark_paid_surfaces_as_tool_error():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "mark_paid",
                {"invoice_id": 999, "paid_on": "2026-02-20"},
            )
            assert result.isError is True
            assert "999" in result.content[0].text

    run(scenario())


def test_unknown_party_on_issue_invoice_surfaces_as_tool_error():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "issue_invoice",
                {
                    "number": 1,
                    "party_id": 999,  # nonexistent
                    "amount_minor": 100_00,
                    "currency": "MYR",
                    "issued_on": "2026-02-01",
                },
            )
            assert result.isError is True
            assert "999" in result.content[0].text

    run(scenario())


def test_bad_adjudication_outcome_surfaces_as_tool_error():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    customer = app.party.register_party(name="Acme", role="customer")
    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=customer.id,
        amount=Money.myr(100_00),
        issued_on=date(2026, 2, 1),
    )
    app.invoicing.mark_paid(invoice_id=inv.id, paid_on=date(2026, 2, 20))

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "adjudicate_settlement",
                {"invoice_id": inv.id, "outcome": "not_an_outcome", "on": "2026-02-25"},
            )
            assert result.isError is True

    run(scenario())
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_errors.py -v`
Expected: PASS (the new cases plus the existing two). They pass immediately — the tools already raise the right exceptions and FastMCP wraps them as `isError`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_errors.py
git commit -m "test(mcp): invoicing error translation cases"
```

---

### Task 8: Docs — README tools/resources

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the invoicing tools**

In `README.md`, under `#### Available tools`, after the `reimburse_owner` line, add:

```markdown
- `issue_invoice(number, party_id, amount_minor, currency, issued_on, rate_bp?)`
  — issue an invoice (Dr AR / Cr Revenue). `rate_bp` is the txn→MYR booking
  rate in integer basis points (×10000, e.g. `32000` = 3.20); defaults to
  `10000` (1.00) and is ignored for MYR.
- `mark_paid(invoice_id, paid_on, banked_minor?, banked_currency?)` — record
  payment (Dr Bank / Cr AR). Returns `status`: `paid` or `awaiting_adjudication`.
- `adjudicate_settlement(invoice_id, outcome, on)` — resolve a foreign-invoice
  MYR shortfall. `outcome` is `settled_in_full` (recognize FX loss) or
  `still_owes` (AR stays open); always supplied explicitly (ADR-0019).
```

- [ ] **Step 2: Add the invoicing resources**

Under `#### Available resources`, after the `postings://{account_code}` entry, add:

```markdown
- `invoices://` — every invoice, with resolved customer name and status.
- `invoices://{invoice_id}/settlement` — the both-numbers settlement picture
  (transaction amount, MYR carrying, MYR banked, MYR shortfall) for
  adjudicating a foreign-currency invoice.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README — sell-side invoicing MCP tools + resources"
```

---

## Final Verification

- [ ] **Run the full suite, lint, and boundary contracts**

```bash
uv run pytest
uv run ruff check src tests
uv run lint-imports
```

Expected: all green; ruff clean; all six ADR-0013 import-linter contracts pass (no new contracts were added — `books.interfaces.mcp.invoicing.*` is already covered by the existing `books.interfaces.*` rules).

- [ ] **Manual smoke (optional)**

```bash
uv run books-mcp
```

Confirm it launches over stdio without import errors.

---

## Self-Review Notes

- **Spec coverage:** issue/mark_paid/adjudicate tools (Tasks 2–4), invoices:// + settlement resources (Task 5), `list_invoices` domain read (Task 1), basis-point rate (Task 2), full-lifecycle tracer (Task 6), error translation (Task 7), README (Task 8), ADR-0019 already committed. No new import-linter contracts (spec §Architecture) — confirmed in Final Verification.
- **Type consistency:** `InvoiceView` fields match the `invoices://` JSON keys and the `list_invoices` test. Tool status strings (`paid` / `awaiting_adjudication` / `partially_paid`) match the domain (`InvoicingService.mark_paid` / `adjudicate_settlement`) and the settlement-shortfall derivation. `rate_from_bp` signature matches both its unit test and the `issue_invoice` call site.
- **Repo method name:** `InvoiceRepository.list_all` (mirrors `PartyRepository.list_all`), not `.all` — the spec's prose said `.all`; the implementation uses `list_all` for house-style consistency.
