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
    assert "Thin Client RDP" in app.root.title()

def test_launcher_apply_data(launcher_instance):
    app = launcher_instance

    mock_status = {
        "network": {
            "primary_ip": "192.168.1.50",
            "wifi": {"connected": True, "ssid": "OfficeWiFi", "ip": "192.168.1.50", "signal": 75}
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

    app._apply_data(mock_status, mock_hosts, default_host="pc-mimmo", initial=False)

    assert app.lbl_wifi_val.cget("text") == "OfficeWiFi"
    assert app.lbl_ts_val.cget("text") == "CONNESSO"
    assert "100.68.91.18" in app.lbl_footer_info.cget("text")
    assert "pc-mimmo" in app.hosts_data
    assert "pc-studio" in app.hosts_data
    assert len(app.host_combo["values"]) == 2

def test_credentials_toggle(launcher_instance):
    app = launcher_instance
    assert app.credentials_expanded is False

    app.toggle_credentials_box()
    assert app.credentials_expanded is True
    assert "▲" in app.btn_toggle_cred.cget("text")

    app.toggle_credentials_box()
    assert app.credentials_expanded is False
    assert "▼" in app.btn_toggle_cred.cget("text")

def test_direct_rdp_countdown_and_cancel(launcher_instance):
    app = launcher_instance
    app.hosts_data = {"pc-mimmo": {"name": "PC Mimmo", "has_password": True}}
    app.default_host_key = "pc-mimmo"

    # Start countdown
    app._start_direct_rdp_countdown()
    assert app.direct_rdp_timer is not None
    assert "Avvio automatico" in app.lbl_conn_title.cget("text")

    # Cancel countdown
    app.cancel_direct_rdp()
    assert app.direct_rdp_cancelled is True
    assert app.direct_rdp_timer is None

def test_rdp_connect_flow_and_window_withdraw(launcher_instance):
    app = launcher_instance
    app.hosts_data = {"pc-mimmo": {"name": "PC Mimmo", "has_password": True}}

    with patch.object(app, "_start_rdp_session_monitor") as mock_monitor, \
         patch.object(app.root, "withdraw") as mock_withdraw:

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

def test_launcher_selection_remains_stable_across_polling(launcher_instance):
    """
    Test that when a non-default PC is selected and user fills credentials for >30s,
    periodic background status polls never reset the dropdown to the default host,
    and typed credentials remain completely untouched.
    """
    app = launcher_instance

    mock_status = {
        "network": {"wifi": {"connected": True, "ssid": "WiFi-Test"}},
        "tailscale": {"connected": True, "ip": "100.68.91.18"},
        "startup": {"mode": "dashboard"}
    }
    mock_hosts = {
        "pc-mimmo": {"name": "PC Mimmo", "hostname": "pc-mimmo", "has_password": True},
        "pc-officina": {"name": "PC Officina", "hostname": "pc-officina", "has_password": False},
        "pc-studio": {"name": "PC Studio", "hostname": "pc-studio", "username": "studio_user", "has_password": True}
    }

    # Initial boot load: default host is pc-mimmo
    app._apply_data(mock_status, mock_hosts, default_host="pc-mimmo", initial=True)
    assert app._get_selected_host_key() == "pc-mimmo"
    assert app.host_combo.current() == 0

    # User explicitly selects pc-officina (index 1)
    app.host_combo.current(1)
    app._on_host_selected()
    assert app._get_selected_host_key() == "pc-officina"

    # User opens credentials box and types username and password
    app.entry_user.delete(0, "end")
    app.entry_user.insert(0, "mario_officina")
    app.entry_pwd.delete(0, "end")
    app.entry_pwd.insert(0, "secret_password_123")
    app.var_save_pass.set(True)

    # Simulate periodic background polling (e.g. 5 ticks = 40+ seconds)
    for _ in range(5):
        app._apply_data(mock_status, mock_hosts, default_host="pc-mimmo", initial=False)
        # Selection MUST NOT be reset to default host!
        assert app._get_selected_host_key() == "pc-officina"
        assert app.host_combo.current() == 1
        # Data in modification MUST NOT be lost or overwritten!
        assert app.entry_user.get() == "mario_officina"
        assert app.entry_pwd.get() == "secret_password_123"
        assert app.var_save_pass.get() is True

def test_launcher_switching_pc_loads_and_preserves_settings(launcher_instance):
    """
    Test that switching between remote PCs:
    - Loads saved credentials for the new PC (without leaking the previous PC's password).
    - Preserves uncommitted drafts for previously modified PCs.
    """
    app = launcher_instance

    mock_status = {"network": {}, "tailscale": {}}
    mock_hosts = {
        "pc-mimmo": {"name": "PC Mimmo", "hostname": "pc-mimmo", "has_password": True},
        "pc-officina": {"name": "PC Officina", "hostname": "pc-officina", "has_password": False},
        "pc-studio": {"name": "PC Studio", "hostname": "pc-studio", "username": "studio_user", "has_password": True}
    }
    app._apply_data(mock_status, mock_hosts, default_host="pc-mimmo", initial=True)

    # 1. User selects pc-officina and types draft
    app.host_combo.current(1)
    app._on_host_selected()
    assert app._get_selected_host_key() == "pc-officina"
    app.entry_user.delete(0, "end")
    app.entry_user.insert(0, "draft_officina_user")
    app.entry_pwd.delete(0, "end")
    app.entry_pwd.insert(0, "draft_pwd_456")

    # 2. Switch to pc-studio (index 2)
    app.host_combo.current(2)
    app._on_host_selected()
    assert app._get_selected_host_key() == "pc-studio"
    # pc-studio's saved username must be loaded
    assert app.entry_user.get() == "studio_user"
    # pc-officina's password must NOT be leaked into pc-studio
    assert app.entry_pwd.get() == ""

    # 3. Switch back to pc-officina (index 1)
    app.host_combo.current(1)
    app._on_host_selected()
    assert app._get_selected_host_key() == "pc-officina"
    # Uncommitted draft must be safely restored
    assert app.entry_user.get() == "draft_officina_user"
    assert app.entry_pwd.get() == "draft_pwd_456"

def test_launcher_start_connection_without_credentials_attempts_rdp(launcher_instance):
    """
    Test that clicking Connetti on a host without saved password attempts RDP directly (Caso B)
    without blocking the user with an upfront credential dialog.
    """
    app = launcher_instance
    app.hosts_data = {
        "pc-officina": {"name": "PC Officina", "hostname": "pc-officina", "username": "tech", "has_password": False}
    }
    app.host_keys_order = ["pc-officina"]
    app.selected_host_key = "pc-officina"
    app.default_host_key = "pc-officina"

    # Input fields are empty
    app.entry_user.delete(0, "end")
    app.entry_user.insert(0, "tech")
    app.entry_pwd.delete(0, "end")

    with patch.object(app, "_do_connect") as mock_connect:
        app.start_connection()
        mock_connect.assert_called_once_with(
            "pc-officina",
            username="tech",
            password=None,
            save_password=False,
            is_uncredentialed=True,
            attempt=1
        )

def test_launcher_uncredentialed_auth_failure_triggers_credentials_dialog(launcher_instance):
    """
    Test that when an uncredentialed connection attempt fails due to authentication/NLA,
    the local credential prompt dialog opens with appropriate fields.
    """
    app = launcher_instance
    app.hosts_data = {
        "pc-officina": {"name": "PC Officina", "hostname": "pc-officina", "username": "tech", "has_password": False}
    }
    app._active_connect_params = {
        "host_key": "pc-officina",
        "username": "tech",
        "password": None,
        "is_uncredentialed": True,
        "attempt": 1
    }

    with patch.object(app, "open_credentials_dialog") as mock_dialog:
        app._on_rdp_session_ended(
            {"state": "IDLE", "is_auth_error": True, "error": "Autenticazione richiesta"},
            "PC Officina"
        )
        mock_dialog.assert_called_once_with(
            "pc-officina",
            app.hosts_data["pc-officina"],
            alert_msg=None,
            prefill_user="tech",
            attempt=1
        )

def test_credentials_dialog_creation_and_fields(launcher_instance):
    """
    Test that open_credentials_dialog constructs a compliant modal:
    - Title includes 'Connessione RDP – [Nome PC]'
    - Salva credenziali checkbox is initially UNCHECKED (False)
    - Username and password inputs are present
    """
    app = launcher_instance
    host_info = {"name": "PC Officina", "hostname": "pc-officina", "username": "mario"}

    app.open_credentials_dialog("pc-officina", host_info, prefill_user="mario", attempt=1)

    # Locate the toplevel window
    dialogs = [w for w in app.root.winfo_children() if isinstance(w, __import__("tkinter").Toplevel)]
    assert len(dialogs) == 1
    dlg = dialogs[0]

    assert "Connessione RDP – PC Officina" in dlg.title()

    # Verify checkbutton variable is False initially
    checkbuttons = [sub for w in dlg.winfo_children() for sub in w.winfo_children() if isinstance(sub, __import__("tkinter").Checkbutton)]
    assert len(checkbuttons) >= 1
    chk = checkbuttons[0]
    assert chk.cget("text") == "Salva credenziali"
    # Find boolean var associated with the checkbox
    var_name = chk.cget("variable")
    assert dlg.getvar(var_name) == 0  # 0 is False

    dlg.destroy()
