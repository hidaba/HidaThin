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
