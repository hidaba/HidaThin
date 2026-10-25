import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tailscale import get_tailscale_status, restart_tailscale, invalidate_tailscale_cache
from app.wifi import parse_nmcli_terse_line, connect_wifi

def test_t18_tailscale_cache_invalidation_after_restart():
    """
    T18: Cache Tailscale 'Starting', poi riavvio -> Nuova lettura 'Running', niente rifiuto da cache obsoleta.
    """
    invalidate_tailscale_cache()
    state_seq = [
        # First reading: Starting
        MagicMock(returncode=0, stdout='{"BackendState": "Starting", "Self": {"TailscaleIPs": ["100.64.0.5"]}}', stderr=""),
        # Second reading after restart: Running
        MagicMock(returncode=0, stdout='{"BackendState": "Running", "Self": {"TailscaleIPs": ["100.64.0.5"]}}', stderr="")
    ]

    with patch("shutil.which", return_value="/usr/bin/tailscale"), \
         patch("subprocess.run") as mock_run:

        mock_run.side_effect = [state_seq[0]]
        st1 = get_tailscale_status(force=False)
        assert st1["connected"] is False
        assert st1["raw_state"] == "Starting"

        # Explicit restart simulates systemctl restart tailscaled
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Restarted", stderr=""), # systemctl restart
            state_seq[1] # tailscale status
        ]
        ok, msg = restart_tailscale()
        assert ok is True

        # Now get_tailscale_status MUST return fresh Running status, not cached Starting!
        st2 = get_tailscale_status(force=False)
        assert st2["connected"] is True
        assert st2["raw_state"] == "Running"

def test_t19_ssid_parsing_with_special_characters():
    """
    T19: SSID con ':', apostrofi, backslash e caratteri Unicode.
    Esito atteso: Parsing accurato e inalterato.
    """
    # 1. Colon escaped as \:
    line_colon = r"Office\:Guest:75:WPA2:*"
    fields = parse_nmcli_terse_line(line_colon)
    assert fields == ["Office:Guest", "75", "WPA2", "*"]

    # 2. Apostrophe (e.g. L'ufficio)
    line_apos = "L'ufficio:85:WPA2-PSK: "
    fields = parse_nmcli_terse_line(line_apos)
    assert fields == ["L'ufficio", "85", "WPA2-PSK", " "]

    # 3. Backslash and Unicode
    line_unicode = r"Wi-Fi_Bar_☕\\Guest:60:WPA2:*"
    fields = parse_nmcli_terse_line(line_unicode)
    assert fields == ["Wi-Fi_Bar_☕\\Guest", "60", "WPA2", "*"]

    # 4. Quotes and potential injection strings
    line_xss = '<img src=x onerror=alert(1)>:90:Open: '
    fields = parse_nmcli_terse_line(line_xss)
    assert fields[0] == '<img src=x onerror=alert(1)>'

def test_t20_wifi_failed_connect_preserves_existing_profile():
    """
    T20: Cambio password Wi-Fi fallito.
    Esito atteso: Il profilo funzionante precedente non viene preventivamente cancellato né distrutto.
    """
    existing_uuid = "uuid-working-profile-1234"

    # Simulate existing profile for SSID "OfficeWi-Fi"
    with patch("shutil.which", return_value="/usr/bin/nmcli"), \
         patch("app.wifi._find_connection_uuids_for_ssid", return_value=[existing_uuid]), \
         patch("subprocess.run") as mock_run:

        # nmcli device wifi connect fails due to wrong password
        mock_fail = MagicMock(returncode=1, stdout="", stderr="Error: Secrets were required, but not provided.")
        mock_run.return_value = mock_fail

        ok, msg = connect_wifi("OfficeWi-Fi", "wrong_password_attempt")
        assert ok is False
        assert "Password errata" in msg or "preservata" in msg

        # Verify that delete was NEVER called for existing_uuid!
        for call_args in mock_run.call_args_list:
            cmd = call_args[0][0]
            if "delete" in cmd:
                assert existing_uuid not in cmd
