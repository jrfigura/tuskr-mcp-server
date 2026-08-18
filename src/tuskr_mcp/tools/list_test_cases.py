"""The list_test_cases tool."""

from fastmcp import Context

import tuskr_client
from tuskr_mcp import credentials
from tuskr_mcp.server import mcp


@mcp.tool
async def list_test_cases(
    ctx: Context,
    filter_project,
    filter_test_suite: str | None = None,
    filter_test_suite_section: str | None = None,
    filter_key: str | None = None,
    filter_name: str | None = None,
    page: int = 1,
):
    """
    Retrieves list of test cases of a project with support for various filters.

    Use this to discover the test case keys a project actually contains before
    recording results against them with add_test_run_results.

    Args:
        filter_project: specifies the project ID to filter the test cases associated with a particular project
        filter_test_suite: ID, key or name of the test suite to filter the test cases by
        filter_test_suite_section: ID or name of the test suite section to filter the test cases by
        filter_key: to filter test cases with key containing the specified value
        filter_name: to filter test cases with name containing the specified value
        page: controls number of records in output, every page contains 100 records. Default is 1.
    """
    # No custom-field filter is exposed. Tuskr ignores a wrong-shaped one
    # silently instead of rejecting it: filtering on a checkbox field returned
    # every case in the project, including those where the field was false. A
    # filter that quietly returns unfiltered rows is worse than no filter, so
    # it is left out until the parameter shape is confirmed. Tuskr's support
    # documents it as filter[customFields][<field>]=<optionId>, taking a
    # dropdown option ID rather than a label, which needs verifying against a
    # project that has a dropdown field before it can be offered here.
    params = {"filter[project]": filter_project}

    if filter_test_suite:
        params["filter[testSuite]"] = filter_test_suite
    if filter_test_suite_section:
        params["filter[testSuiteSection]"] = filter_test_suite_section
    if filter_key:
        params["filter[key]"] = filter_key
    if filter_name:
        params["filter[name]"] = filter_name

    tenant_id, access_token = await credentials.resolve(ctx)

    return tuskr_client.send(
        "test-case",
        {"page": page, **params},
        tuskr_client.RequestMethod.GET,
        ext_tenant_id=tenant_id,
        ext_access_token=access_token,
    )
