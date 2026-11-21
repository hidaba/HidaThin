import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rdp import RDPManager, RDPSession, is_auth_error, AUTH_ERROR_CODES
from app.main import app, load_hosts_data, save_hosts_data

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_is_auth_error_detection():
    # Codes directly in AUTH_ERROR_CODES must return True
    for code in [134, 145, 133, 148, 154, 155, 131, 12, 26]:
        assert is_auth_error(code) is True

    # Standard non-auth exit codes
    assert is_auth_error(0) is False
    assert is_auth_error(141) is False  # host unreachable
    assert is_auth_error(136) is False  # graphics failure
    assert is_auth_error(23) is False   # cli args

    # Keyword detection in log snippets
    assert is_auth_error(1, "freerdp: ERRCONNECT_LOGON_FAILURE (0x00020009)") is True
    assert is_auth_error(1, "Authentication failure, check credentials.") is True
    assert is_auth_error(1, "Transport connection timeout") is False

def test_rdp_manager_status_auth_error():
    manager = RDPManager()

    # Initial status
    status = manager.get_status()
    assert status["state"] == "IDLE"
    assert status["is_auth_error"] is False
    assert status["exit_code"] is None

    # Simulate session terminating with retcode 134 (auth error)
    proc_fail = MagicMock()
    proc_fail.poll.return_value = 134
    proc_fail.wait.return_value = 134

    session = RDPSession(1, {"name": "Test Host", "hostname": "testhost"}, "user", "100.64.0.1")
    session.process = proc_fail
    manager.active_session = session

    manager._monitor_session(session)

    status = manager.get_status()
    assert status["state"] == "IDLE"
    assert status["is_auth_error"] is True
    assert status["exit_code"] == 134
    assert "Autenticazione" in status["error"]

    # Disconnect / reset clears auth error
    manager.disconnect()
    status = manager.get_status()
    assert status["is_auth_error"] is False
    assert status["exit_code"] is None

def test_rdp_manager_status_non_auth_error():
    manager = RDPManager()

    # Simulate session terminating with retcode 141 (host unreachable)
    proc_unreach = MagicMock()
    proc_unreach.poll.return_value = 141
    proc_unreach.wait.return_value = 141

    session = RDPSession(2, {"name": "Test Host", "hostname": "testhost"}, "user", "100.64.0.1")
    session.process = proc_unreach
    manager.active_session = session

    manager._monitor_session(session)

    status = manager.get_status()
    assert status["state"] == "IDLE"
    assert status["is_auth_error"] is False
    assert status["exit_code"] == 141
    assert "non raggiungibile" in status["error"]

def test_reset_failed_credentials_endpoint(client, tmp_path):
    dummy_hosts = {
        "version": 1,
        "default_host": "pc-bad",
        "hosts": {
            "pc-bad": {"name": "PC Bad", "hostname": "pc-bad", "password": "wrong_password_123"}
        }
    }
    with patch("app.main.load_hosts_data", return_value=dummy_hosts), \
         patch("app.main.save_hosts_data") as mock_save:
        res = client.post("/api/rdp/reset-failed-credentials", json={"host_key": "pc-bad"})
        assert res.status_code == 200
        assert res.get_json()["success"] is True
        assert mock_save.called
        saved_data = mock_save.call_args[0][0]
        assert "password" not in saved_data["hosts"]["pc-bad"]

def test_rdp_connect_uncredentialed_behavior(client):
    dummy_hosts = {
        "version": 1,
        "default_host": "pc-open",
        "hosts": {
            "pc-open": {"name": "PC Open", "hostname": "pc-open", "ip": "100.64.0.20"}
        }
    }
    with patch("app.main.load_hosts_data", return_value=dummy_hosts), \
         patch("app.main.get_tailscale_status", return_value={"connected": True}), \
         patch("app.main.rdp_manager.connect", return_value=(True, "OK")) as mock_rdp_connect, \
         patch("app.main.save_hosts_data") as mock_save:

        # Attempt connection without credentials
        res = client.post("/api/rdp/connect", json={
            "host_key": "pc-open",
            "username": "",
            "password": "",
            "save_password": False
        })
        assert res.status_code == 200
        assert res.get_json()["success"] is True

        # rdp_manager.connect must be called with password=None
        mock_rdp_connect.assert_called_once()
        call_kwargs = mock_rdp_connect.call_args
        assert call_kwargs[1]["password"] is None
        # save_hosts_data must NOT be called
        mock_save.assert_not_called()

def test_rdp_connect_transient_vs_saved_password(client):
    dummy_hosts = {
        "version": 1,
        "default_host": "pc-mimmo",
        "hosts": {
            "pc-mimmo": {"name": "PC Mimmo", "hostname": "pc-mimmo", "ip": "100.64.0.7"},
            "pc-officina": {"name": "PC Officina", "hostname": "pc-officina", "ip": "100.64.0.9"}
        }
    }

    # Case 1: save_password=False (Transient password)
    with patch("app.main.load_hosts_data", return_value=dict(dummy_hosts)), \
         patch("app.main.get_tailscale_status", return_value={"connected": True}), \
         patch("app.main.rdp_manager.connect", return_value=(True, "OK")) as mock_rdp_connect, \
         patch("app.main.save_hosts_data") as mock_save:

        res = client.post("/api/rdp/connect", json={
            "host_key": "pc-officina",
            "username": "temp_user",
            "password": "temp_password_123",
            "save_password": False
        })
        assert res.status_code == 200
        mock_rdp_connect.assert_called_once()
        assert mock_rdp_connect.call_args[1]["password"] == "temp_password_123"
        # Must not be saved to disk
        mock_save.assert_not_called()

    # Case 2: save_password=True (Saved password)
    with patch("app.main.load_hosts_data", return_value=dict(dummy_hosts)), \
         patch("app.main.get_tailscale_status", return_value={"connected": True}), \
         patch("app.main.rdp_manager.connect", return_value=(True, "OK")) as mock_rdp_connect, \
         patch("app.main.save_hosts_data") as mock_save:

        res = client.post("/api/rdp/connect", json={
            "host_key": "pc-officina",
            "username": "saved_user",
            "password": "permanent_pass_456",
            "save_password": True
        })
        assert res.status_code == 200
        mock_rdp_connect.assert_called_once()
        # Must be saved to disk for pc-officina only
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert saved["hosts"]["pc-officina"]["password"] == "permanent_pass_456"
        assert saved["hosts"]["pc-officina"]["username"] == "saved_user"
        # Must NOT affect other hosts
        assert "password" not in saved["hosts"]["pc-mimmo"]
        # Must NOT change default_host!
        assert saved["default_host"] == "pc-mimmo"
