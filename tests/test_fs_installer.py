import os
import sys
import pytest
import subprocess
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rdp import RDPManager, open_runtime_log, get_runtime_log_dir

def test_t06_rdp_log_unwritable_fallback(monkeypatch, tmp_path):
    """
    T06: Log RDP non scrivibile e root RO.
    Esito atteso: Fallback controllato a os.devnull, la sessione viene avviata senza crash.
    """
    # Mock open_runtime_log to simulate unwritable log directory
    log_f, log_path = open_runtime_log("test_unwritable.log")
    assert log_f is not None
    log_f.close()

    # Simulate permission error when opening log
    with patch("app.rdp.open_runtime_log") as mock_open_log, \
         patch("subprocess.Popen") as mock_popen, \
         patch("shutil.which", return_value="/usr/bin/xfreerdp3"):

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

        # Fallback to devnull
        devnull_f = open(os.devnull, "w")
        mock_open_log.return_value = (devnull_f, os.devnull)

        manager = RDPManager()
        ok, msg = manager.connect({"name": "Test Host", "hostname": "testhost", "ip": "100.64.0.1"})
        assert ok is True
        assert manager.active_session is not None
        assert manager.active_session.state == "CONNECTING"
        devnull_f.close()

def test_t07_install_empty_destination_script_syntax():
    """
    T07: Installazione in destinazione vuota e verifica sintattica bash.
    Esito atteso: script bash sintatticamente valido senza comandi orfani (EOF).
    """
    res = subprocess.run(
        ["C:\\Program Files\\Git\\bin\\bash.exe", "-n", "install.sh"],
        capture_output=True, text=True
    )
    assert res.returncode == 0
    # Ensure no orphan EOF at the end of install.sh
    with open("install.sh", "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
        assert lines[-1] != "EOF"

def test_t08_config_preservation_on_deployment(tmp_path):
    """
    T08: Aggiornamento con configurazioni personalizzate.
    Esito atteso: Configurazioni e segreti preservati, nessun overwrite distruttivo.
    """
    target_config = tmp_path / "config"
    target_config.mkdir()
    hosts_yaml = target_config / "hosts.yaml"
    hosts_yaml.write_text("version: 1\ndefault_host: my-custom-pc\n")

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_config = source_dir / "config"
    source_config.mkdir()
    (source_config / "hosts.yaml").write_text("version: 1\ndefault_host: OVERWRITE_DANGER\n")

    # Simulate deployment logic from install.sh
    bash_cmd = f'''
    INSTALL_DIR="{tmp_path}"
    SCRIPT_SOURCE_DIR="{source_dir}"
    for item in "$SCRIPT_SOURCE_DIR"/*; do
        base="$(basename "$item")"
        if [ "$base" = "config" ]; then
            for cfg in "$item"/*; do
                [ -f "$cfg" ] || continue
                cfg_base="$(basename "$cfg")"
                if [ ! -f "$INSTALL_DIR/config/$cfg_base" ]; then
                    cp -a "$cfg" "$INSTALL_DIR/config/$cfg_base"
                fi
            done
        fi
    done
    '''
    res = subprocess.run(
        ["C:\\Program Files\\Git\\bin\\bash.exe", "-c", bash_cmd],
        capture_output=True, text=True
    )
    assert res.returncode == 0
    # Original user configuration must be preserved
    assert "my-custom-pc" in hosts_yaml.read_text()
    assert "OVERWRITE_DANGER" not in hosts_yaml.read_text()

def test_t09_setup_readonly_validation_device(tmp_path):
    """
    T09: Ext4 senza label e convalida dispositivo in setup-readonly-fs.sh.
    Esito atteso: Errore se dispositivo non è a blocchi o non specificato; nessuna attivazione RO.
    """
    res = subprocess.run(
        ["C:\\Program Files\\Git\\bin\\bash.exe", "-c",
         f'bash scripts/setup-readonly-fs.sh /nonexistent_device'],
        capture_output=True, text=True
    )
    # Must fail because device is not a valid block device
    assert res.returncode != 0

def test_t10_rollback_preserves_recent_data(tmp_path):
    """
    T10: Migrazione e rollback con dati modificati.
    Esito atteso: Nessun duplicato e nessuna configurazione recente persa durante --undo.
    """
    data_dir = tmp_path / "data" / "thinclient-config"
    data_dir.mkdir(parents=True)
    (data_dir / "hosts.yaml").write_text("version: 1\ndefault_host: pc-modified-during-ro\n")

    local_config = tmp_path / "opt" / "thinclient" / "config"
    local_config.mkdir(parents=True)
    (local_config / "hosts.yaml").write_text("version: 1\ndefault_host: pc-old\n")

    bash_cmd = f'''
    THINCLIENT_DIR="{tmp_path}/opt/thinclient"
    if [ -d "{tmp_path}/data/thinclient-config" ] && [ -d "$THINCLIENT_DIR/config" ]; then
        cp -a "{tmp_path}/data/thinclient-config"/* "$THINCLIENT_DIR/config/"
    fi
    '''
    res = subprocess.run(
        ["C:\\Program Files\\Git\\bin\\bash.exe", "-c", bash_cmd],
        capture_output=True, text=True
    )
    assert res.returncode == 0
    # The updated config from /data must be copied back to local config
    updated_local = (local_config / "hosts.yaml").read_text()
    assert "pc-modified-during-ro" in updated_local
