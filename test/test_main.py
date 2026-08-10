import asyncio
import json

import pytest

from src.main import _trim_assignee, list_test_runs

# Depending on the fastmcp version, @mcp.tool either leaves the plain function
# in place or wraps it in a Tool object exposing the original as `.fn`.
_list_test_runs = getattr(list_test_runs, "fn", list_test_runs)


def _user(**overrides):
    """A Tuskr user object shaped like the real API response."""
    user = {
        "id": "9f1c0e2a",
        "fullName": "Jan Figura",
        "email": "jan.figura@onetick.com",
        "applicationState": "x" * 16209,
        "passwordResetTokenExpiresAt": "2026-08-01T10:00:00Z",
        "jwtTokenInvalidBefore": "2026-07-30T09:00:00Z",
        "lastLoginAt": "2026-08-09T07:14:00Z",
    }
    user.update(overrides)
    return user


class TestTrimAssignee:
    def test_keeps_only_identifying_fields(self):
        assert _trim_assignee(_user()) == {
            "id": "9f1c0e2a",
            "fullName": "Jan Figura",
            "email": "jan.figura@onetick.com",
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


class FakeContext:
    """Minimal stand-in for the FastMCP Context used by the tool functions."""

    def __init__(self, state=None):
        self._state = state or {}

    async def get_state(self, key):
        return self._state.get(key)


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
            "fullName": "Jan Figura",
            "email": "jan.figura@onetick.com",
        }
        assert "applicationState" not in json.dumps(result)
        assert len(json.dumps(result)) < 500
