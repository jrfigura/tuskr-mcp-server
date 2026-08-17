import tuskr_client
from test.helpers import FakeContext, call_tool
from tuskr_mcp.tools import list_test_cases as module


def _list_cases(ctx, **kwargs):
    return call_tool(module.list_test_cases, ctx, **kwargs)


class TestListTestCases:
    """Cover the test-case listing wrapper."""

    def test_project_and_default_page_are_always_sent(self, env, send):
        """A minimal call pins the project, asks for page 1, and sends nothing else."""
        _list_cases(FakeContext(), filter_project="7")

        action, params, method = send.call_args[0]
        assert action == "test-case"
        assert method == tuskr_client.RequestMethod.GET
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
