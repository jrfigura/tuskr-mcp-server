"""Internals of the Tuskr MCP server.

The package is deliberately shallow: `server` owns the FastMCP instance,
`middleware` and `credentials` hold the cross-cutting request plumbing, and
every tool lives in its own module under `tools`. Nothing is imported here, so
that `tools` can import `server` without a cycle.
"""
