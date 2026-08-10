import asyncio

import pytest

from src import main


def _add_result(ctx, **kwargs):
    """Call the add_test_run_results tool, unwrapping the @mcp.tool decorator.

    Driven with asyncio.run so the suite needs no pytest-asyncio dependency.
    """
    tool = getattr(main.add_test_run_results, "fn", main.add_test_run_results)
    return asyncio.run(tool(ctx, **kwargs))


class FakeContext:
    """Minimal stand-in for fastmcp's Context with awaitable get_state."""

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
