# Web Interface (Tracer Slice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Flask+Jinja web interface as a thin adapter over `books.create_app()`, scoped to a single tracer-bullet vertical slice mirroring the thread-1 acceptance test.

**Architecture:** New `src/books/interfaces/web/` package. `create_web_app(books_app)` builds a Flask app holding one `App` in `config["BOOKS"]`. One blueprint module per workflow area under `routes/`. Routes call only `App` service methods and view DTOs. Boundary enforced by import-linter (interfaces is an outermost leaf; context-private modules forbidden as targets).

**Tech Stack:** Python 3.13, Flask, Jinja2, SQLAlchemy (existing), pytest, import-linter, uv.

---

## File Structure

- `src/books/interfaces/__init__.py` — empty package marker.
- `src/books/interfaces/web/__init__.py` — empty package marker.
- `src/books/interfaces/web/app.py` — `create_web_app`, `current_books()` helper, error handler.
- `src/books/interfaces/web/forms.py` — request→domain parsing helpers.
- `src/books/interfaces/web/routes/__init__.py` — `register(flask_app)` wiring point.
- `src/books/interfaces/web/routes/setup.py` — `setup_bp`: parties, accounts, landing.
- `src/books/interfaces/web/routes/invoicing.py` — `invoicing_bp`: issue, list, mark-paid, adjudicate.
- `src/books/interfaces/web/routes/reconciliation.py` — `reconciliation_bp`: import, propose, confirm.
- `src/books/interfaces/web/routes/reports.py` — `reports_bp`: reconciliation report.
- `src/books/interfaces/web/templates/*.html` — Jinja templates.
- `src/books/interfaces/web/static/app.css` — minimal stylesheet.
- `tests/test_web_*.py` — per-blueprint tests + `test_web_tracer.py` acceptance.
- `pyproject.toml` — add `flask` dep, `books-web` script, two import-linter contracts.
- `tests/test_architecture.py` — assert new contracts (uses existing pattern).

---

## Task 1: Package skeleton, `create_web_app`, landing page

**Files:**
- Modify: `pyproject.toml` (add `flask` to `[project.dependencies]`)
- Create: `src/books/interfaces/__init__.py`
- Create: `src/books/interfaces/web/__init__.py`
- Create: `src/books/interfaces/web/app.py`
- Create: `src/books/interfaces/web/routes/__init__.py`
- Create: `src/books/interfaces/web/routes/setup.py`
- Create: `src/books/interfaces/web/templates/base.html`
- Create: `src/books/interfaces/web/templates/landing.html`
- Create: `src/books/interfaces/web/static/app.css`
- Test: `tests/test_web_app.py`

- [ ] **Step 1: Add Flask dependency**

Run:
```bash
uv add flask
```
Expected: `flask` appears under `[project.dependencies]` in `pyproject.toml`; lockfile updates.

- [ ] **Step 2: Write the failing test**

Create `tests/test_web_app.py`:
```python
from books import create_app
from books.interfaces.web.app import create_web_app


def _client():
    return create_web_app(create_app("sqlite://")).test_client()


def test_landing_page_renders_and_lists_empty_state():
    resp = _client().get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "books" in body
    # No parties or accounts registered yet.
    assert "No parties yet" in body
    assert "No accounts yet" in body
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_web_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'books.interfaces'`.

- [ ] **Step 4: Create package markers**

Create `src/books/interfaces/__init__.py` (empty file).
Create `src/books/interfaces/web/__init__.py` (empty file).

- [ ] **Step 5: Implement `app.py`**

Create `src/books/interfaces/web/app.py`:
```python
"""Web interface composition (design: web-interface-tracer-slice).

A thin Flask adapter over the existing composition root. One App per
process, held on the Flask config; injectable so tests use in-memory.
The web layer only translates HTTP <-> service calls; domain invariants
stay in the domain (service-raised ValueError/LookupError -> flash).
"""

from __future__ import annotations

from flask import Flask, current_app, flash, redirect, request

from books import App, create_app


def current_books() -> App:
    return current_app.config["BOOKS"]


def create_web_app(books_app: App | None = None) -> Flask:
    flask_app = Flask(__name__)
    flask_app.secret_key = "books-dev-not-secret"  # dev-only; no auth (v1)
    flask_app.config["BOOKS"] = books_app or create_app(db_url="sqlite:///books.db")

    from books.interfaces.web.routes import register

    register(flask_app)

    @flask_app.errorhandler(ValueError)
    @flask_app.errorhandler(LookupError)
    def _domain_error(exc: Exception):
        # Domain rejected the command (closed period, unknown id, duplicate
        # match, ...). Re-show the page the user came from with the message.
        flash(str(exc))
        return redirect(request.referrer or "/")

    return flask_app
```

- [ ] **Step 6: Implement `routes/__init__.py`**

Create `src/books/interfaces/web/routes/__init__.py`:
```python
"""Single blueprint wiring point. Each blueprint is its own focused
module (one workflow area) registered here."""

from __future__ import annotations

from flask import Flask


def register(flask_app: Flask) -> None:
    from books.interfaces.web.routes.setup import setup_bp

    flask_app.register_blueprint(setup_bp)
```

- [ ] **Step 7: Implement `routes/setup.py` (landing only for now)**

Create `src/books/interfaces/web/routes/setup.py`:
```python
"""setup_bp — landing page plus party/account prerequisites."""

from __future__ import annotations

from flask import Blueprint, render_template

from books.interfaces.web.app import current_books

setup_bp = Blueprint("setup", __name__)


@setup_bp.get("/")
def landing():
    books = current_books()
    # Party/Ledger expose no "list all" API in the tracer; the landing
    # page reads what the slice needs via the reporting/query surface as
    # it is added. For now show empty-state scaffolding.
    parties: list = []
    accounts: list = []
    return render_template("landing.html", parties=parties, accounts=accounts)
```

- [ ] **Step 8: Create templates and stylesheet**

Create `src/books/interfaces/web/templates/base.html`:
```html
<!doctype html>
<title>books</title>
<link rel="stylesheet" href="{{ url_for('static', filename='app.css') }}">
<header><a href="/">books</a></header>
{% with messages = get_flashed_messages() %}
  {% if messages %}
    <ul class="flash">
      {% for m in messages %}<li>{{ m }}</li>{% endfor %}
    </ul>
  {% endif %}
{% endwith %}
<main>{% block body %}{% endblock %}</main>
```

Create `src/books/interfaces/web/templates/landing.html`:
```html
{% extends "base.html" %}
{% block body %}
  <h1>books</h1>
  <h2>Parties</h2>
  {% if parties %}
    <ul>{% for p in parties %}<li>{{ p.name }}</li>{% endfor %}</ul>
  {% else %}
    <p>No parties yet</p>
  {% endif %}
  <h2>Accounts</h2>
  {% if accounts %}
    <ul>{% for a in accounts %}<li>{{ a.code }} — {{ a.name }}</li>{% endfor %}</ul>
  {% else %}
    <p>No accounts yet</p>
  {% endif %}
{% endblock %}
```

Create `src/books/interfaces/web/static/app.css`:
```css
body { font-family: system-ui, sans-serif; margin: 2rem; max-width: 50rem; }
header { margin-bottom: 1rem; font-weight: bold; }
.flash { background: #fee; padding: .5rem 1rem; border: 1px solid #c33; }
table { border-collapse: collapse; }
td, th { border: 1px solid #ccc; padding: .25rem .5rem; }
form { margin: 1rem 0; }
label { display: block; margin: .25rem 0; }
```

- [ ] **Step 9: Run test to verify it passes**

Run: `uv run pytest tests/test_web_app.py -v`
Expected: PASS.

- [ ] **Step 10: Run full suite + ruff**

Run: `uv run pytest --timeout=30 -q && uv run ruff check .`
Expected: all pass, ruff clean.

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml uv.lock src/books/interfaces tests/test_web_app.py
git commit -m "feat(web): Flask app skeleton + landing page

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: import-linter boundary contracts

**Files:**
- Modify: `pyproject.toml` (add two `[[tool.importlinter.contracts]]`)
- Modify: `tests/test_architecture.py`

- [ ] **Step 1: Inspect how architecture is currently tested**

Run: `uv run cat tests/test_architecture.py` (or open it).
Expected: it shells out to `lint-imports` / asserts the import-linter run is clean. Mirror that exact pattern — do not invent a new mechanism.

- [ ] **Step 2: Add the two contracts to `pyproject.toml`**

Append after the existing `reporting is a read-model leaf` contract:
```toml
# interfaces/ is the outermost adapter leaf: nothing in the domain may
# depend on it (design: web-interface-tracer-slice; ADR-0013 discipline).
[[tool.importlinter.contracts]]
name = "interfaces is an outermost leaf (nothing depends on it)"
type = "forbidden"
source_modules = [
    "books.platform",
    "books.party",
    "books.invoicing",
    "books.general_ledger",
    "books.bank_reconciliation",
    "books.reporting",
]
forbidden_modules = ["books.interfaces"]

# interfaces/ may use the composition root + service APIs, but must never
# reach into a context's private persistence/aggregate modules. Each such
# private module is named here as a forbidden target (incremental
# whitelist discipline, same as the cross-context seam list above).
[[tool.importlinter.contracts]]
name = "interfaces touches only the service seam (no context internals)"
type = "forbidden"
source_modules = ["books.interfaces"]
forbidden_modules = []
```
(`forbidden_modules = []` is intentional: there are no separate private modules today — context internals live inside each `service.py` and are not importable as distinct modules. The contract exists so any *future* private module split is a deliberate addition here, not a silent erosion.)

- [ ] **Step 3: Run import-linter to verify all contracts pass**

Run: `uv run lint-imports`
Expected: all contracts (3 existing + 2 new) report `KEPT`.

- [ ] **Step 4: Extend the architecture test**

In `tests/test_architecture.py`, follow the file's existing pattern. If it asserts a fixed count of kept contracts, bump it; if it asserts the run exits 0, no change is needed beyond confirming the new contracts are present. Add (adapting names to the file's existing assertion style):
```python
def test_interfaces_is_an_outermost_leaf():
    # The import-linter run (asserted clean elsewhere in this file)
    # now includes the two interfaces contracts; this test documents
    # the intent and fails loudly if the contract names are removed.
    import tomllib
    from pathlib import Path

    cfg = tomllib.loads(Path("pyproject.toml").read_text())
    names = {c["name"] for c in cfg["tool"]["importlinter"]["contracts"]}
    assert "interfaces is an outermost leaf (nothing depends on it)" in names
    assert "interfaces touches only the service seam (no context internals)" in names
```

- [ ] **Step 5: Run architecture test + full suite**

Run: `uv run pytest tests/test_architecture.py -v && uv run pytest --timeout=30 -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/test_architecture.py
git commit -m "feat(web): enforce interfaces boundary via import-linter

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Setup blueprint — parties & accounts

**Files:**
- Create: `src/books/interfaces/web/forms.py`
- Modify: `src/books/interfaces/web/routes/setup.py`
- Create: `src/books/interfaces/web/templates/parties.html`
- Create: `src/books/interfaces/web/templates/accounts.html`
- Test: `tests/test_web_setup.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_web_setup.py`:
```python
from books import create_app
from books.interfaces.web.app import create_web_app


def _client():
    return create_web_app(create_app("sqlite://")).test_client()


def test_register_party_then_it_shows_on_landing():
    c = _client()
    resp = c.post("/setup/parties", data={"name": "Acme", "role": "customer"},
                  follow_redirects=True)
    assert resp.status_code == 200
    assert "Acme" in resp.get_data(as_text=True)


def test_create_account_then_it_shows_on_landing():
    c = _client()
    resp = c.post("/setup/accounts",
                  data={"code": "Bank", "name": "Bank", "type": "asset"},
                  follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Bank" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_web_setup.py -v`
Expected: FAIL — 404 on `/setup/parties` (route absent).

- [ ] **Step 3: Implement `forms.py`**

Create `src/books/interfaces/web/forms.py`:
```python
"""Request -> domain parsing. Kept tiny and explicit (no WTForms)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from books.platform.money import Currency, Money


def money_from(amount: str, currency: str = "MYR") -> Money:
    minor = int((Decimal(amount) * 100).to_integral_value())
    return Money(minor, Currency(currency))


def date_from(value: str) -> date:
    return date.fromisoformat(value)


def decimal_from(value: str) -> Decimal:
    return Decimal(value)
```

- [ ] **Step 4: Track registered parties/accounts for the landing view**

The Party and Ledger services expose no "list all" API and adding one is
out of this slice's scope. The web layer keeps a thin in-process view
cache of what *it* created, recorded on the Flask config. Replace
`src/books/interfaces/web/routes/setup.py` with:
```python
"""setup_bp — landing page plus party/account prerequisites.

Party/Ledger have no list-all query in the tracer scope; the web layer
keeps a small in-process registry of what it created so the owner can
see current state. This is a view convenience, not domain state.
"""

from __future__ import annotations

from flask import Blueprint, current_app, redirect, render_template, request, url_for

from books.interfaces.web.app import current_books

setup_bp = Blueprint("setup", __name__, url_prefix="")


def _seen(kind: str) -> list:
    return current_app.config.setdefault("_SEEN", {}).setdefault(kind, [])


@setup_bp.get("/")
def landing():
    return render_template(
        "landing.html", parties=_seen("parties"), accounts=_seen("accounts")
    )


@setup_bp.get("/setup/parties")
def parties_form():
    return render_template("parties.html")


@setup_bp.post("/setup/parties")
def register_party():
    party = current_books().party.register_party(
        name=request.form["name"], role=request.form["role"]
    )
    _seen("parties").append({"id": party.id, "name": party.name})
    return redirect(url_for("setup.landing"))


@setup_bp.get("/setup/accounts")
def accounts_form():
    return render_template("accounts.html")


@setup_bp.post("/setup/accounts")
def create_account():
    code = request.form["code"]
    current_books().ledger.create_account(
        code=code,
        name=request.form["name"],
        type=request.form["type"],
        control=bool(request.form.get("control")),
    )
    _seen("accounts").append({"code": code, "name": request.form["name"]})
    return redirect(url_for("setup.landing"))
```

- [ ] **Step 5: Create the two form templates**

Create `src/books/interfaces/web/templates/parties.html`:
```html
{% extends "base.html" %}
{% block body %}
  <h1>Register party</h1>
  <form method="post" action="/setup/parties">
    <label>Name <input name="name" required></label>
    <label>Role
      <select name="role">
        <option value="customer">customer</option>
        <option value="supplier">supplier</option>
      </select>
    </label>
    <button type="submit">Register</button>
  </form>
{% endblock %}
```

Create `src/books/interfaces/web/templates/accounts.html`:
```html
{% extends "base.html" %}
{% block body %}
  <h1>Create account</h1>
  <form method="post" action="/setup/accounts">
    <label>Code <input name="code" required></label>
    <label>Name <input name="name" required></label>
    <label>Type
      <select name="type">
        <option value="asset">asset</option>
        <option value="income">income</option>
        <option value="expense">expense</option>
        <option value="liability">liability</option>
        <option value="equity">equity</option>
      </select>
    </label>
    <label><input type="checkbox" name="control" value="1"> Control account</label>
    <button type="submit">Create</button>
  </form>
{% endblock %}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_web_setup.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Run full suite + ruff + import-linter**

Run: `uv run pytest --timeout=30 -q && uv run ruff check . && uv run lint-imports`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/books/interfaces tests/test_web_setup.py
git commit -m "feat(web): setup blueprint — party & account forms

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Invoicing blueprint — issue, list, mark-paid, adjudicate

**Files:**
- Modify: `src/books/interfaces/web/routes/__init__.py`
- Create: `src/books/interfaces/web/routes/invoicing.py`
- Create: `src/books/interfaces/web/templates/invoice_issue.html`
- Create: `src/books/interfaces/web/templates/invoice_paid.html`
- Test: `tests/test_web_invoicing.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_web_invoicing.py`:
```python
from books import create_app
from books.interfaces.web.app import create_web_app


def _app_client():
    books = create_app("sqlite://")
    return books, create_web_app(books).test_client()


def _setup(books):
    acme = books.party.register_party(name="Acme", role="customer")
    books.ledger.create_account(code="Bank", name="Bank", type="asset")
    books.ledger.create_account(code="AR", name="AR", type="asset", control=True)
    books.ledger.create_account(code="Revenue", name="Revenue", type="income")
    books.ledger.create_account(code="FX Loss", name="FX Loss", type="expense")
    return acme


def test_issue_invoice_posts_to_ledger():
    books, c = _app_client()
    acme = _setup(books)
    resp = c.post("/invoicing/issue", data={
        "number": "1", "party_id": str(acme.id), "amount": "1000.00",
        "currency": "MYR", "issued_on": "2026-01-10", "rate": "1",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert books.ledger.account_balance(code="AR").minor_units == 1000_00


def test_mark_paid_shortfall_then_adjudicate_still_owes_keeps_ar_open():
    books, c = _app_client()
    acme = _setup(books)
    c.post("/invoicing/issue", data={
        "number": "1", "party_id": str(acme.id), "amount": "1000.00",
        "currency": "SGD", "issued_on": "2026-01-10", "rate": "3.20",
    })
    c.post("/invoicing/1/mark-paid", data={
        "paid_on": "2026-01-20", "banked": "3180.00",
    })
    resp = c.post("/invoicing/1/adjudicate", data={
        "outcome": "still_owes", "on": "2026-01-25",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert books.ledger.account_balance(code="AR").minor_units == 20_00
    assert books.ledger.account_balance(code="FX Loss").minor_units == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_web_invoicing.py -v`
Expected: FAIL — 404 on `/invoicing/issue`.

- [ ] **Step 3: Register the invoicing blueprint**

Edit `src/books/interfaces/web/routes/__init__.py`, replace the body of `register` with:
```python
def register(flask_app: Flask) -> None:
    from books.interfaces.web.routes.invoicing import invoicing_bp
    from books.interfaces.web.routes.setup import setup_bp

    flask_app.register_blueprint(setup_bp)
    flask_app.register_blueprint(invoicing_bp)
```

- [ ] **Step 4: Implement `routes/invoicing.py`**

Create `src/books/interfaces/web/routes/invoicing.py`:
```python
"""invoicing_bp — issue invoice, list, mark paid, adjudicate FX shortfall.

The invoice id used in URLs is the value returned by issue_invoice.
"""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from books.interfaces.web.app import current_books
from books.interfaces.web.forms import date_from, decimal_from, money_from

invoicing_bp = Blueprint("invoicing", __name__, url_prefix="/invoicing")


@invoicing_bp.get("/issue")
def issue_form():
    return render_template("invoice_issue.html")


@invoicing_bp.post("/issue")
def issue():
    books = current_books()
    inv = books.invoicing.issue_invoice(
        number=int(request.form["number"]),
        party_id=int(request.form["party_id"]),
        amount=money_from(request.form["amount"], request.form["currency"]),
        issued_on=date_from(request.form["issued_on"]),
        rate=decimal_from(request.form["rate"]),
    )
    return redirect(url_for("invoicing.paid_form", invoice_id=inv.id))


@invoicing_bp.get("/<int:invoice_id>/mark-paid")
def paid_form(invoice_id: int):
    return render_template("invoice_paid.html", invoice_id=invoice_id,
                           picture=None)


@invoicing_bp.post("/<int:invoice_id>/mark-paid")
def mark_paid(invoice_id: int):
    books = current_books()
    raw = request.form.get("banked")
    banked = money_from(raw, "MYR") if raw else None
    books.invoicing.mark_paid(
        invoice_id=invoice_id,
        paid_on=date_from(request.form["paid_on"]),
        banked=banked,
    )
    picture = books.invoicing.settlement_picture(invoice_id)
    return render_template("invoice_paid.html", invoice_id=invoice_id,
                           picture=picture)


@invoicing_bp.post("/<int:invoice_id>/adjudicate")
def adjudicate(invoice_id: int):
    current_books().invoicing.adjudicate_settlement(
        invoice_id=invoice_id,
        outcome=request.form["outcome"],
        on=date_from(request.form["on"]),
    )
    return redirect(url_for("setup.landing"))
```

- [ ] **Step 5: Create templates**

Create `src/books/interfaces/web/templates/invoice_issue.html`:
```html
{% extends "base.html" %}
{% block body %}
  <h1>Issue invoice</h1>
  <form method="post" action="/invoicing/issue">
    <label>Number <input name="number" type="number" required></label>
    <label>Party id <input name="party_id" type="number" required></label>
    <label>Amount <input name="amount" required></label>
    <label>Currency
      <select name="currency">
        <option value="MYR">MYR</option>
        <option value="SGD">SGD</option>
      </select>
    </label>
    <label>Issued on <input name="issued_on" type="date" required></label>
    <label>Booking rate <input name="rate" value="1" required></label>
    <button type="submit">Issue</button>
  </form>
{% endblock %}
```

Create `src/books/interfaces/web/templates/invoice_paid.html`:
```html
{% extends "base.html" %}
{% block body %}
  <h1>Invoice {{ invoice_id }}</h1>
  {% if picture is none %}
    <form method="post" action="/invoicing/{{ invoice_id }}/mark-paid">
      <label>Paid on <input name="paid_on" type="date" required></label>
      <label>Banked MYR (blank = full carrying)
        <input name="banked"></label>
      <button type="submit">Mark paid</button>
    </form>
  {% else %}
    <table>
      <tr><th>Transaction</th><td>{{ picture.transaction_amount.minor_units }}</td></tr>
      <tr><th>Carrying MYR</th><td>{{ picture.carrying.minor_units }}</td></tr>
      <tr><th>Banked MYR</th><td>{{ picture.banked.minor_units }}</td></tr>
      <tr><th>Shortfall MYR</th><td>{{ picture.shortfall.minor_units }}</td></tr>
    </table>
    {% if picture.shortfall.minor_units > 0 %}
      <h2>Adjudicate the shortfall</h2>
      <form method="post" action="/invoicing/{{ invoice_id }}/adjudicate">
        <label>Outcome
          <select name="outcome">
            <option value="settled_in_full">settled in full (realized FX loss)</option>
            <option value="still_owes">still owes (AR stays open)</option>
          </select>
        </label>
        <label>On <input name="on" type="date" required></label>
        <button type="submit">Adjudicate</button>
      </form>
    {% endif %}
  {% endif %}
{% endblock %}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_web_invoicing.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Run full suite + ruff + import-linter**

Run: `uv run pytest --timeout=30 -q && uv run ruff check . && uv run lint-imports`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/books/interfaces tests/test_web_invoicing.py
git commit -m "feat(web): invoicing blueprint — issue, mark paid, adjudicate

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Reconciliation blueprint — import CSV, propose, confirm

**Files:**
- Modify: `src/books/interfaces/web/routes/__init__.py`
- Create: `src/books/interfaces/web/routes/reconciliation.py`
- Create: `src/books/interfaces/web/templates/import_statement.html`
- Create: `src/books/interfaces/web/templates/reconcile.html`
- Test: `tests/test_web_reconciliation.py`

- [ ] **Step 1: Write the failing test**

The CSV format parsed by the import ACL is `date,amount,description` with
a header line skipped; amount is decimal currency units. A "Bank" ledger
posting is created by paying an invoice.

Create `tests/test_web_reconciliation.py`:
```python
from books import create_app
from books.interfaces.web.app import create_web_app


def _app_client():
    books = create_app("sqlite://")
    return books, create_web_app(books).test_client()


def test_import_then_propose_then_confirm_matches_bank_posting():
    books, c = _app_client()
    acme = books.party.register_party(name="Acme", role="customer")
    books.ledger.create_account(code="Bank", name="Bank", type="asset")
    books.ledger.create_account(code="AR", name="AR", type="asset", control=True)
    books.ledger.create_account(code="Revenue", name="Revenue", type="income")
    # Issue + pay -> a Bank posting of 1000.00 dated 2026-01-20.
    c.post("/invoicing/issue", data={
        "number": "1", "party_id": str(acme.id), "amount": "1000.00",
        "currency": "MYR", "issued_on": "2026-01-10", "rate": "1"})
    c.post("/invoicing/1/mark-paid", data={"paid_on": "2026-01-20"})

    csv = "date,amount,description\n2026-01-20,1000.00,Acme payment\n"
    resp = c.post("/reconciliation/import", data={
        "account": "Bank", "period": "2026-01",
        "opening": "0.00", "closing": "1000.00",
        "raw": csv,
    }, follow_redirects=True)
    assert resp.status_code == 200

    # The propose page lists exactly one candidate pair.
    page = c.get("/reconciliation/Bank/2026-01").get_data(as_text=True)
    assert "Confirm" in page

    # Confirm it; report then shows zero reconciling items.
    proposals = books.bank_reconciliation.propose_matches("Bank", "2026-01")
    assert len(proposals) == 1
    p = proposals[0]
    c.post("/reconciliation/confirm", data={
        "statement_line_ref": str(p.statement_line_ref),
        "ledger_posting_ref": str(p.ledger_posting_ref)})
    report = books.reporting.reconciliation_report("Bank", "2026-01")
    assert report.reconciling_items == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_web_reconciliation.py -v`
Expected: FAIL — 404 on `/reconciliation/import`.

- [ ] **Step 3: Register the reconciliation blueprint**

Edit `src/books/interfaces/web/routes/__init__.py` `register`:
```python
def register(flask_app: Flask) -> None:
    from books.interfaces.web.routes.invoicing import invoicing_bp
    from books.interfaces.web.routes.reconciliation import reconciliation_bp
    from books.interfaces.web.routes.setup import setup_bp

    flask_app.register_blueprint(setup_bp)
    flask_app.register_blueprint(invoicing_bp)
    flask_app.register_blueprint(reconciliation_bp)
```

- [ ] **Step 4: Implement `routes/reconciliation.py`**

Create `src/books/interfaces/web/routes/reconciliation.py`:
```python
"""reconciliation_bp — import statement (CSV), propose, confirm.

confirm_match is the sole reconciliation write (ADR-0015). The CSV is
posted as a text field for the tracer; a file upload is a later
thickening (out of slice scope).
"""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from books.interfaces.web.app import current_books
from books.interfaces.web.forms import money_from

reconciliation_bp = Blueprint(
    "reconciliation", __name__, url_prefix="/reconciliation"
)


@reconciliation_bp.get("/import")
def import_form():
    return render_template("import_statement.html")


@reconciliation_bp.post("/import")
def import_statement():
    f = request.form
    current_books().bank_reconciliation.import_statement(
        account=f["account"],
        period=f["period"],
        opening=money_from(f["opening"]),
        closing=money_from(f["closing"]),
        raw=f["raw"],
    )
    return redirect(
        url_for("reconciliation.view", account=f["account"], period=f["period"])
    )


@reconciliation_bp.get("/<account>/<period>")
def view(account: str, period: str):
    books = current_books()
    lines = books.bank_reconciliation.statement_lines(account, period)
    proposals = books.bank_reconciliation.propose_matches(account, period)
    return render_template(
        "reconcile.html", account=account, period=period,
        lines=lines, proposals=proposals,
    )


@reconciliation_bp.post("/confirm")
def confirm():
    f = request.form
    current_books().bank_reconciliation.confirm_match(
        statement_line_ref=int(f["statement_line_ref"]),
        ledger_posting_ref=int(f["ledger_posting_ref"]),
    )
    return redirect(request.referrer or url_for("setup.landing"))
```

- [ ] **Step 5: Create templates**

Create `src/books/interfaces/web/templates/import_statement.html`:
```html
{% extends "base.html" %}
{% block body %}
  <h1>Import bank statement</h1>
  <form method="post" action="/reconciliation/import">
    <label>Account <input name="account" value="Bank" required></label>
    <label>Period (YYYY-MM) <input name="period" required></label>
    <label>Opening <input name="opening" value="0.00" required></label>
    <label>Closing <input name="closing" required></label>
    <label>CSV (date,amount,description; header row skipped)
      <textarea name="raw" rows="6" cols="50" required></textarea>
    </label>
    <button type="submit">Import</button>
  </form>
{% endblock %}
```

Create `src/books/interfaces/web/templates/reconcile.html`:
```html
{% extends "base.html" %}
{% block body %}
  <h1>Reconcile {{ account }} — {{ period }}</h1>
  <h2>Statement lines</h2>
  <table>
    <tr><th>Ref</th><th>Date</th><th>Amount</th><th>Description</th></tr>
    {% for ln in lines %}
      <tr><td>{{ ln.ref }}</td><td>{{ ln.date }}</td>
          <td>{{ ln.amount.minor_units }}</td><td>{{ ln.description }}</td></tr>
    {% endfor %}
  </table>
  <h2>Proposed matches</h2>
  {% if proposals %}
    {% for p in proposals %}
      <form method="post" action="/reconciliation/confirm">
        <input type="hidden" name="statement_line_ref"
               value="{{ p.statement_line_ref }}">
        <input type="hidden" name="ledger_posting_ref"
               value="{{ p.ledger_posting_ref }}">
        line {{ p.statement_line_ref }} ↔ posting {{ p.ledger_posting_ref }}
        <button type="submit">Confirm</button>
      </form>
    {% endfor %}
  {% else %}
    <p>No proposals</p>
  {% endif %}
  <p><a href="/reports/reconciliation/{{ account }}/{{ period }}">View report</a></p>
{% endblock %}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_web_reconciliation.py -v`
Expected: PASS.

- [ ] **Step 7: Run full suite + ruff + import-linter**

Run: `uv run pytest --timeout=30 -q && uv run ruff check . && uv run lint-imports`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/books/interfaces tests/test_web_reconciliation.py
git commit -m "feat(web): reconciliation blueprint — import, propose, confirm

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Reports blueprint — reconciliation report

**Files:**
- Modify: `src/books/interfaces/web/routes/__init__.py`
- Create: `src/books/interfaces/web/routes/reports.py`
- Create: `src/books/interfaces/web/templates/recon_report.html`
- Test: `tests/test_web_reports.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_web_reports.py`:
```python
from books import create_app
from books.interfaces.web.app import create_web_app


def test_report_page_renders_reconciled_state():
    books = create_app("sqlite://")
    c = create_web_app(books).test_client()
    acme = books.party.register_party(name="Acme", role="customer")
    books.ledger.create_account(code="Bank", name="Bank", type="asset")
    books.ledger.create_account(code="AR", name="AR", type="asset", control=True)
    books.ledger.create_account(code="Revenue", name="Revenue", type="income")
    c.post("/invoicing/issue", data={
        "number": "1", "party_id": str(acme.id), "amount": "1000.00",
        "currency": "MYR", "issued_on": "2026-01-10", "rate": "1"})
    c.post("/invoicing/1/mark-paid", data={"paid_on": "2026-01-20"})
    c.post("/reconciliation/import", data={
        "account": "Bank", "period": "2026-01", "opening": "0.00",
        "closing": "1000.00",
        "raw": "date,amount,description\n2026-01-20,1000.00,Acme\n"})
    p = books.bank_reconciliation.propose_matches("Bank", "2026-01")[0]
    c.post("/reconciliation/confirm", data={
        "statement_line_ref": str(p.statement_line_ref),
        "ledger_posting_ref": str(p.ledger_posting_ref)})

    resp = c.get("/reports/reconciliation/Bank/2026-01")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Reconciled" in body
    assert "No reconciling items" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_web_reports.py -v`
Expected: FAIL — 404 on `/reports/reconciliation/Bank/2026-01`.

- [ ] **Step 3: Register the reports blueprint**

Edit `src/books/interfaces/web/routes/__init__.py` `register`, add the import and registration:
```python
def register(flask_app: Flask) -> None:
    from books.interfaces.web.routes.invoicing import invoicing_bp
    from books.interfaces.web.routes.reconciliation import reconciliation_bp
    from books.interfaces.web.routes.reports import reports_bp
    from books.interfaces.web.routes.setup import setup_bp

    flask_app.register_blueprint(setup_bp)
    flask_app.register_blueprint(invoicing_bp)
    flask_app.register_blueprint(reconciliation_bp)
    flask_app.register_blueprint(reports_bp)
```

- [ ] **Step 4: Implement `routes/reports.py`**

Create `src/books/interfaces/web/routes/reports.py`:
```python
"""reports_bp — on-demand reconciliation report (ADR-0016)."""

from __future__ import annotations

from flask import Blueprint, render_template

from books.interfaces.web.app import current_books

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")


@reports_bp.get("/reconciliation/<account>/<period>")
def reconciliation(account: str, period: str):
    report = current_books().reporting.reconciliation_report(account, period)
    return render_template("recon_report.html", account=account,
                           period=period, report=report)
```

- [ ] **Step 5: Create the report template**

Create `src/books/interfaces/web/templates/recon_report.html`:
```html
{% extends "base.html" %}
{% block body %}
  <h1>Reconciliation — {{ account }} {{ period }}</h1>
  <table>
    <tr><th>Statement closing</th>
        <td>{{ report.statement_closing.minor_units }}</td></tr>
    <tr><th>Ledger bank balance</th>
        <td>{{ report.ledger_bank_balance.minor_units }}</td></tr>
    <tr><th>Confirmed cash</th>
        <td>{{ report.confirmed_cash.minor_units }}</td></tr>
    <tr><th>Difference</th>
        <td>{{ report.difference.minor_units }}</td></tr>
  </table>
  {% if report.difference.minor_units == 0 %}
    <p><strong>Reconciled.</strong></p>
  {% else %}
    <p><strong>Not reconciled.</strong></p>
  {% endif %}
  <h2>Reconciling items</h2>
  {% if report.reconciling_items %}
    <table>
      <tr><th>Ref</th><th>Amount</th><th>Age (days)</th><th>Classification</th></tr>
      {% for it in report.reconciling_items %}
        <tr><td>{{ it.ref }}</td><td>{{ it.amount.minor_units }}</td>
            <td>{{ it.age_days }}</td><td>{{ it.classification }}</td></tr>
      {% endfor %}
    </table>
  {% else %}
    <p>No reconciling items</p>
  {% endif %}
{% endblock %}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_web_reports.py -v`
Expected: PASS.

- [ ] **Step 7: Run full suite + ruff + import-linter**

Run: `uv run pytest --timeout=30 -q && uv run ruff check . && uv run lint-imports`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/books/interfaces tests/test_web_reports.py
git commit -m "feat(web): reports blueprint — reconciliation report

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Web tracer acceptance test + `books-web` script

**Files:**
- Modify: `pyproject.toml` (`[project.scripts]` add `books-web`)
- Modify: `src/books/interfaces/web/app.py` (add `main()` runner)
- Test: `tests/test_web_tracer.py`

- [ ] **Step 1: Write the failing acceptance test**

Create `tests/test_web_tracer.py`:
```python
"""Web mirror of tests/test_tracer_thread_1.py — the spine of the web
increment. Drives the full slice through the Flask test client."""

from books import create_app
from books.interfaces.web.app import create_web_app


def test_web_tracer_thread_1_end_to_end():
    books = create_app("sqlite://")
    c = create_web_app(books).test_client()

    # Setup via the web forms.
    c.post("/setup/parties", data={"name": "Acme", "role": "customer"})
    for code, name, type_, ctrl in [
        ("Bank", "Bank", "asset", ""),
        ("AR", "Accounts Receivable", "asset", "1"),
        ("Revenue", "Revenue", "income", ""),
    ]:
        c.post("/setup/accounts", data={
            "code": code, "name": name, "type": type_, "control": ctrl})

    # Issue MYR 1,000 invoice #1, mark paid.
    c.post("/invoicing/issue", data={
        "number": "1", "party_id": "1", "amount": "1000.00",
        "currency": "MYR", "issued_on": "2026-01-10", "rate": "1"})
    c.post("/invoicing/1/mark-paid", data={"paid_on": "2026-01-20"})

    # Import January statement, propose, confirm.
    c.post("/reconciliation/import", data={
        "account": "Bank", "period": "2026-01", "opening": "0.00",
        "closing": "1000.00",
        "raw": "date,amount,description\n2026-01-20,1000.00,Acme\n"})
    p = books.bank_reconciliation.propose_matches("Bank", "2026-01")[0]
    c.post("/reconciliation/confirm", data={
        "statement_line_ref": str(p.statement_line_ref),
        "ledger_posting_ref": str(p.ledger_posting_ref)})

    # Report page: reconciled, zero reconciling items.
    resp = c.get("/reports/reconciliation/Bank/2026-01")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Reconciled" in body
    assert "No reconciling items" in body
    # And the domain agrees.
    report = books.reporting.reconciliation_report("Bank", "2026-01")
    assert report.difference.minor_units == 0
    assert report.reconciling_items == []
```

- [ ] **Step 2: Run test to verify it fails (or passes)**

Run: `uv run pytest tests/test_web_tracer.py -v`
Expected: PASS if Tasks 3–6 are complete (this test composes existing
routes). If it FAILS, the failure pinpoints a slice gap — fix the
responsible blueprint before continuing. Do not weaken the assertions.

- [ ] **Step 3: Add the `books-web` runner**

Append to `src/books/interfaces/web/app.py`:
```python
def main() -> None:
    create_web_app().run(debug=True)
```

- [ ] **Step 4: Register the console script**

In `pyproject.toml` under `[project.scripts]` add:
```toml
books-web = "books.interfaces.web.app:main"
```

- [ ] **Step 5: Verify the script resolves**

Run: `uv run python -c "from books.interfaces.web.app import main; print('ok')"`
Expected: prints `ok`. (Do not start the blocking dev server in CI.)

- [ ] **Step 6: Run full suite + ruff + import-linter + djlint**

Run:
```bash
uv run pytest --timeout=30 -q && uv run ruff check . && uv run lint-imports && uv run djlint src/books/interfaces/web/templates --check
```
Expected: all pass. (djlint ignores in `pyproject.toml` already cover
partial-template noise; fix any real reported issue.)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/books/interfaces tests/test_web_tracer.py
git commit -m "feat(web): web tracer acceptance test + books-web runner

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** package layout (T1), boundary contracts (T2), setup/invoicing/reconciliation/reports blueprints (T3–T6), web tracer acceptance + `books-web` runner (T7), error→flash handler (T1 step 5), in-memory App injection in every test, file-backed default in `create_web_app`. All spec sections map to a task.
- **Deviation from spec (recorded):** CSV is submitted as a text field, not a file upload — simpler for the tracer and exercises the same `import_statement` ACL. File upload is explicitly a later thickening. The spec's "CSV upload" is satisfied in substance (raw bytes through the ACL); flagged here so the reviewer can object.
- **Type consistency:** service signatures verified against source — `register_party(name, role)`, `create_account(code, name, type, control)`, `issue_invoice(number, party_id, amount, issued_on, rate)`, `mark_paid(invoice_id, paid_on, banked)`, `adjudicate_settlement(invoice_id, outcome, on)`, `import_statement(account, period, opening, closing, raw, fmt)`, `propose_matches(account, period)`, `confirm_match(statement_line_ref, ledger_posting_ref)`, `reconciliation_report(account, period)`. DTO fields (`Proposal.statement_line_ref/ledger_posting_ref`, `ReconciliationReport.difference/reconciling_items`, `Money.minor_units`) match source.
- **Placeholder scan:** none — every step has concrete code/commands.
