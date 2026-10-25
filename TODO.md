# TODO — Roadmap & Idee di Ottimizzazione HidaThin

Questo documento raccoglie le attività pianificate e le ottimizzazioni architetturali ispirate dall'analisi di soluzioni thin client ad altissime prestazioni come **WTware** (boot time < 5s, approccio appliance stateless, footprint minimale).

---

## ⚡ 1. Ottimizzazione Boot Speed (Ispirate da WTware)

- [ ] **Modalità "Direct-to-RDP" / Auto-Connect (Bypass Browser)**
  - *Obiettivo*: Se è impostato un host predefinito (`auto_connect: true` in `hosts.yaml`), avviare `xfreerdp3` direttamente al boot senza attendere né aprire Chromium Kiosk.
  - *Comportamento di fallback*: Se la sessione RDP termina o fallisce, aprire il Kiosk/Dashboard o un menu di riconnessione rapido.
  - *Guadagno stimato*: **-5 / 7 secondi** al boot per postazioni fisse.

- [ ] **Sostituzione o Alleggerimento di Chromium Kiosk UI**
  - *Problema*: Chromium è il collo di bottiglia principale all'avvio (~250-400 MB RAM e 5-7s di caricamento su ARM Cortex-A53).
  - *Opzioni*:
    - Creare un launcher grafico nativo leggero (es. **Tkinter** / **Pygame** / **Dear ImGui**), simile all'attuale `overlay.py` che parte in < 200 ms.
    - Oppure utilizzare una WebView ultra-leggera (es. WebKitGTK minimale / `pywebview`) mantenendo il frontend Flask solo se necessario.
    - Mantenere la Web UI per la gestione remota da browser esterno su LAN/Tailscale, senza caricarla localmente su schermo.
  - *Guadagno stimato*: **-4 / 6 secondi**, ~250 MB di RAM liberata per la sessione RDP.

- [x] **Pruning Aggressivo dei Servizi Systemd**
  - *Completato*: Creato script [`scripts/optimize-boot.sh`](file:///y:/Progetti/thinclient/scripts/optimize-boot.sh) con supporto `--undo`.
  - *Servizi mascherati*: `apt-daily` & `apt-daily-upgrade` (timers/services), `man-db` (timer/service), `cups` & `cups-browsed`, `avahi-daemon`, `ModemManager`, `triggerhappy`, `plymouth`, `bluetooth` & `hciuart`, `systemd-udev-settle`, `systemd-time-wait-sync`, `e2scrub`.
  - *Guadagno*: **-2 / 3 secondi** e azzeramento del blocco I/O su MicroSD al boot.

- [ ] **Ottimizzazione Kernel & Storage I/O**
  - *Task*:
    - Aggiungere parametri di boot veloci in `/boot/firmware/cmdline.txt`: `quiet loglevel=0 fastboot noswap fsck.mode=skip`.
    - Testare l'overclock del bus MicroSD in `/boot/firmware/config.txt`: `dtparam=sd_overclock=100` (per schede SD A1/A2).
    - Valutare opzioni di mount `noatime,nodiratime,commit=60` per la partizione root.

---

## 🛡️ 2. Resilienza & Appliance Mode (Stateless)

- [ ] **Filesystem Read-Only con OverlayFS (RAM Disk Mode)**
  - *Obiettivo*: Rendere il thin client completamente immune alla corruzione della scheda SD in caso di spegnimento improvviso da interruttore, come fa WTware eseguendo l'immagine in RAM.
  - *Task*:
    - Abilitare OverlayFS nativo di Raspberry Pi OS (`raspi-config nonint enable_overlayfs`).
    - Configurare cartelle persistenti solo per chiavi Tailscale e configurazioni (`/var/lib/tailscale`, `/opt/thinclient/config`).

- [ ] **Watchdog Hardware del Raspberry Pi**
  - *Task*: Abilitare il chip watchdog hardware (`bcm2835_wdt`) con `systemd` per riavviare automaticamente il thin client in caso di freeze del sistema.

---

## 🌐 3. Gestione Centralizzata & Provisioning Remoto

- [ ] **Configurazione Centralizzata Remota**
  - *Obiettivo*: Gestire flotte di thin client da un server centrale senza dover configurare ogni singolo dispositivo.
  - *Task*:
    - Implementare nel backend il recupero opzionale di `hosts.yaml` da un endpoint HTTP remoto o repository git (via Tailscale) basato su MAC address o hostname.
    - Se l'endpoint remoto non risponde, utilizzare la configurazione locale di cache.

---

## 🖥️ 4. Stack Grafico Moderno (Transizione a Wayland/Cage)

- [ ] **Valutare Wayland + Cage (Kiosk Compositor)**
  - *Obiettivo*: Eliminare l'overhead di Xorg + Openbox adottando **Cage**, un micro-compositor Wayland orientato ai kiosk che parla direttamente con KMS/DRM.
  - *Task*:
    - Testare `wlfreerdp` o `xfreerdp` tramite Xwayland / Cage.
    - Verificare la compatibilità dell'overlay OSD e dello shadowing VNC (o migrazione a Wayvnc).
