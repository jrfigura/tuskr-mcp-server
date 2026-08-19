"""The set_test_run_lock tool."""

from fastmcp import Context

import tuskr_client
from tuskr_mcp import credentials
from tuskr_mcp.server import mcp


@mcp.tool
async def set_test_run_lock(
    ctx: Context,
    test_run: str,
    lock: bool,
):
    """
    Locks or unlocks a test run.

    A locked test run is read-only: results can no longer be recorded against
    it and its test cases can no longer be edited. Locking is otherwise a
    manual action in the Tuskr UI, so this tool is what lets an automated
    workflow seal a run once execution is complete.

    The endpoint accepts one test run per call, so locking several runs takes
    one call each. Tuskr rate-limits every plan at 10 requests/second.

    Args:
        test_run: ID or name of the test run to lock or unlock
        lock: True to lock the test run, False to unlock it
    """
    body = {
        "testRun": test_run,
        "lock": lock,
    }

    tenant_id, access_token = await credentials.resolve(ctx)

    return tuskr_client.send(
        "test-run/set-lock",
        body,
        tuskr_client.RequestMethod.POST,
        ext_tenant_id=tenant_id,
        ext_access_token=access_token,
    )
