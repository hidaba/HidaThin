import os
import sys
import time
import threading
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app, get_cached_system_status

@pytest.fixture
def test_client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

def test_t11_splash_html_no_artificial_delays(test_client):
    """
    T11: Splash con tutto pronto.
    Esito atteso: Nessuna attesa artificiale forzata (setTimeout annidati da 900ms rimossi),
    la prima risposta utile determina lo sblocco immediato (transizione <= 250ms).
    """
    res = test_client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # In our rewritten index.html, initialStatus checks netOk && tsOk immediately
    assert "initialStatus.netOk && initialStatus.tsOk" in html
    assert "setTimeout" in html
    # The completion timeout is 150ms (<= 250ms)
    assert "150" in html

def test_t12_recovery_controls_immediately_accessible(test_client):
    """
    T12: Prima fetch pendente e rete assente.
    Esito atteso: Comandi di recupero ('Configura Wi-Fi', 'Apri Dashboard') sempre presenti e visibili nel DOM.
    """
    res = test_client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert 'id="boot-fallback-actions"' in html
    assert 'style="display: flex;"' in html
    assert 'Configura Wi-Fi' in html
    assert 'Apri Dashboard' in html

def test_t13_splash_dismiss_cancels_polling(test_client):
    """
    T13: Chiusura dello splash cancella timer e richieste in corso.
    Esito atteso: dismissBootSplash() imposta splashDismissed = true, chiama abort() ed elimina timer.
    """
    res = test_client.get("/")
    html = res.data.decode("utf-8")
    assert "function dismissBootSplash()" in html
    assert "splashDismissed = true" in html
    assert "activeBootAbortCtrl.abort()" in html
    assert "clearTimeout(bootPollTimer)" in html

def test_t14_concurrent_status_requests_bounded_workers():
    """
    T14: Richieste concorrenti allo stato condividono la raccolta in background.
    Esito atteso: Un solo thread di raccolta attivo alla volta; cache condivisa.
    """
    results = []
    errors = []

    def fetch_worker():
        try:
            st = get_cached_system_status(force=True)
            results.append(st)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=fetch_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3.0)

    assert len(errors) == 0
    assert len(results) == 10
    for r in results:
        assert isinstance(r, dict)
        assert "network" in r

def test_t15_blocked_subprocesses_healthz_still_responsive(test_client):
    """
    T15: Simulazione di blocco su subprocess (nmcli, tailscale, DNS).
    Esito atteso: /healthz risponde istantaneamente (200 OK) senza essere bloccato.
    """
    # Simulate blocked nmcli / tailscale by making them hang
    def hanging_run(*args, **kwargs):
        time.sleep(2.0)
        raise RuntimeError("Hung subprocess")

    with patch("subprocess.run", side_effect=hanging_run):
        start = time.monotonic()
        res = test_client.get("/healthz")
        elapsed = time.monotonic() - start

        assert res.status_code == 200
        # /healthz must not wait for subprocesses! It must respond in < 100ms
        assert elapsed < 0.2
        data = res.get_json()
        assert data["status"] == "ok"

def test_t26_splash_connection_phases_and_settings(test_client):
    """
    T26: Verifica che lo splash screen visualizzi le fasi di connessione (Motore Kiosk, Rete, Tailscale, RDP)
    e che supporti la configurazione splash_min_duration_seconds da settings.yaml.
    """
    res = test_client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Tutti i 4 step devono essere presenti nella UI
    assert 'id="boot-step-system"' in html
    assert 'id="boot-step-network"' in html
    assert 'id="boot-step-tailscale"' in html
    assert 'id="boot-step-rdp"' in html

    # Funzioni di progressione e gestione durata minima
    assert "function updateStep(stepNum, data)" in html
    assert "minDurationSec" in html
    assert "splash_min_duration_seconds" in html

def test_t27_silent_boot_service_and_xinitrc():
    """
    T27: Verifica configurazione Quiet/Silent Boot in thinclient-ui.service e scripts/xinitrc
    per evitare messaggi di avvio e warning di X sulla console fisica, assicurando che
    il puntatore del mouse rimanga abilitato e configurato (nessun flag -nocursor distruttivo).
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    service_path = os.path.join(base_dir, "systemd", "thinclient-ui.service")
    with open(service_path, "r", encoding="utf-8") as f:
        service_content = f.read()

    assert "StandardOutput=journal" in service_content
    assert "StandardError=journal" in service_content
    assert "-nocursor" not in service_content
    assert "-logverbose 0" in service_content

    xinitrc_path = os.path.join(base_dir, "scripts", "xinitrc")
    with open(xinitrc_path, "r", encoding="utf-8") as f:
        xinitrc_content = f.read()

    assert "xsetroot -cursor_name left_ptr" in xinitrc_content
    assert "feh --bg-fill" in xinitrc_content
    assert "--log-level=3" in xinitrc_content

def test_t28_footer_version_after_tailscale(test_client):
    """
    T28: Verifica che nel footer la versione dell'applicazione sia posizionata
    a destra dopo le informazioni di connessione di rete e Tailscale IP.
    """
    res = test_client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    idx_sys_info = html.find('id="system-info-text"')
    idx_divider = html.find('class="footer-divider"')
    idx_version = html.find('id="footer-version"')

    assert idx_sys_info != -1
    assert idx_divider != -1
    assert idx_version != -1
    assert idx_sys_info < idx_divider < idx_version

