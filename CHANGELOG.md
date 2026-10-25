# Changelog

Tutte le modifiche rilevanti a questo progetto sono documentate in questo file.

Il formato è basato su [Keep a Changelog](https://keepachangelog.com/it/1.0.0/),
e questo progetto segue il versionamento `0.2.x`.

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
