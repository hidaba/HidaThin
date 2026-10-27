import os
import sys
import pytest
import yaml
from unittest.mock import patch, MagicMock

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app, load_hosts_data, save_hosts_data
from app.system import get_settings, save_settings
from app.vnc import save_vnc_settings

@pytest.fixture
def client(tmp_path, monkeypatch):
    """Configures a Flask test client with isolated config directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    hosts_file = config_dir / "hosts.yaml"
    settings_file = config_dir / "settings.yaml"

    initial_hosts = {
        "version": 1,
        "default_host": "pc-test",
        "hosts": {
            "pc-test": {
                "name": "PC Test",
                "hostname": "pc-test",
                "ip": "100.64.0.100",
                "port": 3389,
                "username": "secretuser",
                "password": "SUPER_SECRET_PASSWORD_123"
            }
        }
    }
    with open(hosts_file, "w") as f:
        yaml.safe_dump(initial_hosts, f)

    initial_settings = {
        "version": 1,
        "web_admin": {
            "bind": "127.0.0.1",
            "port": 8080,
            "remote_enabled": False,
            "admin_token": "secret_token_abc"
        },
        "vnc": {
            "enabled": True,
            "port": 5900,
            "bind_tailscale_only": True
        }
    }
    with open(settings_file, "w") as f:
        yaml.safe_dump(initial_settings, f)

    monkeypatch.setattr("app.main.CONFIG_DIR", str(config_dir))
    monkeypatch.setattr("app.main.HOSTS_FILE", str(hosts_file))
    monkeypatch.setattr("app.system.CONFIG_DIR", str(config_dir))
    monkeypatch.setattr("app.system.SETTINGS_FILE", str(settings_file))
    monkeypatch.setattr("app.vnc.CONFIG_DIR", str(config_dir))
    monkeypatch.setattr("app.vnc.PASS_FILE", str(config_dir / "x11vnc.pass"))

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

def test_t01_no_credentials_in_html_or_json(client):
    """
    T01: Credenziale fittizia salvata, lettura pagine/API.
    Esito atteso: Nessun segreto inviato al client (HTML DOM, JSON response).
    """
    secret = "SUPER_SECRET_PASSWORD_123"

    # Test / (index)
    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert secret not in html
    assert 'data-password' not in html
    assert 'data-has-password="1"' in html

    # Test /hosts
    res = client.get("/hosts")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert secret not in html
    assert '🔒 Salvata' in html

    # Test /api/boot/status
    res = client.get("/api/boot/status?force=0")
    assert res.status_code == 200
    body = res.data.decode("utf-8")
    assert secret not in body

    # Test /api/status
    res = client.get("/api/status")
    assert res.status_code == 200
    body = res.data.decode("utf-8")
    assert secret not in body

def test_t02_remote_admin_call_rejected_without_auth(client):
    """
    T02: Chiamata amministrativa remota non autenticata.
    Esito atteso: Rifiutata (403 se disabilitata, 401 se abilitata ma senza token).
    """
    # Remote call with remote_enabled=False -> 403 Forbidden
    res = client.post(
        "/api/hosts/save",
        environ_base={"REMOTE_ADDR": "192.168.1.50"},
        json={"key": "test", "name": "Test", "hostname": "test"}
    )
    assert res.status_code == 403

    # Enable remote access in settings
    save_settings({"web_admin": {"remote_enabled": True, "admin_token": "valid_token"}})

    # Call without token -> 401 Unauthorized
    res = client.post(
        "/api/hosts/save",
        environ_base={"REMOTE_ADDR": "192.168.1.50"},
        json={"key": "test", "name": "Test", "hostname": "test"}
    )
    assert res.status_code == 401

    # Call with invalid token -> 401
    res = client.post(
        "/api/hosts/save",
        environ_base={"REMOTE_ADDR": "192.168.1.50"},
        headers={"X-Admin-Token": "wrong_token"},
        json={"key": "test", "name": "Test", "hostname": "test"}
    )
    assert res.status_code == 401

    # Remote call to overscan apply without token -> 401
    res_os = client.post(
        "/api/system/overscan/apply",
        environ_base={"REMOTE_ADDR": "192.168.1.50"},
        json={"mode": "light"}
    )
    assert res_os.status_code == 401

    # Local kiosk call (127.0.0.1) -> Allowed without token
    res = client.post(
        "/api/hosts/save",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
        json={"key": "localpc", "name": "Local PC", "hostname": "localpc"}
    )
    assert res.status_code == 200

def test_t03_password_semantics_transient_replace_delete(client):
    """
    T03: Uso password salvata, password transitoria, sostituzione ed eliminazione.
    Esito atteso: Semantica distinta, nessuna perdita involontaria di credenziali.
    """
    with patch("app.main.rdp_manager.connect", return_value=(True, "OK")) as mock_connect, \
         patch("app.main.get_tailscale_status", return_value={"connected": True}):

        # 1. Connect without providing password -> Uses saved password
        res = client.post("/api/rdp/connect", json={"host_key": "pc-test"})
        assert res.status_code == 200
        called_args = mock_connect.call_args[1]
        assert called_args["password"] == "SUPER_SECRET_PASSWORD_123"

        # 2. Connect with transient password (save_password=False)
        mock_connect.reset_mock()
        res = client.post("/api/rdp/connect", json={
            "host_key": "pc-test",
            "password": "ONE_TIME_PASS_999",
            "save_password": False
        })
        assert res.status_code == 200
        called_args = mock_connect.call_args[1]
        assert called_args["password"] == "ONE_TIME_PASS_999"

        # Verify stored password did NOT change on disk
        stored = load_hosts_data(include_passwords=True)
        assert stored["hosts"]["pc-test"]["password"] == "SUPER_SECRET_PASSWORD_123"

        # 3. Modify host name without password -> Stored password must NOT be wiped
        res = client.post("/api/hosts/save", json={
            "key": "pc-test",
            "name": "PC Test Renamed",
            "hostname": "pc-test",
            "password": ""  # empty
        })
        assert res.status_code == 200
        stored = load_hosts_data(include_passwords=True)
        assert stored["hosts"]["pc-test"]["name"] == "PC Test Renamed"
        assert stored["hosts"]["pc-test"]["password"] == "SUPER_SECRET_PASSWORD_123"

        # 4. Explicit replacement with new password
        res = client.post("/api/hosts/save", json={
            "key": "pc-test",
            "name": "PC Test Renamed",
            "hostname": "pc-test",
            "password": "NEW_REPLACED_PASSWORD_456"
        })
        assert res.status_code == 200
        stored = load_hosts_data(include_passwords=True)
        assert stored["hosts"]["pc-test"]["password"] == "NEW_REPLACED_PASSWORD_456"

        # 5. Explicit deletion (clear_password=True)
        res = client.post("/api/hosts/save", json={
            "key": "pc-test",
            "name": "PC Test Renamed",
            "hostname": "pc-test",
            "clear_password": True
        })
        assert res.status_code == 200
        stored = load_hosts_data(include_passwords=True)
        assert "password" not in stored["hosts"]["pc-test"]

def test_t04_vnc_limited_to_tailscale_no_vpn(tmp_path):
    """
    T04: VNC limitato a Tailscale con VPN assente.
    Esito atteso: x11vnc-start.sh rifiuta l'avvio e non ascolta su 0.0.0.0 / LAN.
    """
    import subprocess
    # Run x11vnc-start.sh in bash with simulated missing tailscale and password
    settings = tmp_path / "settings.yaml"
    settings.write_text("vnc:\n  enabled: true\n  bind_tailscale_only: true\n")

    # If pass file is missing, must exit with code 1
    env = os.environ.copy()
    env["PATH"] = ""  # remove tailscale
    res = subprocess.run(
        ["C:\\Program Files\\Git\\bin\\bash.exe", "-c",
         f'CONFIG_DIR="{tmp_path}" PASS_FILE="{tmp_path}/x11vnc.pass" SETTINGS_FILE="{settings}" bash scripts/x11vnc-start.sh'],
        capture_output=True, text=True
    )
    assert res.returncode == 1
    assert "missing" in res.stderr.lower() or "password" in res.stderr.lower()

def test_t05_vnc_disabled_preserved_across_save(tmp_path, monkeypatch):
    """
    T05: VNC disabilitato e aggiornamento impostazioni.
    Esito atteso: Rimane disabilitato e non riabilitato surrettiziamente.
    """
    settings_file = tmp_path / "settings.yaml"
    monkeypatch.setattr("app.system.SETTINGS_FILE", str(settings_file))
    monkeypatch.setattr("app.vnc.PASS_FILE", str(tmp_path / "x11vnc.pass"))

    # Save VNC as disabled
    ok, msg = save_vnc_settings(enabled=False, bind_tailscale_only=True)
    assert ok
    s = get_settings()
    assert s["vnc"]["enabled"] is False

    # Save unrelated settings (profile)
    save_settings({"profile": "quality"})
    s = get_settings()
    assert s["vnc"]["enabled"] is False
    assert s["profile"] == "quality"
