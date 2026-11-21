"""
Tailscale Settings & Integration Tests for HidaThin.
Covers the 9 mandatory scenarios:
1. Attivazione Tailscale dalle impostazioni (toggle on/off).
2. Prima autenticazione alla Tailnet (login flow, auth URL).
3. Connessione RDP tramite Tailscale (magicDNS / Tailscale IP target).
4. Disattivazione Tailscale e connessione RDP tramite LAN.
5. Riavvio del thin client con Tailscale abilitato.
6. Riavvio con Tailscale disabilitato.
7. Perdita della rete e successiva riconnessione / cache TTL.
8. Tailscale non installato, non autenticato o con servizio in errore.
9. Persistenza dei profili RDP e delle impostazioni esistenti.
"""

import os
import sys
import json
import yaml
import time
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tailscale import (
    get_tailscale_status,
    is_tailscale_enabled,
    set_tailscale_enabled,
    connect_tailscale,
    disconnect_tailscale,
    login_tailscale,
    apply_boot_tailscale_state,
    is_tailscale_ip,
    is_tailscale_target,
    invalidate_tailscale_cache,
    TAILSCALE_CACHE_TTL,
)
from app.system import get_settings, save_settings, DEFAULT_SETTINGS


# --- Fixtures ---

@pytest.fixture(autouse=True)
def reset_cache_and_settings(tmp_path, monkeypatch):
    invalidate_tailscale_cache()
    tmp_settings = str(tmp_path / "settings.yaml")
    monkeypatch.setattr("app.system.SETTINGS_FILE", tmp_settings)
    initial = dict(DEFAULT_SETTINGS)
    with open(tmp_settings, "w") as f:
        yaml.safe_dump(initial, f)
    yield
    invalidate_tailscale_cache()


# --- Scenario 1: Attivazione Tailscale dalle impostazioni ---

def test_scenario1_toggle_tailscale():
    """Verify enabling and disabling Tailscale updates settings and calls connect/disconnect."""
    with patch("app.tailscale.disconnect_tailscale", return_value=(True, "Tailscale disconnesso")) as mock_disc, \
         patch("app.tailscale.connect_tailscale", return_value=(True, "Connessione avviata", None)) as mock_conn:

        # Disable
        ok, msg = set_tailscale_enabled(False)
        assert ok is True
        assert is_tailscale_enabled() is False
        mock_disc.assert_called_once()
        assert get_settings()["tailscale"]["enabled"] is False

        # Enable
        ok, msg = set_tailscale_enabled(True)
        assert ok is True
        assert is_tailscale_enabled() is True
        mock_conn.assert_called_once()
        assert get_settings()["tailscale"]["enabled"] is True


def test_scenario1_api_toggle():
    """Verify /api/tailscale/toggle REST endpoint."""
    from app.main import app
    with app.test_client() as client:
        with patch("app.tailscale.disconnect_tailscale", return_value=(True, "Tailscale disconnesso")):
            res = client.post("/api/tailscale/toggle", json={"enabled": False})
            assert res.status_code == 200
            data = res.get_json()
            assert data["success"] is True
            assert is_tailscale_enabled() is False


# --- Scenario 2: Prima autenticazione alla Tailnet ---

def test_scenario2_login_returns_auth_url():
    """Verify login flow extracts and returns auth URL when login is pending."""
    mock_out = "To authenticate, visit:\nhttps://login.tailscale.com/a/abc123xyz\n"
    with patch("shutil.which", return_value="/usr/bin/tailscale"), \
         patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = mock_out
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        ok, msg, auth_url = login_tailscale()
        assert ok is True
        assert auth_url == "https://login.tailscale.com/a/abc123xyz"
        assert "autenticazione" in msg.lower()


def test_scenario2_login_error_handling():
    """Verify login failure returns error message without auth URL."""
    with patch("shutil.which", return_value="/usr/bin/tailscale"), \
         patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "daemon error: unable to establish wireguard session"
        mock_run.return_value = mock_proc

        ok, msg, auth_url = login_tailscale()
        assert ok is False
        assert auth_url is None
        assert "daemon error" in msg.lower() or "errore" in msg.lower()


# --- Scenario 3: Connessione RDP tramite Tailscale ---

def test_scenario3_rdp_over_tailscale_connected():
    """Verify RDP connects to Tailscale host when VPN is connected."""
    from app.rdp import RDPManager

    mgr = RDPManager()
    ts_status = {
        "installed": True,
        "enabled": True,
        "connected": True,
        "status": "Connesso",
        "ip": "100.64.0.1",
        "peers": [{"hostname": "office-pc", "dns_name": "office-pc.tailnet.ts.net", "ip": "100.64.0.50"}]
    }

    with patch("app.tailscale.get_tailscale_status", return_value=ts_status), \
         patch("app.tailscale.is_tailscale_enabled", return_value=True), \
         patch("subprocess.Popen") as mock_popen, \
         patch("shutil.which", return_value="/usr/bin/xfreerdp3"):

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

        host_entry = {"name": "Office PC", "hostname": "office-pc.tailnet.ts.net", "ip": "100.64.0.50"}
        ok, msg = mgr.connect(host_entry, check_tailscale=True)
        assert ok is True
        assert "sessione rdp" in msg.lower() or "avviata" in msg.lower() or "connessione" in msg.lower()
        mgr.disconnect()


# --- Scenario 4: Disattivazione Tailscale e connessione RDP tramite LAN ---

def test_scenario4_lan_rdp_works_when_tailscale_disabled():
    """Verify LAN RDP (e.g. 192.168.1.50) connects even when Tailscale is disabled."""
    from app.rdp import RDPManager

    set_tailscale_enabled(False)
    mgr = RDPManager()

    with patch("subprocess.Popen") as mock_popen, \
         patch("shutil.which", return_value="/usr/bin/xfreerdp3"):

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

        lan_host = {"name": "Local PC", "hostname": "192.168.1.50", "ip": "192.168.1.50"}
        ok, msg = mgr.connect(lan_host, check_tailscale=True)
        assert ok is True
        mgr.disconnect()


def test_scenario4_tailscale_rdp_fails_gracefully_when_disabled():
    """Verify connecting to a Tailscale host when Tailscale is disabled returns an informative error."""
    from app.rdp import RDPManager

    set_tailscale_enabled(False)
    mgr = RDPManager()

    ts_host = {"name": "Remote TS PC", "hostname": "remote.ts.net", "ip": "100.64.0.9"}
    ok, msg = mgr.connect(ts_host, check_tailscale=True)
    assert ok is False
    assert "disabilitato" in msg.lower()


def test_scenario4_tailscale_rdp_fails_when_disconnected():
    """Verify connecting to a Tailscale host when Tailscale is enabled but disconnected returns clear error."""
    from app.rdp import RDPManager

    mgr = RDPManager()
    ts_status = {
        "installed": True,
        "enabled": True,
        "connected": False,
        "status": "Disconnesso",
        "ip": None,
        "peers": []
    }

    with patch("app.tailscale.get_tailscale_status", return_value=ts_status), \
         patch("app.tailscale.is_tailscale_enabled", return_value=True):

        ts_host = {"name": "Remote TS PC", "hostname": "remote.ts.net", "ip": "100.64.0.9"}
        ok, msg = mgr.connect(ts_host, check_tailscale=True)
        assert ok is False
        assert "non è connesso" in msg.lower() or "disconnesso" in msg.lower()


# --- Scenario 5: Riavvio con Tailscale abilitato ---

def test_scenario5_boot_state_enabled():
    """Verify apply_boot_tailscale_state connects when enabled is True."""
    set_tailscale_enabled(True)
    with patch("app.tailscale.connect_tailscale", return_value=(True, "Connessione avviata", None)) as mock_conn:
        ok, msg = apply_boot_tailscale_state()
        assert ok is True
        mock_conn.assert_called_once()


# --- Scenario 6: Riavvio con Tailscale disabilitato ---

def test_scenario6_boot_state_disabled():
    """Verify apply_boot_tailscale_state disconnects when enabled is False."""
    set_tailscale_enabled(False)
    with patch("app.tailscale.disconnect_tailscale", return_value=(True, "Tailscale disconnesso")) as mock_disc:
        ok, msg = apply_boot_tailscale_state()
        assert ok is True
        mock_disc.assert_called_once()


# --- Scenario 7: Perdita della rete e riconnessione / cache TTL ---

def test_scenario7_cache_ttl_and_force_refresh():
    """Verify monotonic cache respects TTL and force=True bypasses cache."""
    status_1 = {
        "BackendState": "Running",
        "Self": {"TailscaleIPs": ["100.64.0.1"], "HostName": "thinclient"},
        "MagicDNSSuffix": "tailnet.ts.net",
        "Peer": {}
    }
    status_2 = {
        "BackendState": "Stopped",
        "Self": {"TailscaleIPs": [], "HostName": "thinclient"},
        "MagicDNSSuffix": "",
        "Peer": {}
    }

    with patch("shutil.which", return_value="/usr/bin/tailscale"), \
         patch("subprocess.run") as mock_run:

        proc_1 = MagicMock()
        proc_1.returncode = 0
        proc_1.stdout = json.dumps(status_1)
        mock_run.return_value = proc_1

        # First call loads cache
        res1 = get_tailscale_status(force=False)
        assert res1["connected"] is True
        assert res1["ip"] == "100.64.0.1"
        assert mock_run.call_count == 1

        # Second call within TTL returns cached result without running subprocess
        proc_2 = MagicMock()
        proc_2.returncode = 0
        proc_2.stdout = json.dumps(status_2)
        mock_run.return_value = proc_2

        res_cached = get_tailscale_status(force=False)
        assert res_cached["connected"] is True
        assert mock_run.call_count == 1  # Not called again!

        # Force refresh bypasses cache
        res_forced = get_tailscale_status(force=True)
        assert res_forced["connected"] is False
        assert mock_run.call_count == 2


# --- Scenario 8: Tailscale non installato, non autenticato o servizio in errore ---

def test_scenario8_not_installed():
    """Verify missing binary is handled gracefully."""
    with patch("shutil.which", return_value=None):
        res = get_tailscale_status(force=True)
        assert res["installed"] is False
        assert res["connected"] is False
        assert res["status"] == "Non installato"
        assert "non trovato" in res["error"].lower()


def test_scenario8_needs_login_state():
    """Verify NeedsLogin backend state is mapped to 'Autenticazione richiesta'."""
    needs_login_data = {
        "BackendState": "NeedsLogin",
        "Self": {"TailscaleIPs": [], "HostName": "thinclient"},
        "AuthURL": "https://login.tailscale.com/a/login123",
        "Peer": {}
    }
    with patch("shutil.which", return_value="/usr/bin/tailscale"), \
         patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(needs_login_data)
        mock_run.return_value = mock_proc

        res = get_tailscale_status(force=True)
        assert res["installed"] is True
        assert res["connected"] is False
        assert res["status"] == "Autenticazione richiesta"
        assert res["auth_url"] == "https://login.tailscale.com/a/login123"


def test_scenario8_subprocess_exception():
    """Verify exception in subprocess execution produces 'Errore' status without crashing."""
    with patch("shutil.which", return_value="/usr/bin/tailscale"), \
         patch("subprocess.run", side_effect=RuntimeError("Subprocess timeout")):
        res = get_tailscale_status(force=True)
        assert res["installed"] is True
        assert res["connected"] is False
        assert res["status"] == "Errore"
        assert "subprocess timeout" in res["error"].lower()


# --- Scenario 9: Persistenza dei profili RDP e delle impostazioni esistenti ---

def test_scenario9_persistence_and_isolation(tmp_path, monkeypatch):
    """Verify modifying Tailscale settings preserves RDP profiles and hosts.yaml."""
    tmp_hosts = str(tmp_path / "hosts.yaml")
    monkeypatch.setattr("app.main.HOSTS_FILE", tmp_hosts)

    initial_hosts = {
        "version": 1,
        "default_host": "work-pc",
        "hosts": {
            "work-pc": {"name": "Work PC", "hostname": "work-pc", "ip": "100.64.0.10", "port": 3389},
            "lan-server": {"name": "Local Server", "hostname": "192.168.1.100", "port": 3389}
        }
    }
    with open(tmp_hosts, "w") as f:
        yaml.safe_dump(initial_hosts, f)

    # Save tailscale disabled
    with patch("app.tailscale.disconnect_tailscale", return_value=(True, "OK")):
        ok, msg = set_tailscale_enabled(False)
        assert ok is True

    # Check settings: tailscale is disabled, but all other default settings remain intact
    saved = get_settings()
    assert saved["tailscale"]["enabled"] is False
    assert saved["rdp_client"] == "hidathin-rdp"
    assert saved["profile"] == "balanced"
    assert saved["vnc"]["enabled"] is True

    # Check hosts.yaml: completely untouched
    with open(tmp_hosts, "r") as f:
        loaded_hosts = yaml.safe_load(f)
    assert loaded_hosts == initial_hosts


# --- Target Recognition Tests (IP & MagicDNS) ---

def test_is_tailscale_ip():
    """Verify CGNAT 100.64.0.0/10 and IPv6 recognition."""
    assert is_tailscale_ip("100.64.0.1") is True
    assert is_tailscale_ip("100.127.255.254") is True
    assert is_tailscale_ip("100.100.1.5") is True
    assert is_tailscale_ip("100.63.255.255") is False  # Outside /10
    assert is_tailscale_ip("100.128.0.1") is False     # Outside /10
    assert is_tailscale_ip("192.168.1.1") is False
    assert is_tailscale_ip("10.0.0.1") is False
    assert is_tailscale_ip("fd7a:115c:a1e0::1") is True
    assert is_tailscale_ip(None) is False
    assert is_tailscale_ip("") is False


def test_is_tailscale_target():
    """Verify recognition by IP, .ts.net suffix, and Tailnet peers."""
    assert is_tailscale_target({"ip": "100.64.0.5"}) is True
    assert is_tailscale_target({"hostname": "my-host.ts.net"}) is True
    assert is_tailscale_target({"hostname": "my-host.my-tailnet.ts.net."}) is True
    assert is_tailscale_target({"ip": "192.168.1.20", "hostname": "local-pc"}) is False

    # Target matching peer in tailscale status
    mock_status = {
        "installed": True,
        "connected": True,
        "magic_dns_suffix": "test-tailnet.ts.net",
        "peers": [{"hostname": "server-alpha", "dns_name": "server-alpha.test-tailnet.ts.net"}]
    }
    with patch("app.tailscale.get_tailscale_status", return_value=mock_status):
        assert is_tailscale_target({"hostname": "server-alpha"}) is True
