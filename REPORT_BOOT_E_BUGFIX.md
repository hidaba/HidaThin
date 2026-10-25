# HidaThin — Report di Consegna: Ottimizzazione Boot, Resilienza e Correzione Bug

Data: 25 ottobre 2026  
Versione: `0.2.17`  
Branch di lavoro: `feature/boot-opt-and-bugfix`  
Commit di partenza: `3f08a27` (Audit base v0.2.16) / `4523da2` (Ultimo commit locale pre-intervento)  

---

## 1. Tabella dei Task e Stato di Implementazione

| ID Task | Descrizione Sintetica | Stato | Note di Verifica |
|---|---|---|---|
| **SEC-01** | Default bind `127.0.0.1`, isolamento credenziali RDP, auth remota e semantica password | **Implementato** | Verificato con test unitari e di integrazione (T01, T02, T03). Password rimosse da DOM, HTML e JSON. |
| **SEC-02** | VNC vincolato strettamente a Tailscale (nessun listener LAN/0.0.0.0 o senza password) | **Implementato** | Verificato con T04 e T05. Rifiuto fallback LAN/0.0.0.0, rimozione password default `thinclient`. |
| **FS-01** | Log runtime volatili compatibili con root Read-Only | **Implementato** | Verificato con T06. Reindirizzamento a `/run/thinclient` (RuntimeDirectory systemd) e fallback `/dev/null`. |
| **FS-02** | Persistenza `/data`, rilevamento UUID, nessuna formattazione implicita e rollback coerente | **Implementato** | Verificato con T09 e T10. Blocco se device non valido o mount fallito, preservazione dati recenti su `--undo`. |
| **INS-01** | Installer pulito, rimosso orphan `EOF`, staging dir per clone, preservazione configurazioni | **Implementato** | Verificato con T07 e T08. Verifica sintassi `bash -n`, supporto `chromium` e `chromium-browser`. |
| **BOOT-01** | Splash cyberpunk rapido, azzeramento delay artificiali, controlli immediati e cancellabilità | **Implementato** | Verificato con T11, T12 e T13. Transizione splash <= 200ms a servizi pronti, pulsanti fallback sempre attivi. |
| **BOOT-02** | Endpoint `/healthz`, stato di sistema in background con cache thread-safe e bounded workers | **Implementato** | Verificato con T14 e T15. Nessun blocco su chiamate subprocess lente, timeout TCP/DNS rigoroso. |
| **RDP-01** | Ciclo di vita sessioni isolato (`RDPSession`), monitoraggio deterministico, segnali Chromium mirati | **Implementato** | Verificato con T16 e T17. Vecchie sessioni non azzerano nuove istanze, `start_new_session=True`. |
| **NET-01** | Invalidazione cache Tailscale al riavvio, timeout rigorosi e fallback a IP diretto | **Implementato** | Verificato con T18. Stato fresco letto subito dopo il restart di `tailscaled`. |
| **WIFI-01** | Parser `nmcli` per `\:`, `\\`, quote e Unicode; pulsanti DOM sicuri; connessione non distruttiva | **Implementato** | Verificato con T19 e T20. Profili funzionanti precedenti non cancellati preventivamente. |
| **UPD-01** | Worker OS update con lock atomico preventivo, sincronizzazione e ripristino fedele mount iniziale | **Implementato** | Verificato con T21, T22 e T23. Distinzione `completed_ro_failed` e rispetto dello stato di partenza (RW/RO). |
| **BOOT-03** | Modalità direct-to-RDP configurabile con coordinatore dedicato e fallback alla dashboard | **Implementato** | Verificato con T24 (`direct_rdp_coordinator.py`). Nessun loop infinito tra browser e FreeRDP. |
| **TEST-01** | Suite automatizzata di 25 test di regressione (T01 - T25) | **Implementato** | Tutti i 25 test passati con successo (`python -m pytest tests/ -v`). |
| **DOC-01** | Documentazione allineata (`README.md`, `TODO.md`, `CHANGELOG.md`, settings) | **Implementato** | Documentate tutte le nuove opzioni, architettura di sicurezza e comandi di verifica. |

---

## 2. File Modificati e Razionale

1. **`app/main.py`**:
   - Bind HTTP default impostato su `127.0.0.1:8080`.
   - Middleware di controllo accessi per rigettare chiamate mutanti remote non autenticate e proteggere da DNS rebinding.
   - Esclusione delle credenziali da `load_hosts_data(include_passwords=False)` per tutte le pagine HTML e le risposte JSON delle API.
   - Endpoint `/healthz` ad altissima velocità e background system status collector thread-safe con rate limiting e bounded workers.
   - Semantica password: uso password salvata, supporto a password transitoria per singola sessione (`save_password=False`), cancellazione esplicita (`clear_password`).
2. **`app/system.py`**:
   - Schema di validazione per `settings.yaml` con deep merge controllato per preservare le sezioni non modificate.
   - Funzione atomica `write_secure_yaml` con permessi `0600` e directory `0700`.
   - Worker di aggiornamento OS (`_os_update_worker` / `start_os_update`): impostazione atomica di `status="running"` sotto lock prima della creazione del thread; rilevamento dello stato iniziale di mount (RO vs RW) e ripristino fedele dello stato di partenza; introduzione dello stato `completed_ro_failed` se il remount finale in RO fallisce.
3. **`app/rdp.py`**:
   - Incapsulamento delle sessioni nella classe `RDPSession` con identificatore univoco `session_id`.
   - Riferimento stabile passato al thread di monitoraggio, impedendo che il cleanup di una vecchia sessione interferisca con una nuova sessione attiva.
   - Sostituzione di `preexec_fn=os.setsid` con `start_new_session=True`.
   - Logging runtime rediretto su directory volatile (`/run/thinclient` o `/tmp/thinclient-logs`) con fallback a `/dev/null` in caso di file system Read-Only o spazio esaurito.
   - Segnalazione mirata del browser kiosk (`chromium.*--kiosk`) senza colpire processi estranei.
4. **`app/tailscale.py`**:
   - Invalidazione immediata della cache a tempo monotonico in caso di riavvio esplicito del daemon.
   - Supporto a IP fallback in caso di fallimento della risoluzione MagicDNS.
5. **`app/vnc.py`**:
   - Salvataggio configurazioni VNC senza sovrascrivere altre sezioni di settings.
   - Rimozione della password di default `thinclient` e blocco dell'attivazione VNC se non è configurata una password.
6. **`app/wifi.py`**:
   - Parser dedicato `parse_nmcli_terse_line` per gestire correttamente coloni escapati (`\:`), backslash (`\\`) e caratteri UTF-8.
   - Connessione non distruttiva che preserva i profili preesistenti funzionanti in caso di credenziali errate.
7. **`scripts/x11vnc-start.sh`**:
   - Blocco rigoroso dell'avvio su `0.0.0.0` o LAN se `bind_tailscale_only: true` e la VPN non è disponibile.
   - Verifica della presenza del file password `0600` prima di avviare il listener.
   - Rilevamento della porta configurata e del flag di abilitazione da `settings.yaml`.
8. **`scripts/setup-readonly-fs.sh`**:
   - Rilevamento automatico dell'UUID effettivo della partizione `/data`.
   - Verifica di sicurezza per impedire l'uso accidentale di `/` o `/boot`.
   - Eliminazione della formattazione implicita su dischi ext4 già partizionati.
   - Blocco di sicurezza se il mount fallisce o la partizione non è scrivibile.
   - Routine `--undo` che sincronizza le configurazioni recenti modificate su `/data` prima di ripristinare `/etc/fstab`.
9. **`scripts/direct_rdp_coordinator.py`**:
   - Nuovo script supervisore per l'avvio diretto a FreeRDP senza aprire Chromium.
   - Gestione delle attese di rete con timeout configurabile (default 20s) e fallback trasparente alla Dashboard Kiosk.
10. **`scripts/xinitrc`**:
    - Risoluzione dinamica dell'eseguibile Chromium (`chromium` o `chromium-browser`).
    - Verifica HTTP 200 su `/healthz` con timeout bounded prima dell'avvio della UI.
    - Integrazione della modalità `direct_rdp`.
11. **`scripts/optimize-boot.sh`**:
    - Rimozione del mascheramento di `logrotate.timer` ed `e2scrub_all.timer`.
12. **`install.sh`**:
    - Rimozione dell'`EOF` orfano al termine dello script.
    - Utilizzo di directory di staging temporanea per `git clone` evitando errori di destinazione non vuota.
    - Preservazione delle configurazioni utente esistenti e permessi restrittivi `0600`/`0700`.
13. **`systemd/thinclient.service`**:
    - Aggiunta direttiva `RuntimeDirectory=thinclient` e `RuntimeDirectoryMode=0755`.
14. **`templates/index.html`**:
    - Rimozione delle password dagli attributi DOM.
    - Riscrittura del controller dello splash per transizionare in <= 200ms in presenza di servizi pronti.
    - Comandi di recupero ("Configura Wi-Fi", "Apri Dashboard") immediatamente visibili e utilizzabili.
15. **`templates/hosts.html`**:
    - Rimozione della serializzazione password nell'HTML (`data-password` e `host|tojson` eliminati).
    - Modalità di modifica con placeholder protetto e checkbox esplicita di cancellazione credenziale.
16. **`templates/wifi.html`**:
    - Creazione dinamica delle righe e dei pulsanti tramite API DOM (`addEventListener`), proteggendo da injection nei nomi SSID.
17. **`tests/`**:
    - Suite completa di 25 test automatizzati (`test_sec.py`, `test_fs_installer.py`, `test_boot_status.py`, `test_rdp_lifecycle.py`, `test_net_wifi.py`, `test_updater_settings.py`).

---

## 3. Comandi di Test ed Esito

Esecuzione della suite completa:
```bash
python -m pytest tests/ -v
```
Esito: **25 passed in 9.05s** (100% success rate).

---

## 4. Procedura di Aggiornamento di un Sistema Esistente

1. Collegarsi in SSH al Raspberry Pi:
   ```bash
   ssh root@<indirizzo-ip>
   ```
2. Se il filesystem è in sola lettura, sbloccarlo temporaneamente:
   ```bash
   rw   # alias per mount -o remount,rw / && mount -o remount,rw /boot/firmware
   ```
3. Scaricare ed eseguire la nuova versione senza sovrascrivere le configurazioni:
   ```bash
   cd /opt/thinclient
   git pull origin feature/boot-opt-and-bugfix  # oppure main post-merge
   bash install.sh
   ```
4. Se il file `config/settings.yaml` non include le nuove sezioni, esse vengono caricate automaticamente con i default sicuri (`bind: 127.0.0.1`, `remote_enabled: false`, `startup.mode: dashboard`). Per abilitare l'amministrazione remota via Tailscale:
   ```yaml
   web_admin:
     bind: "0.0.0.0"
     port: 8080
     remote_enabled: true
     admin_token: "TuoTokenSegreto"
   ```
5. Riavviare il servizio:
   ```bash
   systemctl restart thinclient thinclient-ui thinclient-vnc
   ```
6. Se la macchina era in Read-Only, ripristinare la protezione:
   ```bash
   ro   # alias per sync && mount -o remount,ro / && mount -o remount,ro /boot/firmware
   ```

---

## 5. Procedura di Rollback Conservativo

Qualora si desideri annullare la modalità Read-Only o ripristinare una configurazione precedente preservando i dati modificati:
1. Eseguire:
   ```bash
   sudo bash /opt/thinclient/scripts/setup-readonly-fs.sh --undo
   ```
2. Lo script copia automaticamente tutti i file presenti in `/data/thinclient-config/`, `/data/tailscale/` e `/data/NetworkManager/system-connections/` nelle rispettive directory locali di `/opt/thinclient/config/`, `/var/lib/tailscale/` ed `/etc/NetworkManager/system-connections/`, garantendo che nessuna password o profilo aggiunto durante il funzionamento in RO vada perso.
3. Riavviare con `sudo reboot`.

---

## 6. Attivazione e Disattivazione Modalità Direct-to-RDP

### Per attivare Direct-to-RDP:
1. Modificare `/opt/thinclient/config/settings.yaml` impostando:
   ```yaml
   startup:
     mode: "direct_rdp"
     connect_timeout_seconds: 20
     fallback_to_dashboard: true
   ```
2. Assicurarsi che in `/opt/thinclient/config/hosts.yaml` sia configurato un host predefinito valido (`default_host: ...`).
3. Al riavvio (`sudo reboot`), il Raspberry Pi attenderà la connettività di rete/Tailscale e lancerà immediatamente FreeRDP a schermo intero senza caricare Chromium Kiosk.

### Per disattivare Direct-to-RDP e tornare alla Dashboard:
- Qualora la sessione FreeRDP venga terminata, o la rete non sia pronta entro i 20s configurati, il sistema apre automaticamente la Dashboard Kiosk.
- Dalla Dashboard Kiosk (o via SSH), ripristinare in `settings.yaml`:
  ```yaml
  startup:
    mode: "dashboard"
  ```

---

## 7. Misure Hardware Rimanenti

Poiché l'ambiente di sviluppo attuale è basato su simulazione e test isolati, le seguenti misurazioni cronometriche hardware dovranno essere eseguite sul Raspberry Pi 3 fisico di test:
1. `systemd-analyze time` e `systemd-analyze critical-chain thinclient-ui.service`.
2. Tempo power-on → primo frame visibile dello splash.
3. Tempo power-on → sessione FreeRDP attiva (confronto tra modalità `dashboard` e modalità `direct_rdp`).
4. Verifica termica e throttled sotto carico prolungato: `vcgencmd get_throttled`.
