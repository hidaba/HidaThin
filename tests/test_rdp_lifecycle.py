import os
import sys
import time
import threading
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rdp import RDPManager, RDPSession, get_freerdp_error_description
import scripts.direct_rdp_coordinator as coord

def test_t16_old_session_cleanup_does_not_affect_new_session():
    """
    T16: Vecchia sessione A pulita dopo avvio di B.
    Riproduzione deterministica:
    - Sessione A termina.
    - Il monitor di A viene ritardato.
    - Nel frattempo parte la sessione B.
    - Il monitor di A riprende: non deve azzerare active_session o interrompere B!
    - B deve rimanere tracciata, attiva e disconnettibile.
    """
    manager = RDPManager()

    # Create dummy processes for A and B
    proc_a = MagicMock()
    proc_a.poll.return_value = 0
    proc_a.wait.return_value = 0

    proc_b = MagicMock()
    proc_b.poll.return_value = None
    proc_b.wait.return_value = 0

    session_a = RDPSession(1, {"name": "Host A", "hostname": "host-a"}, "user", "100.64.0.1")
    session_a.process = proc_a

    session_b = RDPSession(2, {"name": "Host B", "hostname": "host-b"}, "user", "100.64.0.2")
    session_b.process = proc_b

    # Currently active is session B
    manager.active_session = session_b

    # Run monitor on old session A
    manager._monitor_session(session_a)

    # Verification: session B MUST STILL BE ACTIVE!
    assert manager.active_session is session_b
    assert manager.active_session.session_id == 2
    assert manager.active_session.host_name == "Host B"

    # Now disconnect B cleanly
    ok, msg = manager.disconnect()
    assert ok is True
    assert proc_b.terminate.called
    assert manager.active_session is None

def test_t17_double_connect_and_cancel():
    """
    T17: Doppio Connetti e Annulla durante avvio.
    Esito atteso: Una sola sessione avviata; seconda richiesta respinta; annullamento cancella la sessione.
    """
    manager = RDPManager()
    exit_event = threading.Event()

    with patch("subprocess.Popen") as mock_popen, \
         patch("shutil.which", return_value="/usr/bin/xfreerdp3"):

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_proc.terminate.side_effect = lambda: exit_event.set()
        mock_proc.kill.side_effect = lambda: exit_event.set()
        mock_proc.wait.side_effect = lambda *args, **kwargs: exit_event.wait(timeout=2.0) and 0
        mock_popen.return_value = mock_proc

        # First connect
        ok1, msg1 = manager.connect({"name": "Host 1", "hostname": "host1"})
        assert ok1 is True
        assert manager.active_session is not None

        # Immediate second connect while first is active -> Must be rejected!
        ok2, msg2 = manager.connect({"name": "Host 2", "hostname": "host2"})
        assert ok2 is False
        assert "già attiva" in msg2

        # User cancels
        ok_disc, msg_disc = manager.disconnect()
        assert ok_disc is True
        assert manager.active_session is None
        exit_event.set()

def test_t24_direct_to_rdp_coordinator_fallback():
    """
    T24: Direct-to-RDP fallback quando non ci sono host o connettività non pronta.
    Esito atteso: Il coordinatore rileva timeout/assenza host e restituisce codice di fallback senza loop infiniti.
    """
    # 1. Mode is dashboard -> exits immediately with code 0
    with patch("scripts.direct_rdp_coordinator.get_settings", return_value={"startup": {"mode": "dashboard"}}):
        rc = coord.main()
        assert rc == 0

    # 2. Mode is direct_rdp but backend not ready -> fallback with code 1
    with patch("scripts.direct_rdp_coordinator.get_settings", return_value={"startup": {"mode": "direct_rdp"}}), \
         patch("scripts.direct_rdp_coordinator.check_backend_ready", return_value=False):
        rc = coord.main()
        assert rc == 1

    # 3. Mode is direct_rdp, backend ready, but connectivity times out -> fallback with code 1
    with patch("scripts.direct_rdp_coordinator.get_settings", return_value={"startup": {"mode": "direct_rdp", "connect_timeout_seconds": 1}}), \
         patch("scripts.direct_rdp_coordinator.check_backend_ready", return_value=True), \
         patch("scripts.direct_rdp_coordinator.wait_for_connectivity", return_value=(False, {"default_host": {"key": "pc1"}})):
        rc = coord.main()
        assert rc == 1


def test_t29_rdp_target_ip_resolution_and_error_codes():
    """
    T29: Risoluzione IP target RDP e mapping codici di errore FreeRDP.
    Verifica:
    1. Se l'host ha sia hostname che IP, connect usa l'IP (previene errore DNS 140).
    2. Se l'host ha solo hostname, connect risolve l'IP dai peer Tailscale se presente.
    3. Il codice di errore 140 (DNS not found) restituisce messaggio descrittivo anziché generico.
    """
    # 1. Error description tests
    assert "DNS" in get_freerdp_error_description(140)
    assert "password Windows errata" in get_freerdp_error_description(154)
    assert "permessi" in get_freerdp_error_description(155)

    manager = RDPManager()

    # 2. IP prioritization: host has both hostname and ip
    with patch("subprocess.Popen") as mock_popen, \
         patch("shutil.which", return_value="/usr/bin/xfreerdp3"):

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

        host_with_ip = {"name": "PC Studio", "hostname": "pc-studio", "ip": "100.64.0.1", "port": 3389}
        ok, msg = manager.connect(host_with_ip)
        assert ok is True

        cmd_args = mock_popen.call_args_list[0][0][0]
        # Must target /v:100.64.0.1 not /v:pc-studio
        assert "/v:100.64.0.1" in cmd_args

        manager.disconnect()

    # 3. Auto-resolve hostname via Tailscale peers if IP omitted
    with patch("subprocess.Popen") as mock_popen, \
         patch("shutil.which", return_value="/usr/bin/xfreerdp3"), \
         patch("app.tailscale.get_tailscale_status", return_value={
             "connected": True,
             "peers": [{"hostname": "pc-remote", "ip": "100.64.0.50"}]
         }):

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

        host_without_ip = {"name": "PC Remote", "hostname": "pc-remote"}
        ok, msg = manager.connect(host_without_ip)
        assert ok is True

        cmd_args = mock_popen.call_args_list[0][0][0]
        assert "/v:100.64.0.50" in cmd_args

        manager.disconnect()
