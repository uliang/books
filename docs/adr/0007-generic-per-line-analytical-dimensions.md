# Generic per-line analytical dimensions

Customer profitability and supplier-spend reporting require attribution on
individual journal lines, not whole transactions. Rather than hard-code a
`party_id` column (which would be duplicated when Project/job costing arrives),
a journal line carries a **generic set of typed dimensions**.

v1 implements exactly one dimension type — **Party**. Adding **Project** (the
likely next axis) later is then data, not a schema or aggregate change.

Considered and rejected: a fixed `party_id` field. Cheaper now, but retrofitting
a second axis onto a pure projection architecture is the classic "next engineer
fixes it wrong" trap.
