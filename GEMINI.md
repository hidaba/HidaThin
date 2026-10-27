# Regole del Progetto / Project Rules

## Convenzioni Git e Commit su GitHub
- Quando effettui un commit o pubblichi modifiche su GitHub, includi sempre nel messaggio/commento di commit una breve e chiara descrizione delle modifiche apportate (specificando in sintesi cosa è stato modificato nei singoli file o componenti toccati).

## Manutenzione dello Script di Installazione (`install.sh`)
- Lo script di installazione automatica (`install.sh` / `scripts/install.sh`) deve essere **SEMPRE** mantenuto aggiornato quando vengono introdotte modifiche al repository che riguardano file aggiunti, rimossi o rinominati.
- In particolare, se vengono aggiunti nuovi pacchetti apt, nuovi file di configurazione, nuovi script, nuovi template, nuovi asset o modificati i percorsi/servizi systemd, verificare e aggiornare contestualmente `install.sh` affinché l'installazione automatica (es. via `curl ... | sudo bash`) configuri sempre correttamente il sistema da zero.

## Aggiornamento e Riavvio Automatico del Thin Client Fisico
- Al termine di ogni lavoro di modifica o implementazione e relativi test positivi, **aggiornare sempre il dispositivo thin client fisico** e procedere al suo **riavvio** (`reboot`).
- È disponibile lo script automatico dedicato:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\deploy-thinclient.ps1
  ```
- Tale script esegue automaticamente:
  1. Archiviazione dei file di progetto aggiornati (`app/`, `scripts/`, `static/`, `templates/`, `systemd/`, `tests/`, `install.sh`, `CHANGELOG.md`), escludendo cache (`__pycache__`, `.pytest_cache`, `.git`) e preservando le configurazioni riservate del dispositivo (`hosts.yaml`, `x11vnc.pass`).
  2. Connessione SSH verso il thin client (`thin01` / `100.68.91.18`) e sblocco temporaneo del filesystem root in scrittura (`mount -o remount,rw /`).
  3. Estrazione dei file in `/opt/thinclient/`, normalizzazione dei caratteri di fine riga (LF) per gli script shell / xinitrc, impostazione dei permessi di esecuzione (`chmod +x`).
  4. Sincronizzazione dei buffer fisici su disco (`sync`).
  5. Invio del comando di riavvio (`reboot`) per far ripartire la macchina con filesystem protetto in sola lettura (`ro`) e i servizi aggiornati.



