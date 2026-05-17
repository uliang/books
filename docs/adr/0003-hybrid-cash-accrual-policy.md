# Hybrid cash/accrual accounting policy

The business runs on a **cash basis with one deliberate accrual exception**.

- **Sell side is accrual:** an issued-but-unpaid invoice is a receivable
  asset. Invoicing on terms is core to getting paid, so AR is real.
- **Buy side is cash:** no supplier payables, no Accounts Payable context.
  Suppliers are master data; expenses are recognized as cash leaves.
- **One payable exists:** the credit-card clearing account. Expenses on the
  card are recognized at swipe (`Dr Expense / Cr Card-Clearing`); settling the
  card is `Dr Card-Clearing / Cr Bank`. The card issuer is the sole creditor.

Consequences: the balance sheet must show AR and the card clearing liability;
the cash-flow statement is essentially the cleared-bank-postings view. Moving
to full accrual (supplier AP) or pure cash (no AR) would both reopen the
context map.
