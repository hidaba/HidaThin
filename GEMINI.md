# Regole del Progetto / Project Rules

## Convenzioni Git e Commit su GitHub
- Quando effettui un commit o pubblichi modifiche su GitHub, includi sempre nel messaggio/commento di commit una breve e chiara descrizione delle modifiche apportate (specificando in sintesi cosa è stato modificato nei singoli file o componenti toccati).

## Manutenzione dello Script di Installazione (`install.sh`)
- Lo script di installazione automatica (`install.sh` / `scripts/install.sh`) deve essere **SEMPRE** mantenuto aggiornato quando vengono introdotte modifiche al repository che riguardano file aggiunti, rimossi o rinominati.
- In particolare, se vengono aggiunti nuovi pacchetti apt, nuovi file di configurazione, nuovi script, nuovi template, nuovi asset o modificati i percorsi/servizi systemd, verificare e aggiornare contestualmente `install.sh` affinché l'installazione automatica (es. via `curl ... | sudo bash`) configuri sempre correttamente il sistema da zero.

