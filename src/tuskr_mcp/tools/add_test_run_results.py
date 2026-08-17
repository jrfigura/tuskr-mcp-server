"""The add_test_run_results tool."""

from fastmcp import Context

import tuskr_client
from tuskr_mcp import credentials
from tuskr_mcp.server import mcp


@mcp.tool
async def add_test_run_results(
    ctx: Context,
    test_run: str,
    status: str,
    test_cases: str | list[str],
    assigned_to: str | None = None,
    comments: str | None = None,
    time_spent_in_minutes: int | None = None,
    custom_fields: dict | None = None,
):
    """
    Records a result against one or more test cases in a test run.

    Tuskr exposes a single bulk endpoint for results, so one call applies the
    same status to every test case listed. Pass a single test case to record
    one result, or a list to record many in one request. Always prefer one
    call with a list over repeated single calls: Tuskr rate-limits every plan
    at 10 requests/second.

    Args:
        test_run: ID or name of the test run
        status: result status key, e.g. 'PASSED', 'FAILED', 'RETEST'. Status
            keys are configured per tenant, so use the keys defined in your
            own Tuskr account.
        test_cases: a single test case ID, key or name, or a list of them.
            The status is applied to every test case listed.
        assigned_to: ID, name or email of the user. If present, the test cases
            in this test run will be assigned to this user.
        comments: free-text comment stored on every result created by this call
        time_spent_in_minutes: execution time recorded against every result
        custom_fields: JSON object mapping custom field keys to their values
    """
    if isinstance(test_cases, str):
        test_cases = [test_cases]

    if not test_cases:
        raise ValueError("test_cases must contain at least one test case")

    body = {
        "testRun": test_run,
        "status": status,
        "testCases": test_cases,
    }

    # Only send optional keys the caller actually set. Tuskr resolves
    # assignedTo against real users, so a blank value is an error, not a no-op.
    if assigned_to:
        body["assignedTo"] = assigned_to
    if comments:
        body["comments"] = comments
    if time_spent_in_minutes is not None:
        body["timeSpentInMinutes"] = time_spent_in_minutes
    if custom_fields:
        body["customFields"] = custom_fields

    tenant_id, access_token = await credentials.resolve(ctx)

    return tuskr_client.send(
        "test-run-result/bulk",
        body,
        tuskr_client.RequestMethod.POST,
        ext_tenant_id=tenant_id,
        ext_access_token=access_token,
    )
