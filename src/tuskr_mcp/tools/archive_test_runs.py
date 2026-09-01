"""The archive_test_runs tool."""

from fastmcp import Context

import tuskr_client
from tuskr_mcp import credentials
from tuskr_mcp.server import mcp


@mcp.tool
async def archive_test_runs(
    ctx: Context,
    test_runs: str | list[str],
):
    """
    Archives one or more test runs.

    Archiving hides a run from the default test-run list without deleting it.
    Archived runs remain readable: pass filter_status='archived' to
    list_test_runs to see them, or filter_status='active' to exclude them.

    The endpoint is bulk. Reversing an archive is not exposed as a dedicated
    API action: Tuskr's own UI does it by sending the run's full object back
    with status changed to "active", which this server does not wrap yet.
    Restoring an archived run today means using the Tuskr UI.

    The response is a bare boolean, not a run snapshot. Confirming the new
    status on a specific run needs a follow-up list_test_runs call with
    filter_status set.

    Args:
        test_runs: a single test run ID, or a list of them. Unlike the other
            test-run tools, this endpoint identifies runs by ID only, so a run
            name or key is not accepted.
    """
    if isinstance(test_runs, str):
        test_runs = [test_runs]

    if not test_runs:
        raise ValueError("test_runs must contain at least one test run")

    body = {"ids": test_runs}

    tenant_id, access_token = await credentials.resolve(ctx)

    return tuskr_client.send(
        "test-run/archive",
        body,
        tuskr_client.RequestMethod.POST,
        ext_tenant_id=tenant_id,
        ext_access_token=access_token,
    )
