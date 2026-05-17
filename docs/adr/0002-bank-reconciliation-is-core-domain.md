# Bank Reconciliation is the core domain

One would expect the General Ledger (double-entry correctness) to be the core
domain. It is not — it is a well-understood, supporting backbone.

The product's differentiating value is **trustworthy self-service books**, and
the thing that earns that trust is reconciling recorded activity against the
actual bank statement. Bank Reconciliation owns the clearance state of cash,
the discrepancy/exception list, and the assertions that make divergence
visible. It is the deepest-modeled context and gets the most investment.

Consequence: where effort trade-offs arise, Reconciliation correctness and
ergonomics win over Ledger feature breadth.
