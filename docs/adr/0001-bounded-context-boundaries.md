# Bounded context boundaries

The initial proposal had five contexts: Chart of Accounts, Ledger, Reports,
Suppliers, Customers/Invoicing. We collapsed them.

- **Chart of Accounts + Ledger → one General Ledger context.** "Account" is
  the central noun of both; the double-entry invariant cannot be enforced
  transactionally if posting and account structure live in separate contexts.
  Chart of Accounts is an aggregate inside General Ledger.
- **Reports → a read model, not a context.** Reporting authors no truth and
  holds no invariants; it is a pure derivable projection of the Ledger (plus
  one cross-context projection for customer profitability). Budgeting, the only
  thing that would make it author data, is out of v1.
- **Suppliers → master data, not a context.** Cash basis on purchases means
  "match expense to supplier" is just a Party attribution tag; there is no
  payables lifecycle to own.
- **Customers/Invoicing → split.** Customer is a Party (master data);
  Invoicing/AR is a real context with a genuine invoice lifecycle and is the
  upstream source of receivables.

Result: General Ledger, Invoicing/AR, Expense Management, Bank Reconciliation
as contexts; Party as shared master data; Reporting as a read model.
