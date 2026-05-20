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

#### Available resources

- `parties://` — every registered party.
- `accounts://` — every Chart of Accounts entry.
- `postings://{account_code}` — every GL posting on `account_code`, with
  provenance dimensions (supplier party in v1).

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
