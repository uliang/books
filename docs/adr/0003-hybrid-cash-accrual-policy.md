# Hybrid cash/accrual accounting policy

The business runs on a **cash basis with one deliberate accrual exception**.

- **Sell side is accrual:** an issued-but-unpaid invoice is a receivable
  asset. Invoicing on terms is core to getting paid, so AR is real.
- **Buy side is cash:** no supplier payables, no Accounts Payable context.
  Suppliers are master data; expenses are recognized as cash leaves.
- **One payable exists:** the **Due to Owner** reimbursement liability.
  Business expenses the owner pays personally are recognized at the charge
  (`Dr Expense / Cr Due to Owner`); the business reimbursing the owner is
  `Dr Due to Owner / Cr Bank`. The **owner** is the creditor.

Consequences: the balance sheet must show AR and the Due-to-Owner liability;
the cash-flow statement is essentially the cleared-bank-postings view. Moving
to full accrual (supplier AP) or pure cash (no AR) would both reopen the
context map.

## Amendment 2026-05-19 — the one payable is Due to Owner, not card-clearing

Originally the single payable was the **credit-card clearing account**, with
the card issuer as sole creditor (`Dr Expense / Cr Card-Clearing` at swipe,
`Dr Card-Clearing / Cr Bank` at monthly settlement). That assumed a
**business** card.

The owner's actual rail is a **personal / mixed-use** card: business expenses
are charged alongside unrelated personal spend, and the owner settles the
full card bill personally. The business never sees the card statement and
never pays the card issuer — so the issuer is **not** a creditor of the
business. The reason to track these charges at all is to compute **how much
the business owes the owner**.

The one-payable *structure* is unchanged — it is still exactly one accrued
buy-side liability, recognized at the charge, drawn down by a bank payment
that reconciles on the normal spine. Only the **creditor's identity** changes
(owner, not card issuer), so the context map and the cash/accrual split are
**not** reopened. The personal card and its personal charges are out of
scope of the business books entirely; only individual business expenses are
captured. The reimbursement is settling a debt — deliberately **not** modelled
as owner equity / an owner draw (see ADR-0006), keeping operational expense
funding out of equity and making "how much I am owed" a single liability
balance.
