import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.launcher import NativeLauncherApp

@pytest.fixture
def launcher_instance():
    """Initializes NativeLauncherApp in windowed mode and destroys it after test."""
    with patch("app.launcher.NativeLauncherApp.refresh_all"):
        app = NativeLauncherApp(server_url="http://127.0.0.1:8080", windowed=True)
        yield app
        try:
            app.root.destroy()
        except Exception:
            pass

def test_launcher_initialization(launcher_instance):
    app = launcher_instance
    assert app.windowed is True
    assert app.server_url == "http://127.0.0.1:8080"
    assert app.is_connected_rdp is False
    assert app.root.title().startswith("HidaThin Launcher")

def test_launcher_apply_data(launcher_instance):
    app = launcher_instance

    mock_status = {
        "network": {
            "primary_ip": "192.168.1.50",
            "wifi": {"connected": True, "ssid": "OfficeWiFi", "ip": "192.168.1.50"}
        },
        "tailscale": {
            "connected": True,
            "ip": "100.68.91.18"
        },
        "startup": {
            "mode": "dashboard"
        }
    }
    mock_hosts = {
        "pc-mimmo": {"name": "PC Mimmo", "hostname": "pc-mimmo", "port": 3389, "has_password": True},
        "pc-studio": {"name": "PC Studio", "hostname": "100.64.0.1", "port": 3389, "has_password": False}
    }
    mock_fs = {"root_ro": True}

    app._apply_data(mock_status, mock_hosts, default_host="pc-mimmo", fs_info=mock_fs, initial=False)

    assert "OfficeWiFi" in app.lbl_net_status.cget("text")
    assert "100.68.91.18" in app.lbl_ts_status.cget("text")
    assert "Sola Lettura" in app.lbl_fs_status.cget("text")
    assert "pc-mimmo" in app.hosts_data
    assert "pc-studio" in app.hosts_data

def test_direct_rdp_countdown_and_cancel(launcher_instance):
    app = launcher_instance
    app.hosts_data = {"pc-mimmo": {"name": "PC Mimmo", "has_password": True}}
    app.default_host_key = "pc-mimmo"

    # Start countdown
    app._start_direct_rdp_countdown()
    assert app.direct_rdp_timer is not None
    assert "Avvio automatico" in app.banner_label.cget("text")

    # Cancel countdown
    app.cancel_direct_rdp()
    assert app.direct_rdp_cancelled is True
    assert app.direct_rdp_timer is None

def test_rdp_connect_flow_and_window_withdraw(launcher_instance):
    app = launcher_instance
    app.hosts_data = {"pc-mimmo": {"name": "PC Mimmo", "has_password": True}}

    with patch.object(app, "_start_rdp_session_monitor") as mock_monitor, \
         patch.object(app.root, "withdraw") as mock_withdraw:

        # Simulate successful connect
        app._handle_connect_result({"success": True}, "PC Mimmo")

        assert app.is_connected_rdp is True
        mock_withdraw.assert_called_once()
        mock_monitor.assert_called_once_with("PC Mimmo")

def test_rdp_session_end_restores_window(launcher_instance):
    app = launcher_instance
    app.is_connected_rdp = True

    with patch.object(app.root, "deiconify") as mock_deiconify, \
         patch.object(app, "refresh_all") as mock_refresh:

        app._on_rdp_session_ended({"state": "IDLE"}, "PC Mimmo")

        assert app.is_connected_rdp is False
        mock_deiconify.assert_called_once()
        mock_refresh.assert_called_once_with(force=True)
