# TODO — Roadmap & Idee di Ottimizzazione HidaThin

Questo documento raccoglie le attività pianificate e le ottimizzazioni architetturali ispirate dall'analisi di soluzioni thin client ad altissime prestazioni come **WTware** (boot time < 5s, approccio appliance stateless, footprint minimale).

---

## ⚡ 1. Ottimizzazione Boot Speed (Ispirate da WTware)

- [x] **Modalità "Direct-to-RDP" / Auto-Connect (Bypass Browser)**
  - *Implementato*: Introdotta modalità configurabile `startup.mode: direct_rdp` in `settings.yaml` gestita dal coordinatore dedicato [`scripts/direct_rdp_coordinator.py`](file:///y:/Progetti/thinclient/scripts/direct_rdp_coordinator.py) e [`scripts/xinitrc`](file:///y:/Progetti/thinclient/scripts/xinitrc). All'avvio il coordinatore attende la disponibilità di rete e Tailscale ed effettua la connessione FreeRDP verso l'host predefinito lasciando inizialmente spento Chromium. In caso di errore, timeout o disconnessione, effettua un fallback pulito alla Dashboard Kiosk senza loop infiniti.
  - *Test*: Coperto da suite automatizzata (T24). Misurazione cronometrica specifica su dispositivo hardware fisico programmata con i comandi di benchmark.

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

- [x] **Ottimizzazione Kernel & Storage I/O (Silent Boot & Fast Boot)**
  - *Implementato*: Aggiunti parametri di silent boot in /boot/firmware/cmdline.txt (quiet loglevel=3 logo.nologo consoleblank=0 vt.global_cursor_default=0) e disable_splash=1 in config.txt per eliminare del tutto le scritte console, warning e cursore lampeggiante all'avvio prima di X11. Reindirizzati stdout/stderr di 	hinclient-ui.service su journal systemd per sopprimere warning e cursore di Xorg.
  - *Attività residue*:
    - Aggiungere parametri di boot veloci in `/boot/firmware/cmdline.txt`: `quiet loglevel=0 fastboot noswap fsck.mode=skip`.
    - Testare l'overclock del bus MicroSD in `/boot/firmware/config.txt`: `dtparam=sd_overclock=100` (per schede SD A1/A2).
    - Valutare opzioni di mount `noatime,nodiratime,commit=60` per la partizione root.

---

## 🛡️ 2. Resilienza & Appliance Mode (Stateless)

- [x] **Installer One-Liner Automatizzato (`install.sh` / `scripts/install.sh`)**
  - *Obiettivo*: Setup completo della macchina da zero su Raspberry Pi OS Lite con un singolo comando `curl -sSL ... | sudo bash`.
  - *Implementato*: Script unificato che gestisce dipendenze APT, browser Chromium Kiosk, FreeRDP 3, VNC, Tailscale Mesh VPN, ottimizzazioni kernel/hardware (polling mouse 500Hz, memoria GPU 128MB, accelerazione Xorg 1:1 flat, tuning swappiness a 10), script di fast-boot e registrazione/avvio dei servizi systemd. Regola di manutenzione registrata in `GEMINI.md`.

- [x] **Filesystem Read-Only con Partizione Persistente /data (Soluzione B)**
  - *Obiettivo*: Rendere il thin client completamente immune alla corruzione della scheda SD da spegnimento improvviso, garantendo la persistenza delle impostazioni utente, password Wi-Fi e stato Tailscale.
  - *Implementato*:
    - Script automatico [`scripts/setup-readonly-fs.sh`](file:///y:/Progetti/thinclient/scripts/setup-readonly-fs.sh) (supporto partizione `/data`, tmpfs in RAM per `/tmp`, `/var/tmp`, `/var/log`, journaling volatile, e `--undo`).
    - Bind-mount persistenti per `/opt/thinclient/config`, `/var/lib/tailscale` e `/etc/NetworkManager/system-connections`.
    - Fallback automatico in Python per salvataggio su filesystem protetto (`save_settings` e `save_hosts_data`).
    - Gestione aggiornamenti OS Debian: pulsante "⚡ Aggiorna Sistema Operativo (Debian)" nella pagina Impostazioni che rimonta automaticamente in RW, esegue `apt update` e `apt dist-upgrade` con streaming console in tempo reale, esegue il sync e ripristina garantito lo stato Read-Only (`ro`).
    - Monitoraggio stato del Filesystem (RO/RW) visibile anche in Diagnostica e Impostazioni.

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
