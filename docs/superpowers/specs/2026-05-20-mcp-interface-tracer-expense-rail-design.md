# MCP Interface — Tracer Slice (Expense Rail, Design)

> Date: 2026-05-20
> Status: Approved (brainstorming) — pending implementation plan
> Companion to `docs/ARCHITECTURE.md`, the web tracer spec
> (`docs/superpowers/specs/2026-05-18-web-interface-tracer-slice-design.md`),
> and ADR-0003 / ADR-0011 / ADR-0013 / ADR-0015.

## Goal

Add the first **MCP interface** as a thin adapter over the existing
composition root (`books.create_app() -> App`). Scope is a single
tracer-bullet vertical slice that proves the adapter pattern end-to-end
for the project's primary MCP use case: **an LLM agent (Claude Cowork)
submits an expense to the books from an invoice image.**

The composition root already states the intent: *"interfaces (web, MCP)
will be thin adapters over this same surface."* This increment is the
MCP-shaped parallel of the web tracer slice, deliberately scoped to the
expense rail rather than thread-1's invoicing/reconciliation spine —
expense submission is the natural agent verb (single-action, write-heavy),
whereas reconciliation is human-driven adjudication (ADR-0015). The
reconciliation rail is the next increment, sketched at the end of this
document.

Non-goal: exposing the full domain surface. This slice is the spine; more
use cases (reconciliation, ledger lifecycle) are later increments.

## Architecture & Boundary

### Approach

Use the official `mcp` Python SDK's **`FastMCP`** high-level API
(`@mcp.tool()` / `@mcp.resource()` decorators). Rejected alternatives:
the low-level `Server` class (more boilerplate, no payoff at tracer
scope) and a hand-rolled JSON-RPC stdio loop (YAGNI — the SDK is small
and the spec is a moving target). FastMCP also ships an in-memory
client/server pair
(`mcp.shared.memory.create_connected_server_and_client_session`) which
removes the need for subprocess-based integration tests.

### Package layout

```
src/books/interfaces/mcp/
  __init__.py
  app.py                  # create_mcp_server(books_app: App | None = None) -> FastMCP
  forms.py                # JSON args -> domain types (Money, date, Decimal)
  tools/
    __init__.py           # register(mcp, books_provider): wires all tool modules
    setup.py              # register_party, create_account
    expense.py            # record_owner_paid_expense, pay_contractor, reimburse_owner
  resources/
    __init__.py           # register(mcp, books_provider)
    setup.py              # parties://, accounts://
    postings.py           # postings://{account_code}
```

- `create_mcp_server(books_app=None)`: if no `App` is injected, calls
  `create_app(db_url="sqlite:///books.db")` once at construction and
  holds it in a closure captured by every tool/resource handler. One
  `App` per process; injectable for tests. Mirrors the web layer's
  `create_web_app` shape.
- `tools/__init__.py` and `resources/__init__.py` each expose a single
  `register(mcp, books_provider)` wiring point. Each module is focused
  and understandable in isolation — thin over its corresponding `App`
  service(s). Parallels the web blueprint structure.
- `forms.py`: hand-rolled parsing of MCP JSON args into domain types
  (`Money`, `date`, `Decimal`). Kept separate from the web `forms.py`
  to avoid coupling; revisit factoring if real duplication appears.

### Coexistence with the web interface

Separate processes, same SQLite file (`sqlite:///books.db`). SQLite
handles concurrent readers and one writer at a time, which is fine for a
single-owner self-service tool. `books-web` and `books-mcp` are
independent entry points.

### Boundary enforcement (ADR-0013 consistent)

**No new `import-linter` contracts needed.** The existing two interface
contracts (added by the web tracer) already match against
`books.interfaces.*`, so `books.interfaces.mcp` is covered the moment
the package exists:

1. *"interfaces is an outermost leaf"* — `books.platform` and all four
   contexts plus `books.reporting` must not import `books.interfaces`.
   Naturally extends to the new MCP subtree.
2. *"interfaces touches only the seam"* — `books.interfaces.*` cannot
   import context-private modules; only service APIs. Same scoped
   forbidden list, same incremental-whitelist discipline.

`tests/test_architecture.py` already asserts both contracts hold; the
MCP code just has to live within them.

### Dependency

Add `mcp` (the official Python SDK) to `[project.dependencies]`.

## Tool & Resource Surface (expense rail)

The agent's workflow shapes the surface. Image parsing happens entirely
on the Claude / Cowork side; the MCP server only receives structured
fields.

1. Agent extracts `{supplier_name, amount, date, category_hint, who_paid}`
   from the invoice image.
2. Agent reads `parties://` to find the supplier; if missing, calls
   `register_party`.
3. Agent reads `accounts://` to find the category account; if missing,
   calls `create_account` (or surfaces to the human — policy, not surface).
4. Agent calls **either** `record_owner_paid_expense` (owner used personal
   card) **or** `pay_contractor` (business paid directly) per ADR-0003's
   two buy-side rails.
5. Agent optionally reads `postings://{account_code}` to verify the
   resulting GL posting.

### Tools

**setup/**

- `register_party(name: str, role: str) -> {id: int, name: str, role: str}`
  Typically `role="supplier"` for this flow.
- `create_account(code: str, name: str, type: str, control: bool = False)`
  For new category accounts (`type="expense"`).

**expense/**

- `record_owner_paid_expense(party_id: int, amount_minor: int,
  currency: str, category_account: str, on: str)`
  → emits `OwnerPaidExpenseRecorded` → GL `Dr <category> / Cr Due to
  Owner`. Supplier Party mandatory (provenance) per the
  expense_management domain correction.
- `pay_contractor(party_id: int, amount_minor: int, currency: str,
  category_account: str, on: str)`
  → emits `ContractorPaid` → GL `Dr <category> / Cr Bank`. Cash basis
  per ADR-0003.
- `reimburse_owner(amount_minor: int, currency: str, on: str)`
  → emits `OwnerReimbursed` → GL `Dr Due to Owner / Cr Bank`. Included
  for surface completeness with ADR-0003's rail; covered by a unit
  test, not the tracer spine.

Argument conventions: minor units as `int` to avoid float/string
ambiguity; `currency` ISO 4217 three-letter; `on` ISO-8601 date string.

### Resources

- `parties://` — all parties (the agent's supplier lookup).
- `accounts://` — all GL accounts (the agent's category lookup).
- `postings://{account_code}` — `ledger.postings_for(code)` output,
  including dimensions (Party) and provenance.

### Domain additions warranted by this surface

Two small additions to existing services, both single-context queries
that fit inside the owning service (no cross-context reads — Reporting
remains the sole cross-table reader per ADR-0013):

- `PartyService.list() -> list[Party]`
- `LedgerService.accounts() -> list[Account]`

Chosen over the web tracer's `_seen`-registry workaround because for an
LLM agent, "list parties" / "list accounts" is a genuine read query
that belongs on the domain, not an interface-private cache.

### Error translation

FastMCP turns Python exceptions raised inside tool handlers into
`isError: true` tool results with the exception message as content.
Service-raised `ValueError` / `LookupError` (closed-period guard,
unknown party, unknown account) therefore surface to the MCP client as
structured errors. Domain invariants stay in the domain; the MCP layer
only translates. No special handler beyond what FastMCP provides.

## Testing (TDD — mirrors the project's rhythm)

- **`tests/test_mcp_expense_tracer.py`** — the spine. Uses
  `mcp.shared.memory.create_connected_server_and_client_session` to
  drive end-to-end:
  1. `register_party(name="Stationery Co", role="supplier")` via tool
  2. `create_account(code="5100", name="Office Supplies", type="expense")` via tool
  3. Read `parties://` resource — Stationery Co present
  4. Read `accounts://` resource — 5100 present
  5. `record_owner_paid_expense(party_id=<id>, amount_minor=12345,
     currency="MYR", category_account="5100", on="2026-01-15")` via tool
  6. Read `postings://5100` resource — Dr posting present with
     `Party=Stationery Co` dimension
  7. Read `postings://<due_to_owner_code>` — Cr posting present, balance
     updated

  The MCP mirror of `test_owner_reimbursable_expense.py` in spirit.

- `tests/test_mcp_contractor.py` — second rail acceptance, parallels
  `test_contractor_payment.py`.
- `tests/test_mcp_errors.py` — service-raised exceptions surface as
  `isError: true` tool results, not server crashes. Cases: unknown
  `party_id`, unknown `category_account`, closed-period rejection.
- `tests/test_mcp_reimburse.py` — full owner-paid → reimburse loop, so
  the rail is closed in tests even though it isn't on the agent's
  tracer flow.

All tests inject in-memory `App` (`create_mcp_server(create_app("sqlite://"))`).

`tests/test_architecture.py` — no new contracts; confirms the existing
six still hold once MCP code lands.

## Lifecycle / Running

- Console script `books-mcp` → `create_mcp_server().run()` (stdio).
  `uv run books-mcp` serves over stdio with file-backed
  `sqlite:///books.db` in the working directory.
- README snippet for Claude Desktop / Cowork JSON config:

  ```json
  {
    "command": "uv",
    "args": ["--directory", "<absolute-path-to-books>", "run", "books-mcp"]
  }
  ```

- stdio only — HTTP transport is out of scope for this increment.

## Scope-outs (YAGNI for this tracer)

- No invoicing tools (out of slice).
- No reconciliation tools (next increment; sketched below).
- No `soft_close` / `hard_close` / `write_off` tools (ledger lifecycle,
  separate increment).
- No MCP prompt templates.
- No HTTP transport.
- No authentication — stdio, single owner.
- No PDF / image parsing — always agent-side; books MCP only receives
  structured data.

## Acceptance Criterion

`uv run pytest` green including all new `test_mcp_*` files; `ruff`
clean; all six existing `import-linter` contracts pass in both
pre-commit and pytest. `uv run books-mcp` launches over stdio and the
expense submission flow works end-to-end against `books.db` from a
Claude Desktop / Cowork JSON config.

## Next Increment Sketch — Reconciliation Rail

Out of *this* increment's build scope, but documented here so the
design is committed and the second use case (Claude Cowork parses a PDF
bank statement and performs matching) is not lost.

**Tools (added under `interfaces/mcp/tools/reconciliation.py`):**

- `import_statement(account: str, period: str, opening_minor: int,
  closing_minor: int, raw_csv: str)` — the agent parses the PDF on the
  Cowork side and passes canonical CSV-shaped text. Same idempotency /
  content-hash behaviour as the web import (ADR-0018).
- `propose_matches(account: str, period: str) -> list[Proposal]` —
  side-effect-free (ADR-0015).
- `confirm_match(statement_line_ref: int, ledger_posting_ref: int)` —
  the sole reconciliation write. **One explicit pair per call;
  LLM-asserted is fine** — ADR-0015's "explicit-pair, no batch /
  auto-confirm" contract is actor-agnostic. The MCP wrapper receives
  the explicit pair from the agent and calls `confirm_match` exactly as
  a human via the web does.

**Resources (added under `interfaces/mcp/resources/`):**

- `statements://{account}/{period}/lines`
- `reports://reconciliation/{account}/{period}`

**Acceptance:** the agent imports a small CSV-shaped bank statement,
calls `propose_matches`, calls `confirm_match` on the proposed pair,
reads the report resource — reconciled balance correct, zero
reconciling items. No new `import-linter` contracts.

**ADR consideration to flag (not blocking):** ADR-0015 doesn't
currently say *who* asserts the explicit pair. The contract is
operationally actor-agnostic, but a short ADR amendment noting that
LLM-asserted pairs are legitimate (provenance preserved either way)
would close the question explicitly. Decide when the reconciliation
increment is built.
