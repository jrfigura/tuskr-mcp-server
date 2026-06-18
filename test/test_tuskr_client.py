import os
import pytest
import requests

import src.tuskr_client as tuskr_client

from urllib.parse import urljoin


class TestSend:
    @pytest.fixture(params=[("http://test-url", "abcdef"), (None, "xxx")])
    def mock_envs(self, monkeypatch, request):
        base_url, access_token = request.param

        if base_url:
            monkeypatch.setenv("TUSKR_BASE_URL", base_url)
        monkeypatch.delenv("TUSKR_ACCOUNT_ID", raising=False)
        monkeypatch.setenv("TUSKR_TENANT_ID", "12345")
        monkeypatch.setenv("TUSKR_ACCESS_TOKEN", access_token)

        expected_base_url = os.environ.get(
            "TUSKR_BASE_URL", tuskr_client.TUSKR_BASE_URL
        )
        expected_base_url = urljoin(expected_base_url, os.environ["TUSKR_TENANT_ID"])

        yield expected_base_url, os.environ.get("TUSKR_ACCESS_TOKEN")

    def test_post(self, mocker, mock_envs):
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.text = "executed"
        mock_response.headers = ""

        expected_base_url, access_token = mock_envs

        mocker.patch("requests.post", return_value=mock_response)

        result = tuskr_client.send(
            "create_report", "some body", tuskr_client.RequestMethod.POST
        )

        assert result == "executed"
        requests.post.assert_called_once_with(
            f"{expected_base_url}/create_report",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"data": "some body"},
        )

    def test_get(self, mocker, mock_envs):
        mock_response = mocker.Mock()
        mock_response.status_code = 200
        mock_response.text = "executed"
        mock_response.headers = ""

        expected_base_url, access_token = mock_envs

        mocker.patch("requests.get", return_value=mock_response)

        result = tuskr_client.send(
            "create_report", "some body", tuskr_client.RequestMethod.GET
        )

        assert result == "executed"
        requests.get.assert_called_once_with(
            f"{expected_base_url}/create_report",
            headers={"Authorization": f"Bearer {access_token}"},
            params="some body",
        )


class TestTenantIdResolution:
    """Cover TUSKR_TENANT_ID / TUSKR_ACCOUNT_ID precedence and deprecation."""

    def _mock_get(self, mocker, monkeypatch):
        monkeypatch.setenv("TUSKR_ACCESS_TOKEN", "test-token")
        mock_response = mocker.Mock()
        mock_response.text = "ok"
        mocker.patch("requests.get", return_value=mock_response)

    def test_uses_new_env_var_when_set(self, monkeypatch, mocker):
        """TUSKR_TENANT_ID is honored when set."""
        monkeypatch.delenv("TUSKR_ACCOUNT_ID", raising=False)
        monkeypatch.setenv("TUSKR_TENANT_ID", "tenant-new")
        self._mock_get(mocker, monkeypatch)
        tuskr_client.send("action", {}, tuskr_client.RequestMethod.GET)
        url = requests.get.call_args[0][0]
        assert "tenant-new" in url

    def test_falls_back_to_old_env_var_with_warning(self, monkeypatch, mocker):
        """TUSKR_ACCOUNT_ID still works but emits DeprecationWarning."""
        monkeypatch.delenv("TUSKR_TENANT_ID", raising=False)
        monkeypatch.setenv("TUSKR_ACCOUNT_ID", "tenant-old")
        self._mock_get(mocker, monkeypatch)
        with pytest.warns(DeprecationWarning, match="TUSKR_ACCOUNT_ID"):
            tuskr_client.send("action", {}, tuskr_client.RequestMethod.GET)
        url = requests.get.call_args[0][0]
        assert "tenant-old" in url

    def test_new_env_var_wins_when_both_set(self, monkeypatch, mocker, recwarn):
        """When both env vars are set, new wins and NO DeprecationWarning is emitted."""
        monkeypatch.setenv("TUSKR_TENANT_ID", "tenant-new")
        monkeypatch.setenv("TUSKR_ACCOUNT_ID", "tenant-old")
        self._mock_get(mocker, monkeypatch)
        tuskr_client.send("action", {}, tuskr_client.RequestMethod.GET)
        url = requests.get.call_args[0][0]
        assert "tenant-new" in url
        assert not any(issubclass(w.category, DeprecationWarning) for w in recwarn.list)

    def test_ext_tenant_id_beats_env_vars(self, monkeypatch, mocker):
        """Caller-supplied ext_tenant_id beats env vars (fixes precedence bug)."""
        monkeypatch.setenv("TUSKR_TENANT_ID", "tenant-from-env")
        self._mock_get(mocker, monkeypatch)
        tuskr_client.send(
            "action",
            {},
            tuskr_client.RequestMethod.GET,
            ext_tenant_id="tenant-from-arg",
        )
        url = requests.get.call_args[0][0]
        assert "tenant-from-arg" in url

    def test_ext_account_id_kwarg_still_works_with_warning(self, monkeypatch, mocker):
        """Old ext_account_id kwarg works but warns."""
        monkeypatch.delenv("TUSKR_TENANT_ID", raising=False)
        monkeypatch.delenv("TUSKR_ACCOUNT_ID", raising=False)
        self._mock_get(mocker, monkeypatch)
        with pytest.warns(DeprecationWarning, match="ext_account_id"):
            tuskr_client.send(
                "action",
                {},
                tuskr_client.RequestMethod.GET,
                ext_account_id="tenant-explicit",
            )
        url = requests.get.call_args[0][0]
        assert "tenant-explicit" in url

    def test_raises_when_no_tenant_id_anywhere(self, monkeypatch):
        """Helpful ValueError if neither env var nor argument is provided."""
        monkeypatch.delenv("TUSKR_TENANT_ID", raising=False)
        monkeypatch.delenv("TUSKR_ACCOUNT_ID", raising=False)
        monkeypatch.setenv("TUSKR_ACCESS_TOKEN", "test-token")
        with pytest.raises(ValueError, match="tenant ID is not set"):
            tuskr_client.send("action", {}, tuskr_client.RequestMethod.GET)
