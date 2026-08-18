"""Tool modules, one tool per module.

Each module registers itself on the shared server with `@mcp.tool` at import
time, and importing this package imports all of them. Discovery is automatic so
that adding a tool means adding a single new file: no edit to this module, and
therefore no conflict between branches that each add a tool.
"""

import importlib
import pkgutil

for _module_info in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_module_info.name}")
