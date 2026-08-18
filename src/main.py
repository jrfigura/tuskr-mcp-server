"""Entry point: wires the server together and runs it.

Everything else lives under `tuskr_mcp`. This module deliberately holds no tool
definitions, so adding or changing a tool never touches it.
"""

import logging
import os

import click

from tuskr_mcp import resources, tools
from tuskr_mcp.middleware import UserTokenHandler
from tuskr_mcp.server import mcp

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Importing these two packages is what registers the tools and the resource on
# `mcp`; the binding exists so the imports read as load-bearing rather than dead.
_REGISTERED = (tools, resources)

mcp.add_middleware(UserTokenHandler())


@click.command()
@click.option("--transport", type=str, default=os.environ.get("MCP_TRANSPORT", "http"))
@click.option("--host", type=str, default=os.environ.get("MCP_HOST", "0.0.0.0"))
@click.option("--port", type=int, default=os.environ.get("MCP_PORT", "8000"))
def main(transport, host, port):
    run_params = {}
    if transport == "http":
        run_params["host"] = host
        run_params["port"] = port

    mcp.run(
        transport=transport,
        **run_params,
    )


if __name__ == "__main__":
    main()
