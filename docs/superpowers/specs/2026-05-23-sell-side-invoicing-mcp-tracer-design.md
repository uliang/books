# MCP Interface — Tracer Slice (Sell-side Invoicing, Design)

> Date: 2026-05-23
> Status: Approved (brainstorming) — pending implementation plan
> Companion to `docs/ARCHITECTURE.md`, the MCP expense-rail tracer
> (`docs/superpowers/specs/2026-05-20-mcp-interface-tracer-expense-rail-design.md`),
> and ADR-0005 / ADR-0013 / ADR-0015 / ADR-0019.

## Goal

Extend the MCP interface with the **sell-side invoicing rail**, the natural
parallel to the buy-side expense rail shipped in `#1`. Same adapter pattern —
thin tools/resources over the existing composition root (`books.create_app()
-> App`), no new infrastructure. This slice exposes the **full invoice
lifecycle** to an LLM agent: issue an invoice, mark it paid once the owner has
seen the money, and (for foreign invoices that bank fewer MYR than carried)
adjudicate the shortfall.

Where the expense rail was a single agent verb (submit an expense from an
image), invoicing is a small lifecycle with a human-judgment branch (FX vs
underpayment, ADR-0005). The agent drives every step but **never decides** the
ambiguous branch — it relays the owner's explicit outcome (ADR-0019).

Non-goal: the full domain surface. Reconciliation MCP tools and ledger
lifecycle (`soft_close` / `hard_close` / `write_off`) remain later increments.

## Architecture & Boundary

No architectural decisions are reopened. This slice follows the adapter pattern
the expense tracer already established:

- `FastMCP` high-level API (`@mcp.tool()` / `@mcp.resource()`).
- Tools are thin over `App.invoicing`; reads are resources.
- New tool/resource modules wire through the existing single `register`
  points (`tools/__init__.py`, `resources/__init__.py`).
- In-memory client tests via
  `mcp.shared.memory.create_connected_server_and_client_session`, injecting an
  in-memory `App` (`create_mcp_server(create_app("sqlite://"))`).
- **No new `import-linter` contracts** — the existing two interface contracts
  already match `books.interfaces.*`, so `books.interfaces.mcp.invoicing.*` is
  covered the moment it exists. `tests/test_architecture.py` confirms the six
  contracts still hold.

### Package additions

```
src/books/interfaces/mcp/
  forms.py                # + rate_from_bp(rate_bp: int) -> Decimal
  tools/
    __init__.py           # + register_invoicing
    invoicing.py          # issue_invoice, mark_paid, adjudicate_settlement
  resources/
    __init__.py           # + register_invoicing
    invoicing.py          # invoices://, invoices://{invoice_id}/settlement
```

## Tool Surface — `tools/invoicing.py`

All arguments JSON-friendly primitives, mirroring `expense.py`: minor units as
`int`, `currency` ISO 4217, dates ISO-8601. FX rate as **integer basis points**
(×10000) for the same float-free reason minor units exist — `1.05` → `10500`,
domestic default `10000`. The domain takes a `Decimal`; `forms.rate_from_bp`
converts at the boundary.

- `issue_invoice(number: int, party_id: int, amount_minor: int, currency: str,
  issued_on: str, rate_bp: int = 10000) -> {invoice_id: int, number: int}`
  → `books.invoicing.issue_invoice(...)` → emits `InvoiceIssued` → GL
  `Dr AR / Cr Revenue` at the MYR carrying value. The customer Party
  (`party_id`) is mandatory provenance. The domain forces `rate=1` for MYR
  regardless of `rate_bp`.

- `mark_paid(invoice_id: int, paid_on: str, banked_minor: int | None = None,
  banked_currency: str = "MYR") -> {status: str}`
  → `books.invoicing.mark_paid(...)` → emits `PaymentRecorded`.
  `banked_minor=None` ⇒ the full carrying value landed (domestic case).
  Returns the resulting status: `"paid"` (banked ≥ carrying) or
  `"awaiting_adjudication"` (MYR shortfall, ADR-0005). `mark_paid` is the
  owner's human assertion that funds were seen (CONTEXT / ADR-0004); the agent
  relays it.

- `adjudicate_settlement(invoice_id: int, outcome: str, on: str)
  -> {status: str}`
  `outcome ∈ {"settled_in_full", "still_owes"}`.
  - `settled_in_full` → emits `SettlementAdjudicated`; the realized FX loss is
    posted by the Ledger's guided-journal path (ADR-0005/0006); status `paid`.
  - `still_owes` → AR stays open for the shortfall; status `partially_paid`.
  - any other outcome → `ValueError` (surfaces as `isError`).
  Per ADR-0019 the agent supplies the owner's explicit outcome; the system
  never auto-decides FX vs underpayment.

`mark_paid` returning the status (rather than a bare `{paid: True}`) is the one
deliberate shape difference from the expense tools: the status *is* the signal
the agent needs to know whether an adjudication step follows.

## Resource Surface — `resources/invoicing.py`

- `invoices://` — list rows:
  `{id, number, party_id, party_name, currency, amount_minor, carrying_minor,
  banked_minor, status}`. The agent's invoice-lookup across sessions, so
  `mark_paid` / `adjudicate_settlement` have an id to target.
- `invoices://{invoice_id}/settlement` — the `SettlementPicture`
  (`transaction_amount, carrying, banked, shortfall`), the both-numbers
  adjudication aid (ADR-0005). Backed by the existing
  `InvoicingService.settlement_picture`.

## Domain additions warranted by this surface

A single-context read, consistent with the expense spec's reasoning (a genuine
"list invoices" query belongs on the owning domain, not an interface cache; no
cross-context reads — Reporting remains the sole cross-table reader, ADR-0013):

- `InvoicingService.list_invoices() -> list[InvoiceView]` — new `InvoiceView`
  dataclass carrying the `invoices://` row fields. `party_name` is resolved via
  the already-injected `party_name` callable (no shared kernel, no
  cross-context import).
- `InvoiceRepository.all(session) -> list[...]` backing it.
- `InvoicingService.settlement_picture` already exists — reused, no change.

## Error translation

Unchanged from the expense rail: service-raised `LookupError` (unknown
`invoice_id` or `party_id`) and `ValueError` (unknown adjudication outcome)
surface to the MCP client as `isError: true` results via FastMCP. No special
handler.

## Testing (TDD — mirrors the project's rhythm)

- **`tests/test_mcp_invoicing_tracer.py`** — the spine, domestic:
  1. `register_party(name="Acme Sdn Bhd", role="customer")`
  2. set up AR control + Revenue accounts (mirrors existing invoicing tests)
  3. `issue_invoice(number=1001, party_id=<id>, amount_minor=500000,
     currency="MYR", issued_on="2026-02-01")`
  4. read `invoices://` — invoice present, status `issued`
  5. `mark_paid(invoice_id=<id>, paid_on="2026-02-20")` (full) → status `paid`
  6. read `postings://<AR_code>` — AR cleared by the payment posting
- **`tests/test_mcp_invoice_fx.py`** — foreign invoice + adjudication:
  - `issue_invoice(currency="SGD", rate_bp=31800, ...)` → MYR carrying booked
  - `mark_paid(..., banked_minor=<short MYR>)` → status `awaiting_adjudication`
  - read `invoices://{id}/settlement` — `shortfall` > 0, both numbers present
  - `adjudicate_settlement(outcome="settled_in_full")` → status `paid`,
    `SettlementAdjudicated` emitted / FX loss posted (assert via `postings://`)
  - separate case: `adjudicate_settlement(outcome="still_owes")` →
    `partially_paid`, AR remains open
- **`tests/test_mcp_errors.py`** (extend) — unknown `invoice_id`, unknown
  `party_id` at issue, bad `outcome` ⇒ `isError: true`, not a server crash.
- `tests/test_architecture.py` — no new contracts; the six still hold.

All tests inject in-memory `App`.

## Acceptance Criterion

`uv run pytest` green including the new `test_mcp_invoice*` files; `ruff`
clean; all six `import-linter` contracts pass in pre-commit and pytest. From a
Claude Desktop / Cowork JSON config, the agent can `register_party`,
`issue_invoice`, read `invoices://`, `mark_paid`, read the settlement picture,
and `adjudicate_settlement` end-to-end against `books.db`.

## Scope-outs (YAGNI for this tracer)

- No invoice void / edit / credit-note.
- No PDF / document generation (agent-side if ever).
- No reconciliation tools (separate increment).
- No ledger lifecycle tools (`soft_close` / `hard_close` / `write_off`).
- No HTTP transport, no auth — stdio, single owner.
