"""MCP interface composition (design: 2026-05-20-mcp-interface-tracer-
expense-rail-design.md).

A thin stdio adapter over the existing composition root. One App per
process, captured in tool/resource closures. The MCP layer only
translates JSON args -> service calls; domain invariants stay in the
domain (service-raised ValueError/LookupError surface as isError: true
tool results via FastMCP).
"""
