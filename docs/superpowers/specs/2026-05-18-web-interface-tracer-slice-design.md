# Web Interface — Tracer Slice (Design)

> Date: 2026-05-18
> Status: Approved (brainstorming) — pending implementation plan
> Companion to `docs/ARCHITECTURE.md`, `docs/PLAN-tracer-bullet-bank-reconciliation.md`, ADR-0011/0013.

## Goal

Add the first **web interface** as a thin adapter over the existing
composition root (`books.create_app() -> App`). Scope is a single
**tracer-bullet vertical slice** that mirrors the thread-1 acceptance test
(`tests/test_tracer_thread_1.py`) as clickable web pages, proving the
adapter pattern end-to-end before any thickening. The composition root
already states the intent: *"interfaces (web, MCP) will be thin adapters
over this same surface."*

Non-goal: exposing the full domain surface. This slice is the spine; more
use cases are later increments, and MCP reuses the same adapter pattern.

## Architecture & Boundary

### Package layout

```
src/books/interfaces/
  __init__.py
  web/
    __init__.py
    app.py            # create_web_app(books_app: App | None = None) -> Flask
    forms.py          # request -> domain parsing (Money, date, Decimal)
    routes/
      __init__.py     # register(flask_app): registers all blueprints
      setup.py         # setup_bp           — party + account creation
      invoicing.py     # invoicing_bp        — issue invoice, mark paid, adjudicate
      reconciliation.py# reconciliation_bp   — import CSV, propose, confirm
      reports.py       # reports_bp          — reconciliation report view
    templates/        # Jinja (djlint already configured for jinja profile)
    static/           # one minimal stylesheet
```

- `create_web_app(books_app: App | None = None)`: if no `App` is injected,
  calls `create_app(db_url="sqlite:///books.db")` once at construction and
  stores it on `flask_app.config["BOOKS"]`. One `App` per process;
  injectable for tests (tests inject an in-memory `App`).
- `routes/__init__.py` exposes a single `register(flask_app)` wiring point.
  Each blueprint is its own focused module — understandable and testable in
  isolation, thin over its corresponding `App` service(s).
- `forms.py`: hand-rolled parsing of request data into domain types. No
  WTForms (YAGNI).
- Blueprint URL prefixes mirror names: `/setup`, `/invoicing`,
  `/reconciliation`, `/reports`; landing page at `/`.

### Boundary enforcement (ADR-0013 consistent)

New `import-linter` contracts in `pyproject.toml`, wired into pre-commit
and `tests/test_architecture.py` like the existing three:

1. **interfaces is an outermost leaf (primary, fully enforced).** A
   `forbidden` contract: `books.platform` and all four contexts plus
   `books.reporting` must **not** import `books.interfaces`. This is the
   strong, unambiguous guarantee — nothing in the domain depends on the web
   layer.
2. **interfaces touches only the seam (scoped forbidden edges).**
   `books.interfaces` legitimately *must* import service modules and
   `books` (the composition root), so a blanket forbidden contract is not
   appropriate. Instead, a `forbidden` contract names the specific
   context-private table/aggregate modules as forbidden targets from
   `books.interfaces` (e.g. anything matching a context's internal
   persistence module). Concretely: as private modules are identified
   during implementation, each is added to this contract's forbidden list,
   the same incremental-whitelist discipline ADR-0013 already uses ("an
   unenforced boundary erodes silently"). The convention is reinforced by
   context internals (e.g. `_Invoice`) never being exported from a
   context's `__init__`.
3. The existing "reporting is a read-model leaf" contract is unchanged:
   `books.interfaces` is a *legitimate consumer* of reporting (it is not in
   that contract's forbidden source set).

### Dependency

Add `flask` to `[project.dependencies]`. Nothing else.

## Page & Route Flow (tracer slice)

Server-rendered Jinja, POST → redirect → GET. Maps step-for-step onto the
thread-1 acceptance test.

**Setup (`setup_bp`)** — prerequisites the acceptance test sets up
programmatically:
- `GET/POST /setup/parties` → `app.party.register_party(name, role)`
- `GET/POST /setup/accounts` → `app.ledger.create_account(code, name, type, control?)`
- `GET /` lists parties & accounts so the owner sees current state.

**Invoicing (`invoicing_bp`)**:
- `GET/POST /invoicing/issue` — number, party (dropdown), amount + currency,
  issue date, booking rate → `issue_invoice`.
- `GET /invoicing` — list invoices with status.
- `POST /invoicing/<id>/mark-paid` — paid date, optional banked MYR →
  `mark_paid`; then show `settlement_picture`. If a shortfall is open,
  surface the adjudication choice (`settled_in_full` / `still_owes`) →
  `adjudicate_settlement`. Exercises both increment-3 branches.

**Reconciliation (`reconciliation_bp`)**:
- `GET/POST /reconciliation/import` — account + period + CSV upload →
  `import_statement` (bytes + filename through the import ACL, ADR-0018).
- `GET /reconciliation/<account>/<period>` — statement lines +
  `propose_matches` candidates, a Confirm button per pair.
- `POST /reconciliation/confirm` — `statement_line_ref`,
  `ledger_posting_ref` → `confirm_match` (sole reconciliation write,
  ADR-0015).

**Reports (`reports_bp`)**:
- `GET /reports/reconciliation/<account>/<period>` — renders
  `reporting.reconciliation_report`: reconciled balance, confirmed cash,
  reconciling items with classification (timing vs stale).

**Errors:** a blueprint error handler catches service-raised
`ValueError`/`LookupError` (closed-period guard, unknown invoice, duplicate
match) and re-renders the form with a flash message — no 500. Domain
invariants stay in the domain; the web layer only translates them.

## Testing (TDD — mirrors the project spine)

- `tests/test_web_tracer.py` — Flask **test client** drives the full slice:
  create party → create accounts → issue invoice → mark paid → upload
  January CSV → propose → confirm → assert the reconciliation report page
  shows the reconciled balance and zero reconciling items. The web mirror
  of `test_tracer_thread_1.py`; it is the spine of this increment.
- Per-blueprint tests (`test_web_invoicing.py`,
  `test_web_reconciliation.py`, …) for edge cases: closed-period rejection
  renders a flash, not a 500; duplicate `confirm_match` rejected; the
  increment-3 shortfall path offers both adjudication outcomes.
- All tests inject an **in-memory** `App`
  (`create_web_app(create_app("sqlite://"))`) for isolation and speed; the
  file-backed default applies only to the real run.
- Routes written test-first, red → green (TDD).
- `tests/test_architecture.py` extended to assert the new import-linter
  contracts hold.

## Lifecycle / Running

- Add a `books-web` console script → `create_web_app().run()`.
  `uv run books-web` serves on localhost with file-backed
  `sqlite:///books.db` in the working directory.
- Dev server only — production WSGI is out of scope for this increment.

## Scope-outs (YAGNI for v1)

- No authentication / multi-user — single local owner, self-service.
- No JS / HTMX — plain server-rendered forms.
- No styling beyond one minimal stylesheet for legibility.
- No MCP interface — separate future increment (reuses this adapter pattern).
- No edit/delete of past records — append-only, matching the immutable
  domain (ADR-0010).
- No pagination / search — unnecessary at tracer scale.

## Acceptance Criterion

`uv run pytest` green including `tests/test_web_tracer.py`; `ruff` clean;
all import-linter contracts (existing three + the two new interface
contracts) pass in both pre-commit and pytest. The slice is clickable end
to end via `uv run books-web`.
