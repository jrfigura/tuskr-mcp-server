"""The list_projects tool."""

from fastmcp import Context

import tuskr_client
from tuskr_mcp import credentials
from tuskr_mcp.server import mcp


@mcp.tool
async def list_projects(
    ctx: Context,
    filter_name: str | None = None,
    filter_status: str | None = None,
    page: int = 1,
):
    """
    Retrives list of projects based on various filter criteria.

    Args:
        filter_name: to filter projects with name containing the specified value
        filter_status: to filter projects by their status. Two supported values 'active' or 'archived'
        page: controls number of records in output, every page contains 100 records. Default is 1.
    """
    params = {}

    if filter_name:
        params["filter[name]"] = filter_name
    if filter_status:
        params["filter[status]"] = filter_status

    tenant_id, access_token = await credentials.resolve(ctx)

    return tuskr_client.send(
        "project",
        {"page": page, **params},
        tuskr_client.RequestMethod.GET,
        ext_tenant_id=tenant_id,
        ext_access_token=access_token,
    )
