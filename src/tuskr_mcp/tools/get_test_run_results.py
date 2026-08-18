"""The get_test_run_results tool, and the result trimming it needs.

The trimming helpers stay in this module rather than a shared one: they are used
by this tool alone, and a shared trimming module would be a file every future
tool branch has to touch.
"""

import json

from fastmcp import Context

import tuskr_client
from tuskr_mcp import credentials
from tuskr_mcp.server import mcp

# Fields kept from the nested testCase object of a result row. The raw object
# is the whole test case, and two of its fields grow without bound:
# resultHistory accumulates an entry per execution for the life of the case,
# and openIssueIds accumulates every ticket key ever linked to it across all
# projects. One row measured ~14 KB live, so a full page would exceed the cap.
# testRunTestCases is kept because Tuskr scopes it to the run being queried:
# it holds this run's own result, including the issue keys filed against this
# failure, which is the next thing a caller needs after finding what failed.
_RESULT_TEST_CASE_FIELDS = ("id", "key", "name", "testRunTestCases")


def as_csv(value):
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


def trim_result_row(row):
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


def trim_results(raw):
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

    payload["data"] = [trim_result_row(row) for row in payload["data"]]
    return json.dumps(payload)


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

    status_param = as_csv(status)
    if status_param:
        params["status"] = status_param

    test_cases_param = as_csv(test_cases)
    if test_cases_param:
        params["testCases"] = test_cases_param

    # Resolve credentials once up front so we don't re-await on every page.
    tenant_id, access_token = await credentials.resolve(ctx)

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
        return trim_results(raw) if trim_response else raw

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
        rows = [trim_result_row(row) for row in rows]

    return json.dumps({"data": rows, "meta": meta})
