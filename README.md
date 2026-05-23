# books

Self-service accounting with a web UI and an MCP server, both as thin
adapters over a shared domain (`books.create_app()`).

## Install & run

```bash
uv sync
```

### Web UI (Flask)

```bash
uv run books-web
```

Serves on the Flask default port (5000) against `sqlite:///books.db`
in the working directory.

### MCP server (stdio)

```bash
uv run books-mcp
```

Speaks MCP over stdio, against the same `sqlite:///books.db`. Plug
into Claude Desktop, Claude Code, or Cowork by adding to your MCP
client's JSON config:

```json
{
  "mcpServers": {
    "books": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/this/repo",
        "run",
        "books-mcp"
      ]
    }
  }
}
```

#### Available tools

- `register_party(name, role)` — register a supplier or customer.
- `create_account(code, name, type, control?)` — add a Chart of Accounts entry.
- `record_owner_paid_expense(party_id, amount_minor, currency, category_account, on)`
- `pay_contractor(party_id, amount_minor, currency, category_account, on)`
- `reimburse_owner(amount_minor, currency, on)`
- `issue_invoice(number, party_id, amount_minor, currency, issued_on, rate_bp?)`
  — issue an invoice (Dr AR / Cr Revenue). `rate_bp` is the txn→MYR booking
  rate in integer basis points (×10000, e.g. `32000` = 3.20); defaults to
  `10000` (1.00) and is ignored for MYR.
- `mark_paid(invoice_id, paid_on, banked_minor?, banked_currency?)` — record
  payment (Dr Bank / Cr AR). Returns `status`: `paid` or `awaiting_adjudication`.
- `adjudicate_settlement(invoice_id, outcome, on)` — resolve a foreign-invoice
  MYR shortfall. `outcome` is `settled_in_full` (recognize FX loss) or
  `still_owes` (AR stays open); always supplied explicitly (ADR-0019).

#### Available resources

- `parties://` — every registered party.
- `accounts://` — every Chart of Accounts entry.
- `postings://{account_code}` — every GL posting on `account_code`, with
  provenance dimensions (supplier party in v1).
- `invoices://` — every invoice, with resolved customer name and status.
- `invoices://{invoice_id}/settlement` — the both-numbers settlement picture
  (transaction amount, MYR carrying, MYR banked, MYR shortfall) for
  adjudicating a foreign-currency invoice.

Amounts are signed minor units (`123_45` for MYR 123.45). Dates are
ISO-8601 (`YYYY-MM-DD`). Currencies are ISO 4217 three-letter codes
(`MYR`, `SGD`).

## Develop

```bash
uv run pytest         # full suite with 30s per-test timeout
uv run ruff check src tests
uv run lint-imports   # ADR-0013 boundary contracts
```

See `docs/ARCHITECTURE.md`, `docs/adr/`, and
`docs/superpowers/specs/` for the architecture, decisions, and
in-flight designs.
