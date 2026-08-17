"""The create_test_run tool."""

from fastmcp import Context

import tuskr_client
from tuskr_mcp import credentials
from tuskr_mcp.server import mcp


@mcp.tool
async def create_test_run(
    ctx: Context,
    name: str,
    project: str,
    test_case_inclusion_type: str,
    test_cases: list[str] | None = None,
    description: str = "",
    deadline: str = "",
    assigned_to: str = "",
):
    """
    Creates a new test run in a project.

    Args:
        name: a new test run name
        project: name or project ID where to create a test run
        test_case_inclusion_type: One of 'ALL' or 'SPECIFIC'. If you specify 'ALL', all test cases in the project will be included in the test run.
                                  If you specify 'SPECIFIC', then you will have to indicate the test cases to include as explained below.
        test_cases: list of IDs, keys or names. Required if you have set `test_case_inclusion_type` to 'SPECIFIC'.
        description: description of a test run
        deadline: YYYY-MM-DD date
        assigned_to: ID, name, or email of the user. If specified, the test run will be assigned to this user
    """
    body = {
        "name": name,
        "project": project,
        "testCaseInclusionType": test_case_inclusion_type,
    }

    # Only send optional keys the caller actually set. Tuskr validates these
    # fields even when they arrive blank: an empty `deadline` is rejected with
    # "Deadline must be today or a future date" rather than treated as absent,
    # which made the tool unusable unless a deadline was supplied.
    if test_cases:
        body["testCases"] = test_cases
    if description:
        body["description"] = description
    if deadline:
        body["deadline"] = deadline
    if assigned_to:
        body["assignedTo"] = assigned_to

    tenant_id, access_token = await credentials.resolve(ctx)

    return tuskr_client.send(
        "test-run",
        body,
        tuskr_client.RequestMethod.POST,
        ext_tenant_id=tenant_id,
        ext_access_token=access_token,
    )
