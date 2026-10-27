import os
import sys
import yaml
import pytest
from unittest.mock import patch, MagicMock, mock_open

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app, save_hosts_data, load_hosts_data
from app.system import remount_fs, get_managed_mountpoints
from app.vnc import set_vnc_password

@pytest.fixture
def test_client(tmp_path, monkeypatch):
    hosts_file = tmp_path / "hosts.yaml"
    initial_hosts = {
        "version": 1,
        "default_host": "pc-mimmo",
        "hosts": {
            "pc-mimmo": {"name": "PC Mimmo", "hostname": "pc-mimmo", "ip": "100.64.0.7", "port": 3389},
            "pc-officina": {"name": "PC Officina", "hostname": "pc-officina", "ip": "100.64.0.9", "port": 3389, "username": "hidab"},
            "pc-studio": {"name": "PC Studio", "hostname": "pc-studio", "ip": "100.64.0.1", "port": 3389, "password": "secret_pwd"}
        }
    }
    with open(hosts_file, "w") as f:
        yaml.safe_dump(initial_hosts, f)

    monkeypatch.setattr("app.main.HOSTS_FILE", str(hosts_file))
    monkeypatch.setattr("app.vnc.CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("app.vnc.PASS_FILE", str(tmp_path / "x11vnc.pass"))
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, hosts_file

def test_set_default_host_success(test_client):
    client, hosts_file = test_client

    res = client.post("/api/hosts/set-default", json={"key": "pc-officina"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["default_host"] == "pc-officina"
    assert "PC Officina" in data["message"]

    # Verify YAML content on disk
    with open(hosts_file, "r") as f:
        saved = yaml.safe_load(f)
    assert saved["default_host"] == "pc-officina"
    # Verify password was preserved for other hosts
    assert saved["hosts"]["pc-studio"]["password"] == "secret_pwd"
    # Verify transient display keys are not dumped
    assert "has_password" not in saved["hosts"]["pc-mimmo"]

def test_set_default_host_missing_key(test_client):
    client, _ = test_client
    res = client.post("/api/hosts/set-default", json={})
    assert res.status_code == 400
    assert res.get_json()["success"] is False

def test_set_default_host_nonexistent_key(test_client):
    client, _ = test_client
    res = client.post("/api/hosts/set-default", json={"key": "pc-inexistent"})
    assert res.status_code == 404
    assert res.get_json()["success"] is False

def test_set_default_host_ro_filesystem_auto_remount(test_client, monkeypatch):
    client, hosts_file = test_client

    calls = []
    real_write = __import__("app.main", fromlist=["write_secure_yaml"]).write_secure_yaml

    def mock_write(filepath, data):
        if not calls:
            calls.append("write_attempt_1_failed_ro")
            err = OSError(30, "Read-only file system")
            err.errno = 30
            raise err
        calls.append("write_attempt_2_success")
        return real_write(filepath, data)

    with patch("app.main.write_secure_yaml", side_effect=mock_write), \
         patch("app.main.remount_fs") as mock_remount:
        mock_remount.return_value = (True, "OK")

        res = client.post("/api/hosts/set-default", json={"key": "pc-studio"})
        assert res.status_code == 200
        assert res.get_json()["success"] is True

        # Ensure remount_fs was called with ro=False, then ro=True
        assert mock_remount.call_count == 2
        assert mock_remount.call_args_list[0][1]["ro"] is False
        assert mock_remount.call_args_list[1][1]["ro"] is True
        assert "write_attempt_2_success" in calls

def test_set_default_host_remount_write_failure_handles_cleanly(test_client):
    client, hosts_file = test_client

    with patch("app.main.write_secure_yaml", side_effect=OSError(30, "Read-only file system")), \
         patch("app.main.remount_fs") as mock_remount:
        mock_remount.return_value = (True, "OK")

        # Even if writing still fails after remount, it must return 500 without crashing Flask
        res = client.post("/api/hosts/set-default", json={"key": "pc-officina"})
        assert res.status_code == 500
        assert res.get_json()["success"] is False
        # Finally block must still restore ro=True
        assert mock_remount.call_args_list[-1][1]["ro"] is True

def test_get_managed_mountpoints(monkeypatch):
    proc_mounts = """/dev/mmcblk0p2 / ext4 ro,noatime 0 0
/dev/mmcblk0p2 /opt/thinclient/config ext4 ro,noatime 0 0
/dev/mmcblk0p2 /etc/NetworkManager/system-connections ext4 ro,noatime 0 0
/dev/mmcblk0p2 /var/lib/tailscale ext4 ro,noatime 0 0
tmpfs /tmp tmpfs rw 0 0
"""
    with patch("app.system.CONFIG_DIR", "/opt/thinclient/config"), \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=proc_mounts)):
        managed = get_managed_mountpoints()
        assert "/opt/thinclient/config" in managed
        assert "/etc/NetworkManager/system-connections" in managed
        assert "/var/lib/tailscale" in managed

def test_set_vnc_password_ro_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("app.vnc.CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("app.vnc.PASS_FILE", str(tmp_path / "x11vnc.pass"))

    calls = []
    with patch("app.vnc.shutil.which", return_value=None), \
         patch("app.vnc.remount_fs") as mock_remount:
        mock_remount.return_value = (True, "OK")

        real_open = open
        def mock_open_fn(file, mode="r", *args, **kwargs):
            if "x11vnc.pass" in str(file) and not calls:
                calls.append("failed_ro")
                err = OSError(30, "Read-only file system")
                err.errno = 30
                raise err
            return real_open(file, mode, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_fn):
            ok, msg = set_vnc_password("testpwd123")
            assert ok is True
            assert mock_remount.call_count == 2
            assert mock_remount.call_args_list[0][1]["ro"] is False
            assert mock_remount.call_args_list[1][1]["ro"] is True
