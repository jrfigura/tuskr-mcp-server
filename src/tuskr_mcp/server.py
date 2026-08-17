"""The FastMCP instance every tool and resource registers against.

This lives apart from `main` on purpose. `main` is executed as a script
(`uv run src/main.py`), so it is `__main__`; a tool importing `main` to reach
the server would load a second copy of that module and re-run its import-time
setup. Keeping the instance here gives every module one unambiguous import.
"""

from fastmcp import FastMCP

mcp = FastMCP(
    name="Tuskr MCP Service",
)
