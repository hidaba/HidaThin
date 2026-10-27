import os
import sys
import time
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.system import (
    start_os_update, get_os_update_status, _os_update_worker, _update_state,
    save_settings, get_settings, validate_settings
)

def test_t21_concurrent_update_requests_single_worker():
    """
    T21: Due richieste contemporanee di aggiornamento OS.
    Esito atteso: Un solo lavoro avviato; seconda richiesta rifiutata con stato coerente.
    """
    # Reset update state
    _update_state["status"] = "idle"

    with patch("threading.Thread") as mock_thread:
        mock_t = MagicMock()
        mock_thread.return_value = mock_t

        ok1, msg1 = start_os_update()
        assert ok1 is True
        assert _update_state["status"] == "running"

        # Second request almost simultaneous
        ok2, msg2 = start_os_update()
        assert ok2 is False
        assert "già in corso" in msg2

def test_t22_update_apt_success_ro_remount_failed():
    """
    T22: APT riuscito ma ripristino mount fallito.
    Esito atteso: Stato finale distinto da successo completo ('completed_ro_failed').
    """
    _update_state["status"] = "running"
    _update_state["error_message"] = None

    # Simulate root was RO, but remount_fs(ro=True) fails in finally block
    with patch("app.system.remount_fs") as mock_remount, \
         patch("app.system.subprocess.run"):

        # remount rw succeeds, remount ro fails
        mock_remount.side_effect = [(True, "OK"), (False, "Device busy")]

        # Run worker with root_was_ro=True
        _os_update_worker(initial_root_ro=True, initial_boot_ro=False)

        status = get_os_update_status()
        assert status["status"] == "completed_ro_failed"
        assert "Ripristino RO fallito" in status["error_message"]

def test_t23_updater_preserves_initial_rw_state():
    """
    T23: Updater partendo da RW: ripristina lo stato iniziale senza imporre RO.
    """
    _update_state["status"] = "running"
    _update_state["error_message"] = None

    with patch("app.system.remount_fs") as mock_remount, \
         patch("app.system.subprocess.run"):

        # System was initially RW (initial_root_ro=False)
        _os_update_worker(initial_root_ro=False, initial_boot_ro=False)

        status = get_os_update_status()
        assert status["status"] == "completed"

        # remount_fs(ro=True) should NEVER have been called!
        for call_args in mock_remount.call_args_list:
            assert call_args[1].get("ro") is not True

def test_t25_partial_settings_save_and_schema_validation(tmp_path, monkeypatch):
    """
    T25: Salvataggio di una singola sezione impostazioni.
    Esito atteso: Altre sezioni conservate inalterate; schema validato.
    """
    settings_file = tmp_path / "settings.yaml"
    monkeypatch.setattr("app.system.SETTINGS_FILE", str(settings_file))

    # Initial full configuration
    initial_conf = {
        "version": 1,
        "profile": "balanced",
        "resolution": "auto",
        "color_depth": 24,
        "startup": {
            "mode": "dashboard",
            "connect_timeout_seconds": 25
        },
        "vnc": {
            "enabled": True,
            "port": 5900,
            "bind_tailscale_only": True
        }
    }
    save_settings(initial_conf)

    # 1. Partial save of ONLY profile
    ok, msg = save_settings({"profile": "performance"})
    assert ok is True

    s = get_settings()
    # profile changed
    assert s["profile"] == "performance"
    # startup and vnc preserved!
    assert s["startup"]["mode"] == "dashboard"
    assert s["startup"]["connect_timeout_seconds"] == 25
    assert s["vnc"]["enabled"] is True

    # 2. Schema validation: invalid profile
    ok_inv, msg_inv = save_settings({"profile": "invalid_mode_xyz"})
    assert ok_inv is False
    assert "Profilo non valido" in msg_inv

    # 3. Schema validation: invalid VNC port (out of range)
    ok_port, msg_port = save_settings({"vnc": {"port": 999999}})
    assert ok_port is False
    assert "Porta VNC non valida" in msg_port


def test_t26_overscan_schema_validation(tmp_path, monkeypatch):
    """
    T26: Validazione schema per la configurazione overscan.
    """
    settings_file = tmp_path / "settings.yaml"
    monkeypatch.setattr("app.system.SETTINGS_FILE", str(settings_file))

    for mode in ["none", "auto", "light", "medium"]:
        ok, msg = save_settings({"overscan": mode})
        assert ok is True
        assert get_settings()["overscan"] == mode

    ok_inv, msg_inv = save_settings({"overscan": "invalid_overscan"})
    assert ok_inv is False
    assert "Modalità overscan non valida" in msg_inv


def test_t27_apply_overscan():
    """
    T27: Applicazione hardware underscan via xrandr.
    """
    from app.system import apply_overscan

    # 1. xrandr not available
    with patch("shutil.which", return_value=None):
        ok, msg = apply_overscan("auto")
        assert ok is False
        assert "non disponibile" in msg

    # 2. xrandr available with DRM underscan support
    sample_xrandr_prop = """Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 7680 x 7680
HDMI-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 527mm x 296mm
\tEDID:
\t\t00ffffffffffff00...
\tunderscan: auto
\t\tsupported: off, on, auto
\tunderscan vborder: 0
\t\trange: (0, 128)
\tunderscan hborder: 0
\t\trange: (0, 128)
HDMI-2 disconnected (normal left inverted right x axis y axis)
"""

    mock_res_prop = MagicMock(returncode=0, stdout=sample_xrandr_prop)
    mock_res_set = MagicMock(returncode=0, stdout="", stderr="")

    with patch("shutil.which", return_value="/usr/bin/xrandr"), \
         patch("subprocess.run") as mock_subproc:

        mock_subproc.side_effect = [mock_res_prop, mock_res_set]
        ok, msg = apply_overscan("light")
        assert ok is True
        assert "HDMI-1: light" in msg

        # Verify xrandr command arguments
        set_call = mock_subproc.call_args_list[1][0][0]
        assert set_call == [
            "xrandr", "--output", "HDMI-1",
            "--set", "underscan", "on",
            "--set", "underscan hborder", "24",
            "--set", "underscan vborder", "16"
        ]

    # 3. Test mode 'none'
    with patch("shutil.which", return_value="/usr/bin/xrandr"), \
         patch("subprocess.run") as mock_subproc:

        mock_subproc.side_effect = [mock_res_prop, mock_res_set]
        ok, msg = apply_overscan("none")
        assert ok is True
        set_call = mock_subproc.call_args_list[1][0][0]
        assert set_call == [
            "xrandr", "--output", "HDMI-1",
            "--set", "underscan", "off",
            "--set", "underscan hborder", "0",
            "--set", "underscan vborder", "0"
        ]


def test_t28_overscan_api_endpoint():
    """
    T28: Endpoint API per applicazione immediata overscan.
    """
    from app.main import app
    client = app.test_client()

    with patch("app.main.apply_overscan", return_value=(True, "Applicato a: HDMI-1: light")):
        res = client.post("/api/system/overscan/apply", json={"mode": "light"})
        assert res.status_code == 200
        assert res.get_json()["success"] is True

    res_inv = client.post("/api/system/overscan/apply", json={"mode": "not_valid"})
    assert res_inv.status_code == 400
    assert res_inv.get_json()["success"] is False
