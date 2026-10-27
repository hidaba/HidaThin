# Regole del Progetto / Project Rules

## Convenzioni Git e Commit su GitHub
- Quando effettui un commit o pubblichi modifiche su GitHub, includi sempre nel messaggio/commento di commit una breve e chiara descrizione delle modifiche apportate (specificando in sintesi cosa è stato modificato nei singoli file o componenti toccati).

## Manutenzione dello Script di Installazione (`install.sh`)
- Lo script di installazione automatica (`install.sh` / `scripts/install.sh`) deve essere **SEMPRE** mantenuto aggiornato quando vengono introdotte modifiche al repository che riguardano file aggiunti, rimossi o rinominati.
- In particolare, se vengono aggiunti nuovi pacchetti apt, nuovi file di configurazione, nuovi script, nuovi template, nuovi asset o modificati i percorsi/servizi systemd, verificare e aggiornare contestualmente `install.sh` affinché l'installazione automatica (es. via `curl ... | sudo bash`) configuri sempre correttamente il sistema da zero.

## Aggiornamento e Riavvio Automatico del Thin Client Fisico
- Al termine di ogni lavoro di modifica o implementazione e relativi test positivi, **aggiornare sempre il dispositivo thin client fisico** e procedere al suo **riavvio** (`reboot`).
- La procedura standard per aggiornare e riavviare il thin client (host `thin01` / IP `100.68.91.18` o `192.168.1.131` via SSH con utente `root`) è:
  1. Connettersi via SSH e sbloccare temporaneamente il filesystem root in scrittura: `mount -o remount,rw /`
  2. Sincronizzare i file di progetto aggiornati in `/opt/thinclient/` (es. `app/`, `scripts/`, `static/`, `templates/`, `systemd/`, `tests/`), escludendo cache locali (`__pycache__`, `.pytest_cache`, `.git`) e preservando i file di configurazione attivi del dispositivo (`config/hosts.yaml`, `config/x11vnc.pass`).
  3. Verificare i permessi di esecuzione sugli script (`chmod +x /opt/thinclient/scripts/*`).
  4. Sincronizzare i buffer su disco fisico (`sync`).
  5. Riavviare il sistema (`reboot` o `systemctl reboot`) per ripristinare il funzionamento su filesystem protetto in Read-Only con i nuovi cambiamenti attivi.


