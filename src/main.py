import logging
import os
import warnings

import click
from fastmcp import Context, FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext

import tuskr_client

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


class UserTokenHandler(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        """
        Executed on every tool call.
        We intercept it with goal to get secure token
        if it is in the header
        """
        logger.info(f"Raw middleware processing: {context.method}")

        self.retrieve_and_apply_token(context)

        result = await call_next(context)
        logger.info(f"Raw middleware completed: {context.method}")
        return result

    def retrieve_and_apply_token(self, context: MiddlewareContext):
        """
        In stdio mode there is no HTTP request/headers, so fall back to None
        and let the tool functions fall back to env vars instead
        """
        try:
            request = context.fastmcp_context.request_context.request
            headers = request.headers
        # Broad by design: fastmcp raises different errors depending on which
        # part of the request context is missing in stdio mode.
        except Exception:  # noqa: BLE001
            logger.info(
                "No HTTP request context (stdio mode), skipping header extraction"
            )
            context.fastmcp_context.set_state("ext_access_token", None)
            context.fastmcp_context.set_state("ext_tenant_id", None)
            return

        # Read access token
        auth_header = headers.get("Authorization")
        token = None

        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            if not token:
                raise ValueError(
                    "Unauthorized: Empty Bearer token",
                )
            logger.info(f"Got Bearer token: {token}")

        context.fastmcp_context.set_state("ext_access_token", token)

        # Try to retrieve tenant id from headers; prefer the new Tenant-ID header
        # and fall back to the legacy Account-ID header with a deprecation warning.
        # Tenant id is optional — it can be set via TUSKR_TENANT_ID env var instead.
        tenant_id = None
        tenant_header = headers.get("Tenant-ID")
        if tenant_header:
            tenant_id = tenant_header.strip()
            logger.info(f"Got tenant id: {tenant_id}")
        else:
            legacy_header = headers.get("Account-ID")
            if legacy_header:
                warnings.warn(
                    "The 'Account-ID' HTTP header is deprecated; "
                    "use 'Tenant-ID' instead.",
                    DeprecationWarning,
                    stacklevel=2,
                )
                tenant_id = legacy_header.strip()
                logger.info(
                    f"Got tenant id (via deprecated Account-ID header): {tenant_id}"
                )
            else:
                logger.info("Tenant id is not defined")

        context.fastmcp_context.set_state("ext_tenant_id", tenant_id)


mcp = FastMCP(
    name="Tuskr MCP Service",
)
mcp.add_middleware(UserTokenHandler())


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
    return tuskr_client.send(
        "project",
        {"page": page, **params},
        tuskr_client.RequestMethod.GET,
        ext_tenant_id=(await ctx.get_state("ext_tenant_id"))
        or os.environ.get("TUSKR_TENANT_ID")
        or os.environ.get("TUSKR_ACCOUNT_ID"),
        ext_access_token=(await ctx.get_state("ext_access_token"))
        or os.environ.get("TUSKR_ACCESS_TOKEN"),
    )


@mcp.tool
async def list_test_runs(
    ctx: Context,
    filter_project,
    filter_name: str | None = None,
    filter_key: str | None = None,
    filter_status: str | None = None,
    filter_assigned_to: str | None = None,
    filter_incomplete: bool = False,
    page: int = 1,
):
    """
    Retrieves list of test runs of a project with support for various filters.

    Args:
        filter_project: specifies the project ID to filter the test runs associated with a particular project
        filter_name: to filter test runs with name containing the specified value
        filter_key: to filter test runs with key containing the specified value
        filter_status: to filter test runs by their status. Two supported values 'active' or 'archived'
        filter_assigned_to: id of the user to whom test runs are assigned
        filter_incomplete: if True, fetches all pages and returns only test runs that are not 100% complete,
            with a trimmed payload (id, key, name, percentDone, counts, assignee, deadline, status).
            When False (default), returns the raw paginated response from the Tuskr API.
        page: controls number of records in output, every page contains 100 records. Default is 1.
            Ignored when filter_incomplete is True.
    """
    import json

    params = {"filter[project]": filter_project}

    if filter_name:
        params["filter[name]"] = filter_name
    if filter_key:
        params["filter[key]"] = filter_key
    if filter_status:
        params["filter[status]"] = filter_status
    if filter_assigned_to:
        params["filter[assignedTo]"] = filter_assigned_to

    # Resolve credentials once up front so we don't re-await on every page.
    tenant_id = (
        (await ctx.get_state("ext_tenant_id"))
        or os.environ.get("TUSKR_TENANT_ID")
        or os.environ.get("TUSKR_ACCOUNT_ID")
    )
    access_token = (await ctx.get_state("ext_access_token")) or os.environ.get(
        "TUSKR_ACCESS_TOKEN"
    )

    if not filter_incomplete:
        return tuskr_client.send(
            "test-run",
            {"page": page, **params},
            tuskr_client.RequestMethod.GET,
            ext_tenant_id=tenant_id,
            ext_access_token=access_token,
        )

    # Fetch all pages and filter for incomplete runs client-side,
    # returning a trimmed payload to stay under MCP transport size limits.
    incomplete = []
    current_page = 1
    while True:
        raw = tuskr_client.send(
            "test-run",
            {"page": current_page, **params},
            tuskr_client.RequestMethod.GET,
            ext_tenant_id=tenant_id,
            ext_access_token=access_token,
        )
        data = json.loads(raw)
        rows = data.get("rows", [])
        for run in rows:
            percent = run.get("percentDone", 100)
            if percent < 100:
                incomplete.append(
                    {
                        "id": run.get("id"),
                        "key": run.get("key"),
                        "name": run.get("name"),
                        "percentDone": percent,
                        "totalTestCaseCount": run.get("totalTestCaseCount", 0),
                        "doneTestCaseCount": run.get("doneTestCaseCount", 0),
                        "assignedTo": run.get("assignedTo"),
                        "deadline": run.get("deadline"),
                        "status": run.get("status"),
                    }
                )
        meta = data.get("meta", {})
        if current_page >= meta.get("pages", 1):
            break
        current_page += 1

    return json.dumps({"rows": incomplete, "count": len(incomplete)})


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
    return tuskr_client.send(
        "test-run",
        {
            "name": name,
            "project": project,
            "testCaseInclusionType": test_case_inclusion_type,
            "testCases": test_cases,
            "description": description,
            "deadline": deadline,
            "assignedTo": assigned_to,
        },
        tuskr_client.RequestMethod.POST,
        ext_tenant_id=(await ctx.get_state("ext_tenant_id"))
        or os.environ.get("TUSKR_TENANT_ID")
        or os.environ.get("TUSKR_ACCOUNT_ID"),
        ext_access_token=(await ctx.get_state("ext_access_token"))
        or os.environ.get("TUSKR_ACCESS_TOKEN"),
    )


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

    return tuskr_client.send(
        "test-run-result/bulk",
        body,
        tuskr_client.RequestMethod.POST,
        ext_tenant_id=(await ctx.get_state("ext_tenant_id"))
        or os.environ.get("TUSKR_TENANT_ID")
        or os.environ.get("TUSKR_ACCOUNT_ID"),
        ext_access_token=(await ctx.get_state("ext_access_token"))
        or os.environ.get("TUSKR_ACCESS_TOKEN"),
    )


@mcp.resource("resource://service_description")
def service_description():
    return """This MCP service provides tools to manage projects, test cases, tests suits
    test runs and other resources in Tuskr"""


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
