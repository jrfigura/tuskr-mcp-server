"""The copy_test_run tool."""

from fastmcp import Context

import tuskr_client
from tuskr_mcp import credentials
from tuskr_mcp.server import mcp


@mcp.tool
async def copy_test_run(
    ctx: Context,
    test_run: str,
    name: str = "",
    description: str = "",
    deadline: str = "",
    assigned_to: str = "",
):
    """
    Creates a copy of an existing test run along with its test cases.

    The copy is created in the same project as the source run: this endpoint
    takes no project parameter, so a run cannot be copied across projects.
    The case selection is carried over in full and cannot be narrowed here;
    use create_test_run when a different selection is needed. Results are not
    carried over: every case in the copy starts UNTESTED even if the source
    run had recorded results (verified live against a sandbox project).

    Every optional argument below overrides the corresponding attribute on the
    copy. Leaving one unset keeps the source run's own value rather than
    clearing it.

    Args:
        test_run: ID or name of the test run to copy
        name: name for the new test run
        description: description of the new test run
        deadline: YYYY-MM-DD date
        assigned_to: ID, name, or email of the user. If specified, the new test
            run will be assigned to this user.
    """
    body = {"testRun": test_run}

    # Only send optional keys the caller actually set. An absent key means
    # "inherit from the source run", while a blank one is a value Tuskr
    # validates: `assignedTo` is resolved against real users and `deadline`
    # against today's date, so either is an error rather than a no-op.
    if name:
        body["name"] = name
    if description:
        body["description"] = description
    if deadline:
        body["deadline"] = deadline
    if assigned_to:
        body["assignedTo"] = assigned_to

    tenant_id, access_token = await credentials.resolve(ctx)

    return tuskr_client.send(
        "test-run/copy",
        body,
        tuskr_client.RequestMethod.POST,
        ext_tenant_id=tenant_id,
        ext_access_token=access_token,
    )
