import asyncio
import json

import pytest

from src import main
from src.main import _trim_assignee, _trim_test_run_rows, list_test_runs

# Depending on the fastmcp version, @mcp.tool either leaves the plain function
# in place or wraps it in a Tool object exposing the original as `.fn`.
_list_test_runs = getattr(list_test_runs, "fn", list_test_runs)


def _user(**overrides):
    """A Tuskr user object shaped like the real API response."""
    user = {
        "id": "9f1c0e2a",
        "fullName": "Test User",
        "email": "qa.lead@example.com",
        "applicationState": "x" * 16209,
        "passwordResetTokenExpiresAt": "2026-08-01T10:00:00Z",
        "jwtTokenInvalidBefore": "2026-07-30T09:00:00Z",
        "lastLoginAt": "2026-08-09T07:14:00Z",
    }
    user.update(overrides)
    return user


def _add_result(ctx, **kwargs):
    """Call the add_test_run_results tool, unwrapping the @mcp.tool decorator.

    Driven with asyncio.run so the suite needs no pytest-asyncio dependency.
    """
    tool = getattr(main.add_test_run_results, "fn", main.add_test_run_results)
    return asyncio.run(tool(ctx, **kwargs))


class FakeContext:
    """Minimal stand-in for the FastMCP Context used by the tool functions."""

    def __init__(self, state=None):
        self._state = state or {}

    async def get_state(self, key):
        return self._state.get(key)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.delenv("TUSKR_ACCOUNT_ID", raising=False)
    monkeypatch.setenv("TUSKR_TENANT_ID", "tenant-from-env")
    monkeypatch.setenv("TUSKR_ACCESS_TOKEN", "token-from-env")


@pytest.fixture
def send(mocker):
    return mocker.patch.object(main.tuskr_client, "send", return_value="{}")


class TestTrimAssignee:
    def test_keeps_only_identifying_fields(self):
        assert _trim_assignee(_user()) == {
            "id": "9f1c0e2a",
            "fullName": "Test User",
            "email": "qa.lead@example.com",
        }

    def test_drops_application_state_and_security_metadata(self):
        trimmed = _trim_assignee(_user())
        for dropped in (
            "applicationState",
            "passwordResetTokenExpiresAt",
            "jwtTokenInvalidBefore",
            "lastLoginAt",
        ):
            assert dropped not in trimmed

    def test_unassigned_run_stays_none(self):
        assert _trim_assignee(None) is None

    def test_non_dict_value_passes_through(self):
        assert _trim_assignee("9f1c0e2a") == "9f1c0e2a"

    def test_missing_fields_are_omitted_not_nulled(self):
        assert _trim_assignee({"id": "abc"}) == {"id": "abc"}

    def test_trimmed_row_is_orders_of_magnitude_smaller(self):
        raw_size = len(json.dumps(_user()))
        trimmed_size = len(json.dumps(_trim_assignee(_user())))
        assert raw_size > 16_000
        assert trimmed_size < 300


class TestTrimTestRunRows:
    def test_trims_assignee_on_every_row(self):
        raw = json.dumps(
            {
                "rows": [
                    {"id": "run-1", "assignedTo": _user()},
                    {"id": "run-2", "assignedTo": _user(id="other")},
                ],
                "meta": {"pages": 1},
            }
        )
        data = json.loads(_trim_test_run_rows(raw))
        assert [row["assignedTo"]["id"] for row in data["rows"]] == [
            "9f1c0e2a",
            "other",
        ]
        assert "applicationState" not in _trim_test_run_rows(raw)

    def test_leaves_every_other_field_untouched(self):
        row = {
            "id": "run-1",
            "key": "TR-1",
            "name": "Regression",
            "description": "unchanged",
            "customFields": {"a": 1},
            "assignedTo": _user(),
        }
        data = json.loads(_trim_test_run_rows(json.dumps({"rows": [row]})))
        trimmed = data["rows"][0]
        assert {k: v for k, v in trimmed.items() if k != "assignedTo"} == {
            k: v for k, v in row.items() if k != "assignedTo"
        }

    def test_meta_is_preserved(self):
        raw = json.dumps({"rows": [], "meta": {"pages": 3, "total": 250}})
        assert json.loads(_trim_test_run_rows(raw))["meta"] == {
            "pages": 3,
            "total": 250,
        }

    def test_unassigned_row_keeps_null_assignee(self):
        raw = json.dumps({"rows": [{"id": "run-1", "assignedTo": None}]})
        assert json.loads(_trim_test_run_rows(raw))["rows"][0]["assignedTo"] is None

    def test_row_without_assignee_key_is_not_given_one(self):
        raw = json.dumps({"rows": [{"id": "run-1"}]})
        assert "assignedTo" not in json.loads(_trim_test_run_rows(raw))["rows"][0]

    def test_error_body_passes_through_unchanged(self):
        raw = json.dumps({"errors": [{"code": "NOT_FOUND"}]})
        assert _trim_test_run_rows(raw) == raw

    def test_non_json_passes_through_unchanged(self):
        assert _trim_test_run_rows("502 Bad Gateway") == "502 Bad Gateway"


class TestListTestRunsTrimming:
    @pytest.fixture(autouse=True)
    def _creds(self, monkeypatch):
        monkeypatch.setenv("TUSKR_TENANT_ID", "tenant-1")
        monkeypatch.setenv("TUSKR_ACCESS_TOKEN", "token-1")

    def test_incomplete_rows_carry_trimmed_assignee(self, monkeypatch):
        page = {
            "rows": [
                {
                    "id": "run-1",
                    "key": "TR-1",
                    "name": "Regression",
                    "percentDone": 42,
                    "totalTestCaseCount": 10,
                    "doneTestCaseCount": 4,
                    "assignedTo": _user(),
                    "deadline": "2026-08-20",
                    "status": "ACTIVE",
                },
                {
                    "id": "run-2",
                    "key": "TR-2",
                    "name": "Smoke",
                    "percentDone": 100,
                    "assignedTo": _user(),
                },
            ],
            "meta": {"pages": 1},
        }
        monkeypatch.setattr(
            "tuskr_client.send", lambda *args, **kwargs: json.dumps(page)
        )

        # asyncio.run keeps this a plain sync test, so the repo needs no
        # pytest-asyncio dependency just for this one case.
        result = json.loads(
            asyncio.run(
                _list_test_runs(
                    FakeContext(), filter_project="p", filter_incomplete=True
                )
            )
        )

        assert result["count"] == 1
        row = result["rows"][0]
        assert row["id"] == "run-1"
        assert row["assignedTo"] == {
            "id": "9f1c0e2a",
            "fullName": "Test User",
            "email": "qa.lead@example.com",
        }
        assert "applicationState" not in json.dumps(result)
        assert len(json.dumps(result)) < 500

    def test_default_path_rows_carry_trimmed_assignee(self, monkeypatch):
        page = {
            "rows": [
                {
                    "id": "run-1",
                    "key": "TR-1",
                    "name": "Regression",
                    "percentDone": 100,
                    "assignedTo": _user(),
                }
            ],
            "meta": {"pages": 1, "total": 1},
        }
        monkeypatch.setattr(
            "tuskr_client.send", lambda *args, **kwargs: json.dumps(page)
        )

        raw = asyncio.run(_list_test_runs(FakeContext(), filter_project="p"))
        result = json.loads(raw)

        # Completed runs are still returned here, unlike the filter_incomplete
        # path, and meta survives so pagination keeps working.
        assert result["meta"] == {"pages": 1, "total": 1}
        assert result["rows"][0]["assignedTo"] == {
            "id": "9f1c0e2a",
            "fullName": "Test User",
            "email": "qa.lead@example.com",
        }
        assert "applicationState" not in raw
        assert "passwordResetTokenExpiresAt" not in raw


class TestAddTestRunResults:
    """Cover the bulk result endpoint wrapper."""

    def test_single_test_case_is_wrapped_in_a_list(self, env, send):
        """A bare string becomes a one-element testCases array."""
        _add_result(
            FakeContext(),
            test_run="Release Build 22-10-2021",
            status="PASSED",
            test_cases="C-2",
        )

        action, body, method = send.call_args[0]
        assert action == "test-run-result/bulk"
        assert method == main.tuskr_client.RequestMethod.POST
        assert body["testCases"] == ["C-2"]
        assert body["testRun"] == "Release Build 22-10-2021"
        assert body["status"] == "PASSED"

    def test_many_test_cases_are_sent_in_one_call(self, env, send):
        """A list of test cases produces exactly one request, not one per case."""
        _add_result(
            FakeContext(),
            test_run="Alpha 3",
            status="FAILED",
            test_cases=["C-1", "Pagination", "4ded1648-6fc9-499b-a057-0482263d2f26"],
        )

        send.assert_called_once()
        body = send.call_args[0][1]
        assert body["testCases"] == [
            "C-1",
            "Pagination",
            "4ded1648-6fc9-499b-a057-0482263d2f26",
        ]

    def test_unset_optional_fields_are_omitted(self, env, send):
        """Blank optional values are never sent; Tuskr rejects them."""
        _add_result(
            FakeContext(),
            test_run="Alpha 3",
            status="PASSED",
            test_cases="C-1",
        )

        body = send.call_args[0][1]
        assert set(body) == {"testRun", "status", "testCases"}

    def test_optional_fields_are_forwarded_when_set(self, env, send):
        """Every optional parameter maps onto its documented Tuskr key."""
        _add_result(
            FakeContext(),
            test_run="Alpha 3",
            status="FAILED",
            test_cases="C-1",
            assigned_to="peter@mycompany.co",
            comments="failed on checkout",
            time_spent_in_minutes=10,
            custom_fields={"integer": 108, "checkbox": True},
        )

        body = send.call_args[0][1]
        assert body["assignedTo"] == "peter@mycompany.co"
        assert body["comments"] == "failed on checkout"
        assert body["timeSpentInMinutes"] == 10
        assert body["customFields"] == {"integer": 108, "checkbox": True}

    def test_zero_time_spent_is_still_forwarded(self, env, send):
        """0 minutes is a real value, not an absent one."""
        _add_result(
            FakeContext(),
            test_run="Alpha 3",
            status="PASSED",
            test_cases="C-1",
            time_spent_in_minutes=0,
        )

        assert send.call_args[0][1]["timeSpentInMinutes"] == 0

    def test_empty_test_case_list_raises(self, env, send):
        """An empty list is a caller bug, not a request worth sending."""
        with pytest.raises(ValueError, match="at least one test case"):
            _add_result(
                FakeContext(),
                test_run="Alpha 3",
                status="PASSED",
                test_cases=[],
            )

        send.assert_not_called()


class TestAddTestRunResultsCredentials:
    """Header state must win over env vars; env vars must still work in stdio."""

    def test_falls_back_to_env_vars_in_stdio_mode(self, env, send):
        """Middleware sets state to None in stdio mode, so env vars are used."""
        _add_result(
            FakeContext({"ext_tenant_id": None, "ext_access_token": None}),
            test_run="Alpha 3",
            status="PASSED",
            test_cases="C-1",
        )

        kwargs = send.call_args[1]
        assert kwargs["ext_tenant_id"] == "tenant-from-env"
        assert kwargs["ext_access_token"] == "token-from-env"

    def test_header_state_beats_env_vars(self, env, send):
        """Values from HTTP headers take precedence over the environment."""
        _add_result(
            FakeContext(
                {
                    "ext_tenant_id": "tenant-from-header",
                    "ext_access_token": "token-from-header",
                }
            ),
            test_run="Alpha 3",
            status="PASSED",
            test_cases="C-1",
        )

        kwargs = send.call_args[1]
        assert kwargs["ext_tenant_id"] == "tenant-from-header"
        assert kwargs["ext_access_token"] == "token-from-header"

    def test_deprecated_account_id_env_var_still_resolves(
        self, monkeypatch, mocker, send
    ):
        """TUSKR_ACCOUNT_ID remains a working fallback after the tenant rename."""
        monkeypatch.delenv("TUSKR_TENANT_ID", raising=False)
        monkeypatch.setenv("TUSKR_ACCOUNT_ID", "tenant-legacy")
        monkeypatch.setenv("TUSKR_ACCESS_TOKEN", "token-from-env")

        _add_result(
            FakeContext(),
            test_run="Alpha 3",
            status="PASSED",
            test_cases="C-1",
        )

        assert send.call_args[1]["ext_tenant_id"] == "tenant-legacy"


# --- get_test_run_results -----------------------------------------------------
# Everything below is specific to this tool. Kept in one appended block, after
# the scaffolding shared with every other branch, so branches that add a tool
# append here instead of colliding in the shared region above.


def _get_results(ctx, **kwargs):
    """Call the get_test_run_results tool, unwrapping the @mcp.tool decorator."""
    tool = getattr(main.get_test_run_results, "fn", main.get_test_run_results)
    return asyncio.run(tool(ctx, **kwargs))


def _result_row(key="C-5", status="FAILED"):
    """A results row shaped like the real API response.

    The nested testCase is the whole test case object, so the bulk of the
    payload sits inside it rather than at row level.
    """
    return {
        "testCase": {
            "id": "24921ff9-1512-4340-b43b-852a32e82f03",
            "key": key,
            "name": "Filter by brand",
            "description": "d" * 4000,
            "customFields": {"stepsWithExpectedResults": [{"step": 1}]},
            "resultHistory": {
                f"2024-07-04T08:19:0{n}": {"runId": "old", "status": "FAILED"}
                for n in range(9)
            },
            "openIssueIds": [f"ISSUE-{n}" for n in range(400)],
            "testRunTestCases": [
                {
                    "final": True,
                    "status": status,
                    "issueIds": ["BUG-712"],
                    "testRunId": "run-1",
                    "assignedToId": None,
                }
            ],
        },
        "latestStatus": status,
    }


class TestGetTestRunResultsRequest:
    """The run is addressed in the path; filters are plain comma separated."""

    def test_run_id_goes_in_the_path(self, env, send):
        _get_results(FakeContext(), test_run="246d1fa7")

        action, body, method = send.call_args[0]
        assert action == "test-run/246d1fa7/results"
        assert method == main.tuskr_client.RequestMethod.GET
        assert body == {"page": 1}

    def test_single_status_is_sent_as_is(self, env, send):
        _get_results(FakeContext(), test_run="run-1", status="FAILED")

        assert send.call_args[0][1]["status"] == "FAILED"

    def test_status_list_becomes_comma_separated(self, env, send):
        _get_results(FakeContext(), test_run="run-1", status=["RETEST", "FAILED"])

        # Tuskr documents `status` as a comma separated string, not a repeated
        # or bracketed parameter like the filter[...] endpoints use.
        assert send.call_args[0][1]["status"] == "RETEST,FAILED"

    def test_test_cases_list_becomes_comma_separated(self, env, send):
        _get_results(
            FakeContext(),
            test_run="run-1",
            test_cases=["C-1", "Pagination", "7911ff67"],
        )

        assert send.call_args[0][1]["testCases"] == "C-1,Pagination,7911ff67"

    def test_absent_filters_are_omitted(self, env, send):
        _get_results(FakeContext(), test_run="run-1", status=None, test_cases=[])

        assert set(send.call_args[0][1]) == {"page"}

    def test_page_is_forwarded(self, env, send):
        _get_results(FakeContext(), test_run="run-1", page=3)

        assert send.call_args[0][1]["page"] == 3

    def test_falls_back_to_env_vars_in_stdio_mode(self, env, send):
        _get_results(
            FakeContext({"ext_tenant_id": None, "ext_access_token": None}),
            test_run="run-1",
        )

        kwargs = send.call_args[1]
        assert kwargs["ext_tenant_id"] == "tenant-from-env"
        assert kwargs["ext_access_token"] == "token-from-env"

    def test_header_state_beats_env_vars(self, env, send):
        _get_results(
            FakeContext(
                {
                    "ext_tenant_id": "tenant-from-header",
                    "ext_access_token": "token-from-header",
                }
            ),
            test_run="run-1",
        )

        assert send.call_args[1]["ext_tenant_id"] == "tenant-from-header"


class TestGetTestRunResultsTrimming:
    """Trimming bounds the response without dropping result information."""

    def test_nested_test_case_is_reduced_by_default(self, env, send):
        send.return_value = json.dumps({"data": [_result_row()], "meta": {"pages": 1}})

        row = json.loads(_get_results(FakeContext(), test_run="run-1"))["data"][0]

        assert set(row["testCase"]) == {"id", "key", "name", "testRunTestCases"}
        assert row["testCase"]["key"] == "C-5"
        assert row["testCase"]["name"] == "Filter by brand"

    def test_unbounded_history_fields_are_dropped(self, env, send):
        """resultHistory and openIssueIds are what blow the transport limit."""
        send.return_value = json.dumps({"data": [_result_row()]})

        trimmed = _get_results(FakeContext(), test_run="run-1")

        for dropped in ("resultHistory", "openIssueIds", "customFields"):
            assert dropped not in trimmed

    def test_this_runs_result_and_issue_keys_are_kept(self, env, send):
        """testRunTestCases is run-scoped, so it stays: it names the bug filed."""
        send.return_value = json.dumps({"data": [_result_row()]})

        row = json.loads(_get_results(FakeContext(), test_run="run-1"))["data"][0]

        assert row["testCase"]["testRunTestCases"][0]["issueIds"] == ["BUG-712"]
        assert row["testCase"]["testRunTestCases"][0]["final"] is True

    def test_latest_status_survives_trimming(self, env, send):
        send.return_value = json.dumps({"data": [_result_row(status="RETEST")]})

        row = json.loads(_get_results(FakeContext(), test_run="run-1"))["data"][0]

        assert row["latestStatus"] == "RETEST"

    def test_meta_is_preserved(self, env, send):
        send.return_value = json.dumps({"data": [], "meta": {"total": 110, "pages": 2}})

        result = json.loads(_get_results(FakeContext(), test_run="run-1"))

        assert result["meta"] == {"total": 110, "pages": 2}

    def test_trimming_is_orders_of_magnitude_smaller(self, env, send):
        raw = json.dumps({"data": [_result_row()]})
        send.return_value = raw

        trimmed = _get_results(FakeContext(), test_run="run-1")

        assert len(raw) > 8000
        assert len(trimmed) < 500

    def test_trim_response_false_returns_the_raw_body(self, env, send):
        raw = json.dumps({"data": [_result_row()], "meta": {"pages": 1}})
        send.return_value = raw

        assert _get_results(FakeContext(), test_run="run-1", trim_response=False) == raw

    def test_row_without_a_test_case_is_untouched(self, env, send):
        send.return_value = json.dumps({"data": [{"latestStatus": "PASSED"}]})

        row = json.loads(_get_results(FakeContext(), test_run="run-1"))["data"][0]

        assert row == {"latestStatus": "PASSED"}

    def test_error_body_passes_through_unchanged(self, env, send):
        send.return_value = "403 Forbidden"

        assert _get_results(FakeContext(), test_run="run-1") == "403 Forbidden"


class TestGetTestRunResultsPagination:
    """fetch_all_pages walks meta.pages; the default fetches exactly one page."""

    def test_default_fetches_one_page_only(self, env, send):
        send.return_value = json.dumps(
            {"data": [_result_row()], "meta": {"total": 110, "pages": 2}}
        )

        _get_results(FakeContext(), test_run="run-1")

        send.assert_called_once()

    def test_all_pages_are_combined(self, env, send):
        send.side_effect = [
            json.dumps(
                {"data": [_result_row(key="C-1")], "meta": {"total": 3, "pages": 3}}
            ),
            json.dumps({"data": [_result_row(key="C-2")], "meta": {"pages": 3}}),
            json.dumps({"data": [_result_row(key="C-3")], "meta": {"pages": 3}}),
        ]

        result = json.loads(
            _get_results(FakeContext(), test_run="run-1", fetch_all_pages=True)
        )

        assert [row["testCase"]["key"] for row in result["data"]] == [
            "C-1",
            "C-2",
            "C-3",
        ]
        assert [call[0][1]["page"] for call in send.call_args_list] == [1, 2, 3]
        assert result["meta"] == {"total": 3, "pages": 3}

    def test_all_pages_ignores_the_page_argument(self, env, send):
        send.return_value = json.dumps({"data": [], "meta": {"pages": 1}})

        _get_results(FakeContext(), test_run="run-1", page=7, fetch_all_pages=True)

        assert send.call_args[0][1]["page"] == 1

    def test_all_pages_still_trims(self, env, send):
        send.return_value = json.dumps({"data": [_result_row()], "meta": {"pages": 1}})

        combined = _get_results(FakeContext(), test_run="run-1", fetch_all_pages=True)

        assert "customFields" not in combined

    def test_all_pages_passes_through_a_non_json_body(self, env, send):
        send.return_value = "502 Bad Gateway"

        assert (
            _get_results(FakeContext(), test_run="run-1", fetch_all_pages=True)
            == "502 Bad Gateway"
        )


# --- list_test_cases ----------------------------------------------------------
# Everything below is specific to this tool. Kept in one appended block, after
# the scaffolding shared with every other branch, so branches that add a tool
# append here instead of colliding in the shared region above.


def _list_cases(ctx, **kwargs):
    """Call the list_test_cases tool, unwrapping the @mcp.tool decorator."""
    tool = getattr(main.list_test_cases, "fn", main.list_test_cases)
    return asyncio.run(tool(ctx, **kwargs))


class TestListTestCases:
    """Cover the test-case listing wrapper."""

    def test_project_and_default_page_are_always_sent(self, env, send):
        """A minimal call pins the project, asks for page 1, and sends nothing else."""
        _list_cases(FakeContext(), filter_project="7")

        action, params, method = send.call_args[0]
        assert action == "test-case"
        assert method == main.tuskr_client.RequestMethod.GET
        # Exact equality is the point: an unset filter must not reach Tuskr as
        # an empty query parameter.
        assert params == {"page": 1, "filter[project]": "7"}

    def test_page_is_forwarded(self, env, send):
        """Pagination is caller-controlled; the default is not hardcoded."""
        _list_cases(FakeContext(), filter_project="7", page=3)

        assert send.call_args[0][1]["page"] == 3

    def test_optional_filters_map_onto_tuskr_keys(self, env, send):
        """Every snake_case parameter becomes its camelCase filter key."""
        _list_cases(
            FakeContext(),
            filter_project="7",
            filter_test_suite="TS-1",
            filter_test_suite_section="Checkout",
            filter_key="C-2",
            filter_name="pagination",
        )

        params = send.call_args[0][1]
        assert params["filter[testSuite]"] == "TS-1"
        assert params["filter[testSuiteSection]"] == "Checkout"
        assert params["filter[key]"] == "C-2"
        assert params["filter[name]"] == "pagination"

    def test_falls_back_to_env_vars_in_stdio_mode(self, env, send):
        """Middleware sets state to None in stdio mode, so env vars are used."""
        _list_cases(
            FakeContext({"ext_tenant_id": None, "ext_access_token": None}),
            filter_project="7",
        )

        kwargs = send.call_args[1]
        assert kwargs["ext_tenant_id"] == "tenant-from-env"
        assert kwargs["ext_access_token"] == "token-from-env"

    def test_header_state_beats_env_vars(self, env, send):
        """Values from HTTP headers take precedence over the environment."""
        _list_cases(
            FakeContext(
                {
                    "ext_tenant_id": "tenant-from-header",
                    "ext_access_token": "token-from-header",
                }
            ),
            filter_project="7",
        )

        kwargs = send.call_args[1]
        assert kwargs["ext_tenant_id"] == "tenant-from-header"
        assert kwargs["ext_access_token"] == "token-from-header"
