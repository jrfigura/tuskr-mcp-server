import json
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

# Identifying fields kept from a Tuskr user object. The raw object also carries
# an `applicationState` UI blob (menu state and cached announcement text, up to
# ~16 KB per user) plus per-account security metadata such as
# `passwordResetTokenExpiresAt`, `jwtTokenInvalidBefore` and `lastLoginAt`.
# None of that is useful to a caller, and passing it through both defeats the
# trimming and puts account metadata into model context.
_ASSIGNEE_FIELDS = ("id", "fullName", "email")


def _trim_assignee(assignee):
    """Reduce a Tuskr user object to its identifying fields.

    Returns the value unchanged when it is not a user object (e.g. None for an
    unassigned test run), so the response shape stays stable for callers.
    """
    if not isinstance(assignee, dict):
        return assignee
    return {key: assignee[key] for key in _ASSIGNEE_FIELDS if key in assignee}


def _trim_test_run_rows(raw):
    """Trim the assignee on every row of a raw Tuskr test-run response.

    Takes and returns the JSON text `tuskr_client.send` produces, so every
    other field reaches the caller exactly as the API sent it. A payload that
    is not a JSON object carrying a `rows` list is returned untouched, which
    keeps error bodies and any future response shape readable rather than
    silently emptied.
    """
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return raw

    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        return raw

    for row in data["rows"]:
        if isinstance(row, dict) and "assignedTo" in row:
            row["assignedTo"] = _trim_assignee(row["assignedTo"])

    return json.dumps(data)


# Fields kept from the nested testCase object of a result row. The raw object
# is the whole test case, and two of its fields grow without bound:
# resultHistory accumulates an entry per execution for the life of the case,
# and openIssueIds accumulates every ticket key ever linked to it across all
# projects. One row measured ~14 KB live, so a full page would exceed the cap.
# testRunTestCases is kept because Tuskr scopes it to the run being queried:
# it holds this run's own result, including the issue keys filed against this
# failure, which is the next thing a caller needs after finding what failed.
_RESULT_TEST_CASE_FIELDS = ("id", "key", "name", "testRunTestCases")


def _as_csv(value):
    """Render a str-or-list argument in the comma separated form Tuskr expects.

    Returns None for an absent value so the caller can leave the query
    parameter out entirely rather than sending an empty filter.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    joined = ",".join(str(item) for item in value)
    return joined or None


def _trim_result_row(row):
    """Reduce one result row's nested testCase to its identifying fields.

    Every sibling key, including latestStatus and any result detail Tuskr
    adds later, is carried through untouched.
    """
    if not isinstance(row, dict):
        return row
    test_case = row.get("testCase")
    if not isinstance(test_case, dict):
        return row
    return {
        **row,
        "testCase": {
            key: test_case[key] for key in _RESULT_TEST_CASE_FIELDS if key in test_case
        },
    }


def _trim_results(raw):
    """Trim every row of a raw Tuskr test-run results response.

    Takes and returns the JSON text `tuskr_client.send` produces. A payload
    that is not a JSON object carrying a `data` list is returned untouched,
    so error bodies stay readable.
    """
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return raw

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return raw

    payload["data"] = [_trim_result_row(row) for row in payload["data"]]
    return json.dumps(payload)


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
            When False (default), returns the paginated response from the Tuskr API with every field
            intact. Either way the assignee on each row is reduced to id, fullName and email.
        page: controls number of records in output, every page contains 100 records. Default is 1.
            Ignored when filter_incomplete is True.
    """
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
        # Trim the assignee here too: this path returns whole rows, so without
        # it the largest single source of bulk and the account security
        # metadata both reach the caller on the default call.
        return _trim_test_run_rows(
            tuskr_client.send(
                "test-run",
                {"page": page, **params},
                tuskr_client.RequestMethod.GET,
                ext_tenant_id=tenant_id,
                ext_access_token=access_token,
            )
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
                        "assignedTo": _trim_assignee(run.get("assignedTo")),
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


@mcp.tool
async def get_test_run_results(
    ctx: Context,
    test_run: str,
    status: str | list[str] | None = None,
    test_cases: str | list[str] | None = None,
    page: int = 1,
    fetch_all_pages: bool = False,
    trim_response: bool = True,
):
    """
    Fetches the test cases in a test run together with their latest result.

    The main use is confirmation testing: pass status='FAILED' to get back
    only the test cases that need re-checking after a fix.

    Args:
        test_run: ID of the test run. Tuskr addresses the run in the URL path
            for this endpoint, so unlike the other tools a run name is not
            accepted here.
        status: a result status key, or a list of them, e.g. 'FAILED' or
            ['RETEST', 'FAILED']. Only test cases whose current status is one
            of these are returned. Status keys are configured per tenant, so
            use the keys defined in your own Tuskr account.
        test_cases: a test case ID, key or name, or a list of them. Only the
            matching test cases are returned.
        page: page number to fetch, 100 records per page. Default is 1.
            Ignored when fetch_all_pages is True.
        fetch_all_pages: if True, walks every page and returns the combined
            rows. Tuskr rate-limits every plan at 10 requests/second, so
            prefer a status or test_cases filter over fetching everything.
        trim_response: if True (default), each row's nested testCase object is
            reduced to id, key, name and testRunTestCases (this run's own
            result and its linked issue keys). The full object also carries the
            case's entire resultHistory and every issue key ever linked to it,
            which can push a busy run past the MCP transport size limit. Set it
            to False when that history is genuinely needed.
    """
    params = {}

    status_param = _as_csv(status)
    if status_param:
        params["status"] = status_param

    test_cases_param = _as_csv(test_cases)
    if test_cases_param:
        params["testCases"] = test_cases_param

    # Resolve credentials once up front so we don't re-await on every page.
    tenant_id = (
        (await ctx.get_state("ext_tenant_id"))
        or os.environ.get("TUSKR_TENANT_ID")
        or os.environ.get("TUSKR_ACCOUNT_ID")
    )
    access_token = (await ctx.get_state("ext_access_token")) or os.environ.get(
        "TUSKR_ACCESS_TOKEN"
    )

    def fetch(page_number):
        return tuskr_client.send(
            f"test-run/{test_run}/results",
            {"page": page_number, **params},
            tuskr_client.RequestMethod.GET,
            ext_tenant_id=tenant_id,
            ext_access_token=access_token,
        )

    if not fetch_all_pages:
        raw = fetch(page)
        return _trim_results(raw) if trim_response else raw

    first = fetch(1)
    try:
        payload = json.loads(first)
    except (TypeError, ValueError):
        return first

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return first

    rows = payload["data"]
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    for page_number in range(2, meta.get("pages", 1) + 1):
        more = json.loads(fetch(page_number))
        rows.extend(more.get("data", []))

    if trim_response:
        rows = [_trim_result_row(row) for row in rows]

    return json.dumps({"data": rows, "meta": meta})


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
