# Changelog

Tutte le modifiche rilevanti a questo progetto sono documentate in questo file.

Il formato è basato su [Keep a Changelog](https://keepachangelog.com/it/1.0.0/),
e questo progetto segue il versionamento `0.2.x`.

## [0.2.20] - 2026-10-27

### Aggiunto
- **Compensazione Automatica Bordi / Overscan TV (`app/system.py`, `app/main.py`, `scripts/xinitrc`, `templates/settings.html`, `templates/diagnostics.html`)**:
  - Implementato il supporto nativo per la correzione dell'overscan HDMI (bordi dell'interfaccia tagliati su TV e monitor multimediali) tramite proprietà DRM hardware underscan (`vc4-kms-v3d`).
  - Introdotta la nuova opzione di configurazione `overscan` in `settings.yaml` con 4 modalità selezionabili:
    - `none`: Nessuna compensazione (mappatura 1:1 pixel-perfect per monitor PC da ufficio).
    - `auto`: Rilevamento automatico basato sui flag EDID/CEA dello schermo connesso.
    - `light`: Compensazione leggera (~2.5% margini hardware: 24px orizzontale, 16px verticale).
    - `medium`: Compensazione marcata (~5% margini hardware: 48px orizzontale, 32px verticale per televisori tradizionali).
  - Aggiunto hook di avvio in `scripts/xinitrc` per applicare automaticamente l'underscan configurato su tutte le uscite video attive durante l'inizializzazione del server X11.
  - Aggiunto endpoint REST `/api/system/overscan/apply` con anteprima dinamica in tempo reale nella pagina Impostazioni: il cambio modalità dal menu a tendina aggiorna immediatamente lo schermo connesso senza richiedere riavvio.
  - Aggiornato `templates/diagnostics.html` con indicatore dedicato dello stato overscan attivo.
  - Aggiornato `install.sh` per includere `overscan: "auto"` nel template di configurazione default e disabilitare l'overscan firmware legacy in `config.txt` (`disable_overscan=1`) a favore del controllo dinamico KMS.
  - Aggiunti test automatizzati di validazione schema e comandi xrandr (T26, T27, T28) in `tests/test_updater_settings.py` e controllo accessi in `tests/test_sec.py`.

## [0.2.19] - 2026-10-27

### Risolto
- **Posizione Versione Software nel Footer (`templates/base.html`)**:
  - Spostato il badge della versione dell'applicazione (`footer-version`) alla destra delle informazioni di rete e connessione Tailscale (`system-info-text`), posizionandolo dopo il Tailscale IP separato da un dot divider (`•`), migliorando la leggibilità complessiva della barra di stato inferiore.
  - Aggiunto il test di regressione T28 in `tests/test_boot_status.py` per garantire l'ordine degli elementi nel footer.
- **Ripristino Visibilità Cursore Mouse (`systemd/thinclient-ui.service`, `scripts/xinitrc`, `install.sh`)**:
  - Rimosso il flag distruttivo `-nocursor` dal comando di avvio di Xorg in `thinclient-ui.service`. In Xorg, il parametro `-nocursor` disabilita a livello globale il rendering dello sprite del puntatore per l'intera sessione (Chromium Kiosk, Openbox e FreeRDP), rendendo il mouse completamente invisibile all'utente.
  - Configurato il cursore predefinito in `scripts/xinitrc` tramite `xsetroot -cursor_name left_ptr`, eliminando alla radice l'antiquato puntatore a "X" della font root X11 e garantendo un puntatore a freccia standard e visibile fin dal caricamento dello splash screen.
  - Aggiunto il pacchetto `adwaita-icon-theme` all'array `PACKAGES_CORE` in `install.sh` per fornire temi cursore moderni e vettoriali out-of-the-box.
  - Aggiornato il test di regressione T27 in `tests/test_boot_status.py` per garantire che `-nocursor` non venga reintrodotto e che `xsetroot -cursor_name left_ptr` sia sempre configurato in `xinitrc`.

## [0.2.18] - 2026-10-26

### Esperienza Utente & Avvio Grafico (Silent Boot & Splash Screen)
- **Avvio Silenzioso di Xorg e Soppressione Warning Console (`systemd/thinclient-ui.service`, `scripts/xinitrc`)**:
  - Reindirizzati `StandardOutput` e `StandardError` su `journal` in `thinclient-ui.service`, impedendo a `xinit`, `Xorg`, script shell e Chromium di stampare scritte di caricamento o warning a video su `/dev/tty1`.
  - Introdotti flag `-nocursor` e `-logverbose 0` nella riga di comando di Xorg per eliminare il puntatore nero grezzo a "X" e azzerare i log a console.
  - Aggiunto flag `--log-level=3` all'avvio di Chromium Kiosk per sopprimere i warning su stderr.
  - Configurazione automatica nel file `/boot/firmware/cmdline.txt` (`quiet loglevel=3 logo.nologo consoleblank=0 vt.global_cursor_default=0`) e `/boot/firmware/config.txt` (`disable_splash=1`) tramite `install.sh` per un boot silenzioso dall'accensione ad X11.
- **Visualizzazione Immediata dello Sfondo Splash in X11 (`scripts/xinitrc`, `install.sh`)**:
  - Integrato `feh --bg-fill` all'avvio di Openbox per impostare all'istante l'immagine di sfondo Cyberpunk sul root window X11, eliminando la schermata scura/vuota nei secondi di caricamento di Chromium.
  - Aggiunto il pacchetto `feh` tra le dipendenze base in `install.sh`.
- **Progressione Fluida delle Fasi di Connessione nello Splash (`templates/index.html`, `config/settings.yaml`, `app/system.py`)**:
  - Implementata una sequenza fluida e cadenzata per mostrare le 4 fasi di stato prima della dashboard:
    1. `[01/04] MOTORE KIOSK HIDATHIN` (Flask & X11)
    2. `[02/04] CONNESSIONE DI RETE` (Wi-Fi con SSID/IP oppure Ethernet)
    3. `[03/04] TUNNEL VPN TAILSCALE WIREGUARD` (Stato WireGuard e IP 100.x)
    4. `[04/04] VERIFICA HOST RDP REMOTO` (Raggiungibilità porta 3389)
  - Introdotto parametro configurabile `startup.splash_min_duration_seconds` (default: 2 secondi) per consentire all'utente di verificare visivamente i check di connessione prima del fade-out alla dashboard principale (oppure impostare `0` per l'avvio istantaneo).
  - Comandi di recupero ("Configura Wi-Fi", "Apri Dashboard") sempre immediatamente cliccabili con interruzione istantanea dello splash.
- **Test Automatizzati (`tests/test_boot_status.py`)**:
  - Aggiunti test di regressione T26 (validazione delle fasi di connessione e supporto dwell time) e T27 (verifica configurazione Silent Boot su systemd e xinitrc).

## [0.2.17] - 2026-10-25

### Sicurezza (SEC-01 & SEC-02)
- **Bind Locale e Protezione Accesso Remoto (`app/main.py`, `config/settings.yaml`)**:
  - Impostato il bind default del backend Flask a `127.0.0.1:8080`.
  - Introdotti controlli di accesso (`web_admin.remote_enabled`, `web_admin.admin_token`) che rifiutano chiamate remote mutanti prive di autorizzazione (403/401) e verificano l'header `Host` contro attacchi di DNS rebinding.
  - Kiosk locale ed overlay OSD continuano a operare senza frizioni su loopback.
- **Rimozione Credenziali dai Flussi Frontend & API (`templates/index.html`, `templates/hosts.html`, `app/main.py`)**:
  - Eliminate le password in chiaro da tutti i file HTML, attributi DOM (`data-password`) e risposte JSON delle API.
  - Esposto unicamente il flag booleano `has_password`.
  - Definita la semantica rigorosa delle password: campo vuoto significa "nessuna sostituzione" (conserva la password esistente nel backend); la cancellazione richiede azione esplicita (`clear_password`); supporto a password transitorie per singola sessione (`save_password=False`).
  - Permessi restrittivi `0600` e directory `0700` per i file di configurazione (`hosts.yaml`, `settings.yaml`, `x11vnc.pass`).
- **VNC Strettamente Vincolato a Tailscale (`scripts/x11vnc-start.sh`, `app/vnc.py`)**:
  - Con `bind_tailscale_only: true`, eliminato il fallback insicuro a `0.0.0.0` o LAN: se la VPN Tailscale non è pronta, il launcher termina con codice di errore lasciando che systemd ritenti.
  - Eliminata la password comune hardcoded `thinclient` dalle nuove installazioni: richiesta configurazione esplicita della password prima di consentire l'ascolto VNC.

### Affidabilità Filesystem e Installer (FS-01, FS-02, INS-01)
- **Logging Runtime Volatile e Root Read-Only (`app/rdp.py`, `systemd/thinclient.service`)**:
  - Spostati i log di runtime in directory volatile (`/run/thinclient`, configurata con `RuntimeDirectory=thinclient` in systemd).
  - Gestione resiliente degli errori: fallback controllato su `/dev/null` in caso di file system protetto o esaurimento inode, evitando il blocco delle sessioni RDP.
- **Persistenza `/data`, Migrazione e Rollback Idempotente (`scripts/setup-readonly-fs.sh`)**:
  - Rilevamento automatico dell'UUID effettivo della partizione senza assumere label fisse (`HidaData`).
  - Verifica di sicurezza per impedire la selezione accidentale delle partizioni root (`/`) o boot.
  - Eliminata la formattazione implicita di partizioni ext4 già contenenti dati.
  - Blocco preventivo dell'attivazione RO se il mount di `/data` fallisce o non è scrivibile.
  - Rollback (`--undo`) coerente che preserva le configurazioni più recenti create su `/data` prima del ripristino di `/etc/fstab`.
- **Installer Pulito e Conservativo (`install.sh`)**:
  - Clonazione sicura tramite directory di staging per evitare collisioni in destinazioni non vuote.
  - Rimosso l'`EOF` orfano al termine dello script.
  - Separazione netta tra codice e configurazione utente (nessuna sovrascrittura di file esistenti).
  - Supporto trasparente a entrambi i pacchetti browser `chromium` e `chromium-browser`.

### Performance di Avvio e Gestione Stato (BOOT-01, BOOT-02)
- **Splash Cyberpunk Istantaneo e Non Bloccante (`templates/index.html`)**:
  - Eliminati tutti i delay artificiali (`setTimeout` annidati): se la rete e la VPN sono già attive, la schermata di splash transiziona in <= 200ms.
  - Comandi di recupero ("Configura Wi-Fi", "Apri Dashboard") immediatamente visibili e utilizzabili anche in assenza di rete.
  - Polling a richiesta singola con `AbortController` e cancellazione immediata alla chiusura dello splash.
- **Endpoint Locale `/healthz` e Cache di Stato in Background (`app/main.py`)**:
  - Introdotto endpoint `/healthz` ad altissima velocità (nessun subprocess, nessuna chiamata a rete/DNS).
  - Raccolta dello stato del sistema in background con cache thread-safe e TTL a tempo monotonico (`time.monotonic()`), evitando spawn multipli di subprocess su richieste concorrenti.
  - Timeout restrittivi e fallback da hostname a indirizzo IP diretto per la verifica di raggiungibilità dei PC RDP.
  - Rimosso il mascheramento indiscriminato di `logrotate.timer` da `scripts/optimize-boot.sh`.

### Ciclo di Vita Sessioni, Rete e Aggiornamenti (RDP-01, NET-01, WIFI-01, UPD-01)
- **Isolamento Sessioni FreeRDP e Coordinamento Kiosk (`app/rdp.py`)**:
  - Creata la classe `RDPSession` con identificatore univoco `session_id`. Il thread di monitoraggio sorveglia esclusivamente la propria istanza e non altera sessioni successive.
  - Sostituito `os.setsid` con `start_new_session=True`.
  - Segnalazione `SIGSTOP`/`SIGCONT` mirata esclusivamente ai processi del browser kiosk (`chromium.*--kiosk`), senza impattare altri processi utente.
- **Invalidazione Cache Tailscale e Parsing Wi-Fi Robusto (`app/tailscale.py`, `app/wifi.py`, `templates/wifi.html`)**:
  - Invalidazione immediata della cache Tailscale in caso di riavvio del daemon.
  - Parser rigoroso per l'output terse di `nmcli` in grado di gestire `\:`, `\\`, apostrofi, virgolette e caratteri UTF-8.
  - Costruzione dei pulsanti Wi-Fi tramite API DOM (`addEventListener`), azzerando vulnerabilità di iniezione JavaScript nei nomi delle reti.
  - Procedura di connessione Wi-Fi non distruttiva che preserva il profilo funzionante precedente in caso di credenziali errate.
- **Aggiornamento OS Debian Atomico e Preservazione Mount (`app/system.py`)**:
  - Impostazione dello stato `running` sotto lock prima della creazione del worker thread, prevenendo update concorrenti.
  - Memorizzazione dello stato di mount iniziale (RO vs RW) e ripristino fedele dello stato di partenza (nessuna imposizione di RO su sistemi originariamente RW).
  - Segnalazione dello stato `completed_ro_failed` se i pacchetti APT sono aggiornati ma il remount RO non va a buon fine.

### Modalità Direct-to-RDP (BOOT-03)
- **Avvio Diretto a RDP Configurabile (`scripts/direct_rdp_coordinator.py`, `scripts/xinitrc`, `config/settings.yaml`)**:
  - Introdotta la modalità `startup.mode: direct_rdp` (disattivata per default).
  - Coordinatore dedicato che attende la connettività di rete e avvia la sessione verso l'host predefinito lasciando inizialmente spento Chromium.
  - Fallback automatico e trasparente alla Dashboard Kiosk in caso di timeout, errore o disconnessione della sessione RDP, senza cicli infiniti tra browser e FreeRDP.

### Suite di Test Integrata (TEST-01)
- **25 Test di Regressione Automatizzati (`tests/`)**:
  - Coperti tutti gli scenari richiesti: T01-T05 (Sicurezza), T06-T10 (Filesystem & Installer), T11-T15 (Boot & Healthz), T16-T17-T24 (RDP Lifecycle & Coordinator), T18-T20 (Rete & Wi-Fi), T21-T23-T25 (Updater & Settings Schema).

## [0.2.16] - 2026-10-25

### Risolto e Perfezionato (Boot Read-Only & Appliance Mode)
- **Eliminazione Definitiva Errori di Swap al Boot (`scripts/setup-readonly-fs.sh`, `/etc/rpi/swap.conf`)**:
  - Rimozione preventiva del file residuo `/var/swap` su disco SD prima del mount RO e configurazione di `Mechanism=zram` per allocazione swap pura in RAM compressa.
  - Mascherati definitivamente i servizi di gestione swap su MicroSD (`rpi-resize-swap-file`, `rpi-remove-swap-file@`, `rpi-setup-loop@var-swap`, `dphys-swapfile`) azzerando i messaggi di errore e i fallimenti al boot (`0 failed units`).
- **Stabilizzazione Avvio Chromium & Xorg su Filesystem Read-Only (`scripts/xinitrc`, `systemd/thinclient-ui.service`)**:
  - Reindirizzati i parametri `--user-data-dir` e `--disk-cache-dir` di Chromium su directory volatili in `/tmp` (tmpfs), risolvendo la schermata nera da crash continuo all'avvio.
  - Reindirizzato il log del server grafico Xorg su `/tmp/Xorg.0.log` per evitare blocchi al momento del remount RO.

## [0.2.15] - 2026-10-25

### Aggiunto
- **Installer One-Liner Automatizzato per Raspbian / Debian (`install.sh`, `scripts/install.sh`)**:
  - Creato script di installazione rapida e chiavi in mano eseguibile direttamente tramite `curl -sSL https://raw.githubusercontent.com/hidaba/HidaThin/main/install.sh | sudo bash` o in locale con `sudo bash install.sh`.
  - Installazione e configurazione automatizzata di tutti i pacchetti di sistema (Xorg, Openbox, Chromium kiosk, Python 3, Flask, FreeRDP 3, x11vnc, NetworkManager, wireless-tools).
  - Installazione e abilitazione automatica di Tailscale WireGuard Mesh.
  - Sincronizzazione / clonazione del repository in `/opt/thinclient` con corretta impostazione dei permessi utente e cartelle di log.
  - Applicazione delle ottimizzazioni hardware: configurazione puntatore Xorg lineare 1:1 (`flat` profile), tuning frequenza di polling USB a 500 Hz (`usbhid.mousepoll=2`), allocazione memoria GPU a 128 MB (`gpu_mem=128`) e abbattimento usura MicroSD (`vm.swappiness=10`).
  - Esecuzione automatica dello script di Fast Boot per mascherare i servizi di background bloccanti o non necessari.
  - Registrazione, abilitazione all'avvio e avvio immediato dei servizi systemd (`thinclient.service`, `thinclient-ui.service`, `thinclient-vnc.service`, `cpu-governor.service`).
  - Aggiunto wrapper `scripts/install.sh` per compatibilità da qualsiasi directory di esecuzione.
- **Regola di Sviluppo in `GEMINI.md`**:
  - Registrata la regola vincolante di manutenzione per garantire che `install.sh` sia sempre tenuto aggiornato ad ogni modifica che coinvolge aggiunta, rimozione o variazione di file o dipendenze nel repository.



## [0.2.14] - 2026-10-25

### Resilienza e Manutenzione
- **Filesystem Read-Only con Partizione Persistente /data (Soluzione B)**:
  - **Script di Configurazione Automatizzato (`scripts/setup-readonly-fs.sh`)**: configurazione di root (`/`) e `/boot/firmware` in sola lettura (`ro`) in `/etc/fstab`, mount bind persistenti per configurazioni HidaThin, credenziali Tailscale e profili Wi-Fi NetworkManager, partizioni RAM volatili `tmpfs` (`/tmp`, `/var/tmp`, `/var/log`, `/var/spool`) e storage volatile per systemd-journald.
  - **Aggiornamento Sistema Operativo Debian con Gestione RW/RO Garantita (`app/system.py`)**: implementato worker in background che sblocca il filesystem in scrittura (`rw`), lancia `apt update` e `apt dist-upgrade -y`, pulisce i pacchetti obsoleti con `clean`/`autoremove`, esegue il flush dei buffer fisici con `sync` e ripristina garantito (in blocco `finally`) lo stato Read-Only (`ro`).
  - **Interfaccia Web per Manutenzione & Aggiornamento (`templates/settings.html`, `static/css/style.css`)**: aggiunta sezione dedicata in Impostazioni con badge di stato real-time (`SOLA LETTURA (SD Protetta)` vs `SCRITTURA (RW)`), pulsante di toggle sblocco manuale e pulsante di aggiornamento OS Debian con finestra modale terminale a scorrimento automatico e barra di avanzamento.
  - **Stato Filesystem in Diagnostica (`templates/diagnostics.html`)**: esposto lo stato di mount di root e della partizione `/data` nella dashboard diagnostica.
  - **Fallback Automatico Scrittura Config (`app/main.py`, `app/system.py`)**: salvataggio automatico con sblocco temporaneo on-demand in caso di filesystem protetto per `hosts.yaml` e `settings.yaml`.

## [0.2.13] - 2026-10-25

### Ottimizzazione e Boot Speed
- **Script di Pruning & Masking Aggressivo dei Servizi Systemd (`scripts/optimize-boot.sh`)**:
  - Creato script automatizzato per disabilitare e mascherare tutti i demoni in background e timer non necessari per un thin client dedicato (risparmio di ~2-4s di tempo di avvio e abbattimento dei colli di bottiglia di I/O su MicroSD).
  - Mascherati timer periodici pesanti: `apt-daily.timer`, `apt-daily-upgrade.timer`, `man-db.timer`, `e2scrub_all.timer`, `logrotate.timer`.
  - Disabilitati demoni non utilizzati: `cups` (stampa locale), `avahi-daemon` (mDNS ridondante con Tailscale MagicDNS), `ModemManager`, `triggerhappy` (tasti multimediali), `plymouth` (splash generico non necessario con kiosk X11 diretto), `bluetooth` e `hciuart`.
  - Disabilitate le sincronizzazioni bloccanti al boot: `systemd-udev-settle.service` e `systemd-time-wait-sync.service` per evitare stalli nell'avvio della sessione grafica.
  - Aggiunto parametro `--undo` per il ripristino immediato dei servizi all'occorrenza.
  - Documentata procedura di esecuzione in [README.md](file:///y:/Progetti/thinclient/README.md) e tracciata la roadmap in [TODO.md](file:///y:/Progetti/thinclient/TODO.md).

## [0.2.12] - 2026-10-25

### Risolto e Ottimizzato
- **Eliminazione Inerzia e Latenza di Risposta del Mouse (Locale & RDP)**:
  - **Profilo di Accelerazione Lineare Diretto (`flat`)**: configurato Xorg (`/etc/X11/xorg.conf.d/50-mouse.conf`) con `Option "AccelProfile" "flat"` e `Option "AccelSpeed" "0.2"`. Il profilo predefinito di `libinput` (`adaptive`) applicava un filtro temporale di smoothing (isteresi) e una curva di decelerazione a basse velocità, provocando un marcato effetto "spugna/inerzia" nel puntatore. Con `flat`, il tracciamento del cursore è 1:1, istantaneo e privo di qualsiasi decelerazione o curva artificiale.
  - **Aumento Frequenza Polling USB Hardware (`usbhid.mousepoll=2`)**: forzato il polling USB a 500Hz (2ms) sia a runtime che in `/boot/firmware/cmdline.txt`, abbattendo la latenza di lettura dei pacchetti USB da 10ms a soli 2ms.
  - **Rimozione Demone `unclutter` (`scripts/xinitrc`)**: eliminato il demone `unclutter` che nascondeva il cursore dopo 3 secondi di inattività tramite subwindow X11 invisibile, azzerando l'esitazione e il micro-freeze alla ripresa del movimento del mouse.
  - **Disattivazione Soglie di Accelerazione Legacy X11 (`xset m 1 1`)**: impostato mapping lineare 1:1 nel server X eliminando salti di soglia tra movimenti lenti e veloci.
  - **Mitigazione Interferenze RF 2.4GHz Dongle Wireless**: documentata l'interferenza EMI nota tra HDMI/Wi-Fi e i ricevitori nano-USB su Raspberry Pi 3, raccomandando l'uso di una prolunga USB se si rilevano jitter residui.

## [0.2.11] - 2026-10-25

### Risolto e Migliorato
- **Gestione Robusta Cambio Rete Wi-Fi & Risoluzione Conflitti Credenziali**:
  - **Pulizia Automatica Profili Conflittuali (`app/wifi.py`)**: implementata rimozione preventiva di qualsiasi profilo NetworkManager obsoleto o danneggiato associato all'SSID di destinazione prima di tentare l'attivazione. In precedenza, se l'utente inseriva una password errata o cambiava rete, NetworkManager creava un profilo corrotto in stato `need-auth` provocando il blocco sistematico `no secrets: No agents were available for this request` anche nei successivi tentativi con password corretta.
  - **Rollback Pulito su Errore**: in caso di handshake fallito, timeout o credenziali respinte dal punto di accesso, il profilo temporaneo non funzionante viene cancellato immediatamente da NetworkManager evitando tentativi di riconnessione in background a vuoto.
  - **Feedback Utente Chiaro in Lingua Italiana**: mappatura degli errori di basso livello di `nmcli` in messaggi amichevoli e precisi (es. password errata/handshake WPA fallito, rete non trovata, timeout segnale debole).
  - **Invalidazione Istantanea Cache di Rete**: introdotta `invalidate_network_cache()` che azzera immediatamente la cache di 15s al cambio rete o rimozione, permettendo all'interfaccia web di riflettere subito il nuovo IP e SSID.
  - **Miglioramenti UI Modal Wi-Fi (`templates/wifi.html`)**:
    - Aggiunto toggle interattivo ("👁" e checkbox "Mostra password in chiaro") per verificare visivamente i caratteri digitati prima di confermare.
    - Supporto per invio diretto tramite tasto `Invio`.
    - Autofocus automatico sul campo password all'apertura del modale.

## [0.2.10] - 2026-10-17

### Risolto e Migliorato
- **Risoluzione Mancata Visualizzazione Splash Screen al Boot**:
  - **Avvio UI Iper-Veloce (13.8s)**: spostata la dipendenza di `thinclient.service` da `network.target` a `basic.target`. In precedenza `network.target` attendeva 31 secondi di negoziazione Wi-Fi di NetworkManager prima di avviare il backend e X11, lasciando lo schermo nero per quasi un minuto. Con `basic.target`, `thinclient-ui.service` e Chromium partono a soli **13.8 secondi** dall'accensione!
  - **Tracciamento `boot_id` Kernel su `/api/boot/status`**: integrata lettura del `boot_id` univoco generato dal kernel Linux ad ogni riavvio (`/proc/sys/kernel/random/boot_id`). Questo garantisce che la sequenza splash venga riprodotta infallibilmente ad ogni accensione o riavvio del dispositivo, evitando che la persistenza della sessione di Chromium la inibisse.
  - **Modalità Chromium Kiosk Incognito**: aggiunto flag `--incognito` e `--lang=it` in `scripts/xinitrc` per impedire il ripristino di sessioni precedenti o cache obsolete.
  - **Visibilità Immediata Splash Screen**: rimosso `display: none` iniziale dal markup HTML; l'overlay Cyberpunk è ora visibile fin dal primo frame di rendering della pagina senza alcuno sfarfallio.
  - **Sequenza di Bootstrap Garantita (3.5 - 4.0 secondi)**: implementata progressione fluida con tempo minimo garantito per consentire all'utente di vedere tutti e 4 gli stadi di inizializzazione (UI, Rete, Tailscale, Host RDP) con le relative spunte verdi prima della dissolvenza nella dashboard.

## [0.2.9] - 2026-10-16

### Aggiunto
- **Overlay Hot-Corner OSD Nativo (In alto a sinistra durante sessione RDP)**:
  - **Micro-servizio Tkinter OSD (`app/overlay.py`)**:
    - Finestra borderless per il server X11 (`DISPLAY=:0`) con flag `overrideredirect(True)` e `attributes('-topmost', True)`, per rimanere sempre in primo piano rispetto a FreeRDP 3 a tutto schermo (`/f`).
    - Bassissimo impatto di risorse (~15-20 MB RAM, 0% CPU in idle).
    - **Trigger Hot Corner (1.0 secondo)**: zona di ascolto minima (16x16 px) nell'angolo in alto a sinistra (`0, 0`). L'overlay si espande solo se il cursore staziona per almeno 1 secondo continuo nell'angolo, evitando aperture involontarie durante l'utilizzo di Windows.
    - **Riquadro informativo**: mostra l'IP locale (Wi-Fi con SSID o Ethernet), l'IP VPN Tailscale WireGuard e il computer host remoto collegato.
    - **Pulsante "Disconnetti Sessione"**: consente di terminare la sessione RDP con un solo click invocando `/api/rdp/disconnect`, risvegliando istantaneamente Chromium Kiosk e chiudendo l'overlay.
    - **Timer di chiusura a scomparsa (2.0 secondi)**: quando il cursore esce dal perimetro del riquadro, si avvia un conto alla rovescia di 2 secondi; se il cursore rientra il timer si azzera, altrimenti il riquadro scompare tornando alla modalità trigger nascosta.
  - **Integrazione nel Ciclo di Vita FreeRDP (`app/rdp.py`)**:
    - Avvio automatico dell'overlay alla connessione FreeRDP e arresto pulito alla disconnessione o chiusura del processo.
  - **Diagnostica & Test (`app/main.py`, `templates/diagnostics.html`)**:
    - Aggiunto endpoint di test `/api/overlay/test` e pulsante interattivo "Testa Overlay OSD" nel pannello Diagnostica.

## [0.2.8] - 2026-10-16

### Aggiunto
- **Supervisione & Assistenza Remota VNC (Desktop Shadowing su DISPLAY :0)**:
  - **Servizio Systemd Dedicato (`systemd/thinclient-vnc.service`)**:
    - Agganciato a `DISPLAY=:0` per visualizzare in tempo reale esattamente ciò che vede l'operatore (sia la Kiosk UI sia la sessione FreeRDP 3 attiva).
    - Avvio non bloccante in parallelo (`After=thinclient-ui.service tailscaled.service`, `PartOf=thinclient-ui.service`).
  - **Script di Avvio Ottimizzato per RPi 3 (`scripts/x11vnc-start.sh`)**:
    - Controllo e attesa disponibilità display X11 (`/tmp/.X11-unix/X0` e `xset -q`).
    - Parametri di abbattimento carico CPU (`-wait 50 -defer 40 -noxdamage -repeat`) per mantenere l'uso CPU sotto al 5-10% e prevenire conflitti con l'accelerazione Glamor/VC4.
    - Modalità ascolto intelligente: bind esclusivo all'IP IPv4 di Tailscale WireGuard (`-listen $TS_IP` o `-interface tailscale0`) per impedire accessi non autorizzati dalla LAN locale.
    - Gestione automatica password crittografata con permessi `0600` (`config/x11vnc.pass`), con creazione automatica password iniziale (`thinclient`).
  - **Backend Python & REST API (`app/vnc.py`, `app/main.py`)**:
    - Monitoraggio stato del demone e rilevamento client connessi in tempo reale tramite socket analysis (`ss`/`netstat`).
    - API RESTful `/api/vnc/status`, `/api/vnc/save`, `/api/vnc/restart`.
    - Gestione cambio password crittografata al volo con `x11vnc -storepasswd`.
  - **Integrazione Web UI & Kiosk**:
    - **Pannello Impostazioni (`/settings`)**: sezione dedicata "Supervisione e Assistenza Remota (VNC)" con switch abilitazione/disabilitazione, limitazione accesso Tailscale, modifica password e box con endpoint MagicDNS/IP Tailscale per il tecnico.
    - **Pannello Diagnostica (`/diagnostics`)**: card con stato servizio, porta 5900, client attivi e pulsante di riavvio al volo.
    - **Indicatore Live in Header (`base.html`, `app.js`)**: visualizzazione dinamica del badge *"Assistenza Remota Attiva"* quando un supervisore si connette alla porta 5900.

## [0.2.7] - 2026-10-16

### Aggiunto e Ottimizzato
- **Snellimento Critico del Boot (Riduzione tempo di avvio da 71s a ~16s)**:
  - **Disaccoppiamento Avvio Kiosk UI**: rimossa la dipendenza bloccante di rete (`After=network-online.target tailscaled.service`) da `thinclient.service`. Il server Flask locale e Chromium Kiosk si avviano immediatamente senza attendere la rete esterna o Tailscale.
  - **Rimozione Colli di Bottiglia Systemd**: disabilitati e mascherati tutti i servizi residui di `cloud-init` (`cloud-init-main`, `cloud-init-local`, `cloud-init-network`, `cloud-config`, `cloud-final`) risparmiando oltre 10 secondi di ritardo su `sysinit.target`.
  - **Eliminazione Attesa Rete**: disabilitato e mascherato `NetworkManager-wait-online.service`, consentendo a NetworkManager e Tailscale di connettersi in parallelo in background mentre la grafica è già operativa.
  - **Disattivazione Servizi Superflui**: disabilitati `rpi-eeprom-update.service` (inutile su Pi 3), `keyboard-setup.service` e `console-setup.service`.
  - **Ottimizzazioni Firmware & Silent Boot (`config.txt` / `cmdline.txt`)**:
    - Abilitati `boot_delay=0`, `disable_splash=1`, `initial_turbo=30` (frequenza CPU al massimo nei primi 30 secondi di avvio).
    - Disabilitati `camera_auto_detect=0` e `display_auto_detect=0` per eliminare i cicli di probe I2C a vuoto.
    - Configurato **Silent Boot** in `cmdline.txt` (`quiet loglevel=3 logo.nologo vt.global_cursor_default=0 consoleblank=0`) rimuovendo il parametro `ds=nocloud;...`, eliminando il testo scorrevole del kernel su schermo.
    - Impostato sfondo root X11 scuro immediato in `scripts/xinitrc` (`xsetroot -solid "#0f172a"`).
- **Nuovo Tema Cyberpunk e Rebranding "HiDaThin"**:
  - Introdotto branding ufficiale **HiDaThin** (Remote Thin Client OS via Tailscale) nell'interfaccia e nello splash screen.
  - Generata e integrata grafica artwork in stile **Cyberpunk** ad alta definizione (`cyberpunk_splash.jpg`), con mainframe console dark carbon, circuiti neon ciano ed effetti HUD.
  - Scheda splash ridisegnata con stile HUD Cyberpunk, bordi al neon (`#00f0ff`), scanlines retrò-futuristiche, barra di avanzamento elettrica ciano/magenta e checklist ad alto contrasto.
  - Risolto refuso di sintassi JavaScript che inibiva l'esecuzione dei pulsanti e del controller di bootstrap, garantendo ora reattività immediata a tutti i tasti dell'interfaccia.
  - Aggiunto blocco automatico dei popup di traduzione di Chromium (`translate="no"`, `meta notranslate`).

## [0.2.6] - 2026-10-16

### Ottimizzato
- **Accelerazione Grafica FreeRDP su GPU (Glamor / X11)**:
  - Abilitato flag `/gdi:hw` in FreeRDP 3: il rendering e il blitting 2D vengono ora delegati direttamente al server Xorg con driver `vc4-kms-v3d` e accelerazione Glamor sulla GPU VideoCore IV, eliminando il pesante rendering software su CPU.
  - Attivata pipeline grafica Microsoft EGFX specifica per thin client: `/gfx:progressive,thin-client:on,small-cache:on` per il profilo bilanciato e `/gfx:RFX,thin-client:on,small-cache:on` per il profilo performance.
  - Sostituito `/network:lan` con `/network:broadband` e disabilitati effetti Windows pesanti (`-wallpaper`, `-menu-anims`, `-window-drag`), riducendo drasticamente il flusso di pixel non necessari. Corretto refuso nel parametro animazioni (`-menu-anims`) che generava l'errore di sintassi con codice 23. Mappato il codice 23 nella diagnostica utente.
- **Sospensione Automatica Chromium Kiosk**:
  - All'avvio della sessione RDP a tutto schermo, il backend Flask invia automaticamente `SIGSTOP` a Chromium Kiosk, congelando i suoi processi (0% CPU, stop swap su MicroSD).
  - Alla chiusura della sessione RDP, Chromium viene ripreso istantaneamente con `SIGCONT`, restituendo il controllo all'interfaccia utente.
- **Diagnosi Hardware Critica**:
  - Rilevata sottotensione attiva sull'alimentatore (`throttled=0x50005`), che causava il dimezzamento del clock CPU da 1.2 GHz a 600 MHz via firmware hardware.

## [0.2.5] - 2026-10-16

### Risolto e Migliorato
- **Gestione Autenticazione NLA e Diagnostica FreeRDP**:
  - **Mappatura codici di errore FreeRDP**: tradotti i codici di uscita numerici (es. codice 145 per mancata autenticazione NLA, 134 per credenziali errate, 141 per host non raggiungibile) in messaggi utente chiari e guidati invece del generico `codice: 145`.
  - **Gestione annullamento utente**: azzerato l'errore fittizio mostrato alla pressione del tasto "Annulla" (`SIGTERM`).
  - **Supporto Utente Predefinito per Host**: aggiunto il campo facoltativo `username` in `config/hosts.yaml` e nel pannello di gestione host (`/hosts`), con precompilazione automatica del nome utente all'avvio o alla selezione del PC.
  - **UX Credenziali Intelligente**: espansione e focus automatico del campo password nel caso in cui il PC richieda Autenticazione a livello di rete (NLA), con supporto per la connessione diretta premendo Invio.

## [0.2.4] - 2026-10-16

### Ottimizzato
- **Prestazioni CPU e Riduzione Latenza Input**:
  - **Caching chiamate di sistema**: introdotta cache TTL di 15 secondi per `get_network_status()` (`nmcli`, `ip`) e `get_tailscale_status()` (`tailscale status`), azzerando il carico parassita su `NetworkManager` e `dbus-daemon`.
  - **Lettura segnale Wi-Fi zero-overhead**: lettura diretta da `/proc/net/wireless` evitando scansioni Wi-Fi periodiche invasive con `nmcli dev wifi`.
  - **Polling interfaccia Web**: allungato l'intervallo di polling da 4 a 15 secondi in `static/js/app.js`.
  - **Ottimizzazione Chromium Kiosk**: disabilitato il processo GPU ANGLE (`--no-gl-override`, `--disable-gpu`, `--disable-gpu-rasterization`, `--disable-software-rasterizer`), risparmiando oltre 120 MB di RAM e il 20% di CPU fissa sul Raspberry Pi 3.

## [0.2.3] - 2026-10-16

### Risolto
- **Riconoscimento Tastiera e Mouse in Xorg**:
  - Installati i pacchetti driver di input X11 mancanti: `xserver-xorg-input-all`, `xserver-xorg-input-libinput`, `libinput10` e utility `xinput`. In precedenza Xorg rilevava le periferiche USB tramite udev ma le ignorava per mancanza del driver (`No input driver specified, ignoring this device`).
  - Rimosso il flag `-nocursor` dal comando di avvio del server X in `systemd/thinclient-ui.service`. Il puntatore del mouse è ora visibile durante il movimento ed è gestito in idle dal demone `unclutter`.

## [0.2.2] - 2026-10-07

### Aggiunto
- **Tailscale & MagicDNS**:
  - Installazione del pacchetto ufficiale Tailscale (v1.102.5).
  - Autenticazione nodo `thin01` (IP `100.68.91.18`).
  - Abilitazione e avvio automatico di `tailscaled.service`.
  - Verifica della risoluzione MagicDNS (`taild1b0f0.ts.net`) e connettività ping (latenza 7-11ms verso `pc-mimmo`, `pc-officina`, `pc-studio`).
  - Verifica raggiungibilità porta TCP 3389 (RDP) su tutti i PC remoti.
- **Client FreeRDP 3**:
  - Installazione `freerdp3-x11` (v3.15.0) con symlink `/usr/bin/xfreerdp`.
  - Ottimizzazione parametri di avvio per Raspberry Pi 3: `/cache:bitmap:on,offscreen:on`, `+clipboard`, `/network:lan`, `/compression`, `/cert:ignore`.
  - Supporto per tre profili prestazionali: Prestazioni Elevate (16-bit, compressione), Bilanciato (predefinito, 24-bit, font nitidi), Qualità (32-bit, GFX AVC420).
  - Gestione sicura credenziali via stdin in memoria RAM (`/from-stdin:force`), senza memorizzazione in chiaro su file o log.
- **Ottimizzazioni Sistema Raspberry Pi 3**:
  - Disabilitazione servizi non necessari (`bluetooth.service`, `avahi-daemon.service`, `avahi-daemon.socket`).
  - Configurazione CPU scaling governor a `performance` permanente via `cpu-governor.service` per azzerare la latenza di clock.
  - Impostazione `vm.swappiness=10` in `/etc/sysctl.d/99-thinclient.conf` per ridurre la scrittura su scheda MicroSD.
  - Allocazione `gpu_mem=128` in `/boot/firmware/config.txt`.
- **Applicazione Thin Client (`/opt/thinclient`)**:
  - Backend leggero in Python + Flask con API RESTful su porta 8080.
  - Interfaccia web fullscreen dark-mode responsive ottimizzata per mouse e tastiera con pulsanti grandi:
    - Schermata principale: stato Wi-Fi, stato Tailscale, selettore PC a discesa (`pc-mimmo` predefinito), pulsante grande "CONNETTI", menu rapido.
    - Gestione Wi-Fi: scansione reti tramite `nmcli`, visualizzazione segnale e tipo di cifratura, connessione e memorizzazione automatica.
    - Gestione PC RDP: elenco persistente (`config/hosts.yaml`), aggiunta/modifica/eliminazione host, cambio host predefinito, test ping.
    - Diagnostica: riepilogo in tempo reale di IP LAN, SSID, potenza segnale, gateway, DNS, stato Tailscale, RAM, CPU, temperatura, throttling e test porta 3389.
    - Impostazioni: configurazione profili prestazionali, risoluzione display e profondità colore (`config/settings.yaml`).
- **Autostart e Kiosk Mode**:
  - Servizio systemd `thinclient.service` con riavvio automatico in caso di crash (`Restart=always`).
  - Servizio grafico `thinclient-ui.service` basato su Xorg, Openbox e Chromium in kiosk mode (`--kiosk --app=http://127.0.0.1:8080`) con watchdog.
  - Configurazione logrotate per la rotazione automatica dei log in `/etc/logrotate.d/thinclient`.

## [0.2.1] - 2026-10-07

### Aggiunto
- Analisi hardware e software preliminare del Raspberry Pi 3 Model B (Rev 1.2, Debian 13 trixie aarch64).
- Backup di sicurezza delle configurazioni di sistema originali in `/root/backup_original_config/`.
- Configurazione autenticazione SSH con chiave ed25519 per automazione e gestione remota sicura.
- Verifica disponibilità pacchetti `freerdp3-x11`, `xserver-xorg`, `openbox`, `NetworkManager`.
