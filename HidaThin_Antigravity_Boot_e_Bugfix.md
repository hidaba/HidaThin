# HidaThin — Ottimizzazione boot e correzione bug

## Incarico per Antigravity

Implementa nel progetto **HidaThin** le correzioni e le ottimizzazioni descritte in questo documento. Porta il lavoro fino a codice modificato, test pertinenti, installer aggiornato e documentazione coerente. Non fermarti a una nuova analisi o a un elenco di suggerimenti.

- **Repository:** https://github.com/hidaba/HidaThin
- **Base dell'audit:** versione `0.2.16`, commit `3f08a273b4c2dda5d05821f8981dc7a31a6361ec`.
- **Data dell'audit:** 25 ottobre 2026.
- **Target principale:** Raspberry Pi 3, mantenendo compatibilità con i modelli e le versioni di Raspberry Pi OS effettivamente supportati dal progetto.
- **Stack attuale:** Python/Flask, Xorg, Openbox, Chromium kiosk, FreeRDP, NetworkManager, Tailscale, x11vnc, systemd.
- **Obiettivi:** dashboard disponibile rapidamente, avvio affidabile anche senza rete, sessioni RDP corrette, modalità read-only funzionante, installazione ripetibile e accessi amministrativi protetti.

Le osservazioni sono riferite al commit indicato. Prima di modificare il codice, verifica la revisione presente nel checkout: alcuni problemi potrebbero essere già stati risolti. Riporta le differenze ed evita di reintrodurre implementazioni superate.

Il documento è autosufficiente: non richiede i file temporanei o la conversazione dell'audit originale. Ricrea nel repository le prove di regressione necessarie.

## 1. Modalità di lavoro e ambito

1. Leggi `AGENTS.md`, se presente, `GEMINI.md`, `README.md`, `TODO.md` e `CHANGELOG.md` e rispetta le convenzioni effettive del progetto.
2. Controlla branch, commit e modifiche locali. Preserva il lavoro esistente; usa un branch dedicato o un checkout isolato quando serve. Evita reset o sovrascritture del lavoro dell'utente.
3. Implementa tutti gli interventi obbligatori di questo documento, compresa la modalità direct-to-RDP configurabile. Il riassetto completo dei privilegi e una migrazione a Wayland non fanno parte di questo incarico.
4. Mantieni Xorg/Openbox, l'interfaccia attuale, la gestione Wi-Fi, la lista PC, l'overlay OSD e l'assistenza VNC. Apporta modifiche mirate e coerenti con la struttura esistente.
5. Mantieni sincronizzati `install.sh`, `scripts/install.sh`, unità systemd, percorsi, dipendenze e configurazioni di esempio. Questa è anche una regola esplicita di `GEMINI.md`.
6. Le scelte tecniche ordinarie rientrano nel lavoro: prendile autonomamente e documentale. Segnala soltanto informazioni mancanti che impediscono una scelta corretta o azioni sul dispositivo che richiedono un accesso non disponibile.
7. Nel normale ambiente di sviluppo simula `reboot`, `poweroff`, mount, APT, NetworkManager, Tailscale, segnali ai processi e avvio FreeRDP. Non eseguire installer o script di partizionamento sul computer di sviluppo.
8. Se è disponibile un Raspberry di test nel contesto autorizzato, completa anche le prove reali. In caso contrario, completa comunque codice e test isolati e indica con precisione quali verifiche hardware restano da fare.
9. Prepara modifiche e commit locali secondo le convenzioni del repository. Push, merge, release e installazione su dispositivi devono seguire le autorizzazioni già presenti nell'ambiente; questo documento non è una richiesta autonoma di pubblicazione o di distribuzione in produzione.

### Ordine consigliato

| Fase | Interventi | Scopo |
| --- | --- | --- |
| 1 | SEC-01, SEC-02 | Proteggere password, API amministrative e VNC |
| 2 | FS-01, FS-02, INS-01 | Rendere affidabili read-only, persistenza e installazione |
| 3 | BOOT-01, BOOT-02 | Rimuovere attese artificiali e controlli sovrapposti |
| 4 | RDP-01, NET-01, WIFI-01, UPD-01 | Correggere sessioni, cache, Wi-Fi e aggiornamenti |
| 5 | BOOT-03 | Aggiungere l'avvio diretto RDP, disattivato per default |
| 6 | TEST-01, DOC-01 | Verifiche finali, misure e documentazione |

## 2. Evidenze iniziali e limiti delle misure

L'audit ha letto il codice ed eseguito prove isolate. Non ha cronometrato un avvio reale del Raspberry.

La simulazione del JavaScript originale dello splash, con prima risposta immediata e tutti i servizi pronti, ha rilevato:

| Scenario | Dashboard cliccabile dalla prima risposta | Splash completamente nascosto | Massimo richieste contemporanee |
| --- | ---: | ---: | ---: |
| Controlli successivi immediati | 4,3 s | 4,9 s | 1 |
| Controlli successivi con latenza simulata di 3 s | 7,3 s | 7,9 s | 4 |
| Controlli successivi con latenza simulata di 5 s | 9,3 s | 9,9 s | 7 |

Con rete assente e API immediata, i comandi di recupero compaiono dopo circa 11,3 secondi. Se la prima richiesta rimane pendente, non viene nemmeno avviato un timer indipendente per il recupero. Chiudere manualmente lo splash non cancella il polling: nella simulazione offline vengono effettuate 37 richieste in 29,7 secondi anche dopo la chiusura.

Sono stati inoltre riprodotti con dati fittizi e comandi simulati: password presenti nell'HTML senza autenticazione, chiamata amministrativa senza autenticazione, blocco RDP su errore EROFS del log, perdita del riferimento a una nuova sessione da parte del vecchio monitor, cache Tailscale obsoleta dopo riavvio, parsing errato degli SSID con due punti, doppio avvio dell'updater e stato `completed` nonostante ripristino RO fallito. Le prove dell'installer hanno confermato il clone in directory non vuota e l'`EOF` finale eseguito come comando. Il blocco di configurazione `/data` è stato verificato con mount fallito simulato.

Usa questi risultati come casi di regressione. Non trasformarli in promesse di boot complessivo o in benchmark hardware già eseguiti.

## 3. SEC-01 — API amministrative e credenziali RDP

### Problema

Nella revisione esaminata:

- `app/main.py` avvia Flask su `0.0.0.0:8080`.
- `systemd/thinclient.service` esegue il backend come root.
- Le operazioni amministrative non richiedono autenticazione.
- `templates/index.html` inserisce la password salvata in `data-password`.
- `templates/hosts.html` serializza l'intero oggetto host, password compresa.
- L'installer applica permessi ricorsivi che rendono leggibili anche i file di configurazione contenenti credenziali.

L'esposizione da rete dipende dalla raggiungibilità della porta; il bind e l'invio dei segreti al browser sono problemi del codice.

### Implementazione richiesta

1. Imposta il bind locale `127.0.0.1` come default. Allinea README, unità e configurazione alla realtà.
2. Se mantieni l'amministrazione web remota, rendila una modalità esplicita con autenticazione, controllo degli accessi e trasporto protetto adeguato alla configurazione scelta. La sola presenza di Tailscale non sostituisce l'autenticazione applicativa.
3. Non aggiungere credenziali amministrative fisse o token in URL, log o codice distribuito. Prevedi un bootstrap documentato per l'eventuale modalità remota.
4. Proteggi le operazioni mutanti da richieste cross-origin non autorizzate e DNS rebinding, con controlli di Host/Origin e protezione CSRF coerenti con il modello scelto. Mantieni funzionanti kiosk e overlay nativo senza eccezioni che riaprano l'accesso remoto indiscriminato.
5. Rimuovi completamente password e altri segreti dalle pagine HTML e dalle risposte JSON. Usa informazioni come `has_password` senza inviare il contenuto salvato.
6. Mantieni i segreti sul server con permessi restrittivi, ad esempio file `0600` e directory dedicate accessibili soltanto all'utente del servizio. Preserva tali permessi durante installazioni, aggiornamenti, migrazioni e scritture atomiche.
7. Continua a passare la password a FreeRDP attraverso stdin o un meccanismo supportato equivalente; non inserirla nella riga di comando o nei log.
8. Documenta la migrazione del bind per installazioni esistenti. Durante un deployment remoto preserva un accesso tecnico funzionante; non interrompere senza preparazione l'unico canale con cui si sta lavorando.

### Semantica obbligatoria delle password

Definisci esplicitamente il contratto frontend/backend, evitando di attribuire significati diversi alla stessa stringa vuota:

| Azione utente | Comportamento richiesto |
| --- | --- |
| Usare la password già salvata | Il backend la recupera senza restituirla al browser |
| Inserire una password per una sola sessione | La usa per quella connessione e non modifica la credenziale persistente |
| Sostituire la password salvata | Sostituzione esplicita con il nuovo valore e conferma dell'esito di salvataggio |
| Eliminare la password salvata | Azione esplicita di cancellazione |
| Modificare nome, porta o indirizzo del PC | La password esistente rimane invariata se non è stata richiesta una modifica |

Un campo password vuoto deve significare normalmente “nessuna sostituzione”. L'eliminazione richiede un'azione distinta. Aggiorna frontend e API insieme, gestendo in modo chiaro eventuali richieste nel vecchio formato. Il semplice uso di una password salvata non richiede una nuova verifica dell'utente; sono le modifiche persistenti a dover essere esplicite.

Gestisci coerentemente la coppia username/password: cambiare utente non deve usare inconsapevolmente una credenziale salvata per un account diverso. Se una persistenza richiesta fallisce, comunica l'errore e distingui l'eventuale avvio della sessione dal salvataggio non riuscito.

### Accettazione

- Una password fittizia salvata non compare nel sorgente di `/`, `/hosts`, in risposte API, attributi DOM, log o argomenti del processo.
- La modalità remota rifiuta operazioni amministrative non autenticate.
- Il kiosk locale e il pulsante Disconnetti dell'overlay continuano a funzionare.
- Sono testati uso, password transitoria, sostituzione ed eliminazione della credenziale.
- L'aggiornamento di un host senza campo password non cancella il segreto già salvato.

## 4. SEC-02 — VNC realmente limitato a Tailscale

### Problema

`scripts/x11vnc-start.sh` può avviare x11vnc su tutte le interfacce quando è richiesto `bind_tailscale_only: true` ma Tailscale non è disponibile. L'installer crea inoltre una password iniziale comune. Il launcher non applica direttamente tutte le preferenze VNC salvate.

### Implementazione richiesta

- Con vincolo Tailscale attivo e VPN indisponibile, mantieni VNC fermo o in attesa limitata e ritenta tramite systemd. Non usare un ripiego verso LAN o `0.0.0.0`.
- Usa un indirizzo valido della VPN e verifica i parametri realmente supportati dalla versione di x11vnc installata. Evita comandi Tailscale senza timeout.
- Applica realmente `vnc.enabled`, porta configurata e preferenza di bind. Installer e aggiornamenti devono preservare un VNC precedentemente disabilitato.
- Con password mancante o creazione della password fallita, non avviare un listener privo di autenticazione.
- Elimina il default comune dalle nuove installazioni: richiedi un'impostazione esplicita o predisponi un bootstrap sicuro senza segreti nei log. Conserva le credenziali già impostate dall'utente.
- Gestisci l'arrivo tardivo e la perdita della VPN senza creare un ciclo di riavvii aggressivo. Non bloccare dashboard o RDP per attendere VNC.

### Accettazione

Testa almeno: VPN pronta, nessun IP, interfaccia assente, comando Tailscale bloccato, VNC disabilitato, password mancante e riavvio con configurazione personalizzata. Quando è richiesta Tailscale, nessun caso deve produrre ascolto sulla LAN.

## 5. FS-01 — Log e dati temporanei compatibili con root read-only

### Problema

`app/rdp.py` apre `/opt/thinclient/logs/rdp.log` prima di avviare FreeRDP. Lo script read-only non rende scrivibile questa directory. Anche l'overlay usa un log sotto `/opt/thinclient/logs`.

### Implementazione richiesta

1. Sposta i log runtime in journald oppure in una directory volatile dedicata, per esempio `/run/thinclient`. Predisponila con systemd `RuntimeDirectory=` o con un meccanismo equivalente affidabile.
2. Se scegli `/var/log/thinclient`, garantisci la creazione della directory a ogni boot anche quando `/var/log` è tmpfs.
3. Aggiorna tutti i riferimenti: RDP, overlay, diagnostica, installer, logrotate e documentazione.
4. Elimina le scritture sotto `/opt/thinclient` durante il normale funzionamento, salvo i percorsi di configurazione resi intenzionalmente persistenti e scrivibili.
5. Gestisci errori del logging con un fallback controllato e visibile. Non impedire l'avvio RDP soltanto perché il log applicativo non si può aprire, e non rimontare la root RW per scrivere log ordinari.
6. Limita la crescita dei log su disco e in RAM. Lo script di ottimizzazione attuale maschera `logrotate.timer`: rendi coerenti questa scelta e la strategia di logging adottata.
7. Chiudi correttamente i file descriptor e mantieni disponibile la diagnostica degli errori di connessione.

### Accettazione

Con root RO e percorsi volatili vuoti al boot devono partire backend, UI, FreeRDP e overlay. Simulando EROFS o spazio esaurito sul log, la gestione dell'errore non deve lasciare sessioni o processi senza controllo.

## 6. FS-02 — Persistenza `/data`, migrazione e ripristino

### Problema

Lo script usa `LABEL=HidaData` anche quando il dispositivo passato è già ext4 e non ha quella label. Il fallimento di mount viene ignorato. Viene inoltre accettata una semplice cartella `/data` nella root come se fosse automaticamente uno spazio persistente indipendente.

### Implementazione richiesta

1. Rileva il filesystem e usa l'UUID effettivo del dispositivo. Non presumere che esista una label specifica.
2. Verifica che il dispositivo selezionato non corrisponda alla root o al boot e che il mount effettivo sia quello previsto.
3. Se manca un filesystem dati adatto, interrompi la procedura prima delle modifiche a root/fstab e descrivi il requisito mancante. Non considerare una semplice directory sotto la root sufficiente all'architettura root RO + dati RW.
4. Rimuovi la formattazione implicita dei dispositivi dal percorso standard. Un disco già contenente dati non deve essere formattato automaticamente.
5. Un mount fallito deve essere un errore bloccante. Verifica anche la possibilità di creare e rimuovere un file temporaneo nella destinazione prima di migrare dati o attivare RO.
6. Rendi le modifiche a `fstab` idempotenti e limitate alle voci gestite: niente duplicati, aggiunte ripetute di `ro` o cancellazione di mount estranei. Conserva un backup identificabile e verificabile.
7. Migra configurazione, credenziali, profili NetworkManager e stato Tailscale preservando permessi e proprietà. Coordina i servizi durante la copia finale per evitare dati incompleti o modifiche perse fra copia e primo riavvio.
8. Verifica le dipendenze systemd dei bind mount e della partizione dati prima dell'avvio dei servizi che ne hanno bisogno. Evita che una partizione assente venga sostituita silenziosamente dalla directory sottostante nella root.
9. Implementa un rollback coerente: deve preservare i dati più recenti modificati dopo la migrazione. Il semplice ripristino di un vecchio `fstab` non deve far riapparire configurazioni obsolete nascoste dai bind mount.
10. Lo stato mostrato dalla UI deve riflettere mount e scrivibilità reali. Non dichiarare protezione assoluta dai guasti: la partizione dati rimane scrivibile.

### Accettazione

Copri partizione ext4 senza label, UUID inesistente, mount fallito, destinazione non scrivibile, `/data` ordinaria sotto root, ripetizione della procedura e rollback dopo una modifica delle impostazioni. Le prove che richiedono mount reali vanno eseguite in un ambiente isolato o sul dispositivo di test autorizzato.

## 7. INS-01 — Installer pulito, aggiornamento e preservazione configurazioni

### Problemi verificati

- Il clone iniziale viene tentato dopo aver creato `logs/` e `config/` nella destinazione, che quindi non è vuota.
- L'ultima riga di `install.sh` contiene un `EOF` senza heredoc aperto.
- Il deployment da clone locale copia anche le configurazioni, con rischio di sostituire quelle dell'utente.
- Il fallback di installazione accetta `chromium-browser`, ma `scripts/xinitrc` invoca soltanto `chromium`.

### Implementazione richiesta

1. Clona in una destinazione vuota o usa una directory di staging e un deployment esplicito. Crea le directory runtime soltanto nel momento appropriato.
2. Rimuovi l'`EOF` orfano e verifica il codice di uscita effettivo oltre al testo stampato.
3. Separa codice/versione da configurazione/dati. Le configurazioni esistenti devono essere conservate; inizializza i default soltanto se mancanti. Prevedi migrazioni esplicite per i cambi di schema.
4. Preserva password, lista host, host predefinito, profili Wi-Fi, identità Tailscale e impostazioni VNC durante aggiornamenti e reinstallazioni.
5. Seleziona il binario Chromium disponibile e usa un unico criterio nel launcher e nella gestione dei processi. Fallisci con un messaggio chiaro se manca una dipendenza essenziale.
6. Verifica la compatibilità dei parametri con FreeRDP realmente installato. Non dichiarare riuscita un'installazione priva di client RDP e non promettere supporto FreeRDP 2 se gli argomenti usati richiedono FreeRDP 3.
7. Gestisci reinstallazione e root RO conservando lo stato iniziale dei mount e coordinandoti con la procedura di manutenzione. Nessun cambiamento implicito permanente del modo RO/RW.
8. Applica permessi specifici per codice e segreti; rimuovi il `chmod` ricorsivo pubblico sui dati sensibili.
9. Includi tutti i nuovi script, unità, file di configurazione e dipendenze aggiunti da questo intervento. Evita copie divergenti della logica tra i due installer.
10. Se un servizio essenziale non è stato abilitato o avviato, il riepilogo non deve dichiararlo operativo. Se il test UI non è possibile perché manca un display, distingui la configurazione riuscita dalla verifica grafica non eseguita.

### Accettazione

Testa installazione pulita, aggiornamento di installazione esistente, avvio da clone locale e modalità equivalente alla pipe documentata. Verifica la preservazione delle configurazioni personalizzate e il comportamento in caso di dipendenza mancante. `bash -n` è necessario ma non sufficiente.

## 8. BOOT-01 — Splash rapido, accessibile e annullabile

### Implementazione richiesta

- Utilizza subito il primo stato ricevuto: niente attese obbligatorie tra gli stadi se le condizioni sono già soddisfatte.
- Mostra immediatamente i comandi per dashboard e Wi-Fi, anche senza rete, VPN o host RDP.
- Se mantieni lo splash, rendilo un indicatore non bloccante oppure permettine l'uscita dal primo frame utile.
- Usa un timeout indipendente dalla richiesta iniziale, attivato prima della `fetch`. Gestisci errori HTTP, JSON non valido, backend non raggiungibile e risposte che non arrivano.
- Cancella timer, richieste e callback obsolete quando lo splash viene chiuso o la pagina cambia. La chiusura deve essere idempotente.
- Mantieni al massimo una richiesta di stato attiva per pagina. Pianifica la successiva soltanto dopo la conclusione della precedente, con timeout e backoff ragionevoli in caso di errore.
- Non usare una spunta verde per dichiarare raggiungibile un PC quando il controllo è fallito o non è stato eseguito. Distingui “configurato”, “in verifica”, “raggiungibile” e “non disponibile”.
- Lo stato dell'host remoto non deve impedire l'accesso alla configurazione locale.
- Se `sessionStorage` non è disponibile o genera un errore, la UI deve restare utilizzabile. La logica di boot ID non deve reintrodurre attese a ogni navigazione.
- Quando il backend non è pronto, il launcher X11 deve usare una verifica locale limitata e una politica di recupero comprensibile; evita un `curl` pendente indefinitamente. Il controllo di salute deve verificare anche l'esito HTTP, non soltanto l'apertura della connessione.

### Accettazione e obiettivi misurabili

- Nei test con clock simulato e stato già pronto, la UI è utilizzabile immediatamente; la transizione grafica finale, se presente, non supera 250 ms dalla risposta utile.
- I comandi locali sono accessibili anche se la prima richiesta non si risolve mai.
- Rete assente, Tailscale assente e host spento non producono un blocco dell'interfaccia.
- Con API lente non si accumulano richieste concorrenti.
- Dopo la chiusura non prosegue il polling specifico dello splash; può restare soltanto il normale aggiornamento leggero della dashboard.
- Una callback ritardata non riapre lo splash o sovrascrive uno stato più recente.

Questi sono criteri sulla logica applicativa. Il tempo totale dal power-on resta da misurare sul Raspberry.

## 9. BOOT-02 — Stato di sistema in background e separazione della disponibilità locale

### Implementazione richiesta

1. Introduci o riusa un endpoint di salute locale leggero, ad esempio `/healthz`, che non interroghi rete, DNS, Tailscale o host RDP. Non deve contenere informazioni sensibili.
2. Raccogli lo stato in background con una cache condivisa e frequenze limitate. Le richieste HTTP devono restituire uno snapshot senza avviare un gruppo di subprocess a ogni accesso.
3. Distingui stato sconosciuto, ultimo stato valido, dato non recente ed errore. Includi timestamp/età del campionamento quando utile alla UI.
4. Usa `time.monotonic()` per scadenze, intervalli e TTL. Non far dipendere i timeout da correzioni dell'orologio dovute a NTP.
5. Limita sia la durata delle operazioni esterne sia il numero di operazioni pendenti. Un worker bloccato non deve causare la creazione illimitata di altri thread o processi.
6. Se esiste un comando di aggiornamento forzato, deve accorpare le richieste simultanee; non deve scavalcare ogni limite facendo ripartire la stessa raccolta in parallelo.
7. Mantieni indipendenti l'avvio locale della UI e la disponibilità della rete. Non aggiungere dipendenze bloccanti da `network-online.target` al kiosk.
8. Il controllo di raggiungibilità RDP deve essere separato e limitato. Un timeout del socket non rappresenta automaticamente un limite complessivo per DNS e TCP: progetta una deadline che copra l'intera operazione.
9. Usa l'IP configurato come vero fallback se la risoluzione del nome fallisce, secondo una politica documentata. Rispetta la porta impostata per l'host e chiudi sempre i socket.
10. Rivaluta `optimize-boot.sh` sulla base delle dipendenze effettive. Non mascherare indiscriminatamente servizi di aggiornamento, verifica filesystem o gestione hardware per ottenere un numero migliore.

### Accettazione

Più richieste contemporanee allo stato devono condividere la stessa raccolta. Un blocco simulato di DNS, `nmcli` o Tailscale non deve bloccare `/healthz` né l'accesso alla dashboard. Il limite di concorrenza deve essere verificabile e il numero di worker deve rimanere limitato.

## 10. RDP-01 — Ciclo di vita delle sessioni e coordinamento con Chromium

### Problema

Monitor e timer leggono `self.process`, che può essere sostituito da una nuova sessione. La pulizia della vecchia sessione può azzerare il riferimento alla nuova, terminare l'overlay sbagliato o riprendere Chromium durante RDP.

### Implementazione richiesta

- Associa a ogni sessione un processo, un identificatore e le risorse correlate: overlay, log e stato del browser.
- Passa al monitor riferimenti stabili; esegui `wait()` sul processo che quel monitor deve sorvegliare.
- Prima di modificare lo stato condiviso verifica sotto lock l'identificatore della sessione corrente. Applica lo stesso controllo a timer, timeout e callback.
- Rendi connessione, cancellazione e pulizia idempotenti. La conclusione della sessione A non deve modificare B.
- Mantieni al massimo una sessione RDP attiva, comprese le richieste provenienti da auto-connect, dashboard e strumenti di assistenza.
- Definisci stati distinti per processo avviato, connessione in corso, sessione stabilita, errore e cancellazione. Un processo vivo da 1,5 secondi non prova che Windows sia utilizzabile.
- Se non è disponibile un segnale affidabile di sessione stabilita, non inventarlo: usa uno stato intermedio ed esponi il limite in diagnostica. Scegli un segnale compatibile con FreeRDP e testalo.
- Sospendi o riprendi soltanto il browser del kiosk associato all'applicazione, evitando segnali indiscriminati per nome a tutti i processi Chromium.
- `SIGSTOP` riduce l'esecuzione CPU, ma non libera automaticamente la RAM del browser. Non descrivere tale comportamento come recupero della memoria.
- Se per direct-to-RDP scegli di non avviare o di chiudere Chromium, coordina il supervisore del kiosk: l'attuale ciclo in `xinitrc` non deve riaprirlo subito.
- Sostituisci `preexec_fn=os.setsid` con `start_new_session=True`, ove appropriato. Gestisci gruppi di processi e cleanup senza colpire processi estranei.
- Raccogli correttamente gli exit code di `Popen`, distinguendo cancellazione volontaria, segnali ed errori applicativi. Usa timeout ed escalation terminate/kill limitati.

### Accettazione

Riproduci in modo deterministico: A termina, la sua pulizia viene ritardata, B parte, la pulizia di A riprende. B deve rimanere tracciata e disconnettibile, con overlay e stato corretti. Copri anche doppio clic su Connetti, Annulla durante la connessione, autenticazione fallita, processo che non termina e ripresa della dashboard.

## 11. NET-01 — Cache Tailscale e fallback dell'indirizzo

- Invalida lo stato memorizzato dopo un riavvio esplicito di Tailscale o un cambiamento di rete rilevante.
- Dopo il riavvio usa una lettura nuova e, se necessario, un'attesa limitata per lo stato pronto. Evita un ciclo di polling aggressivo.
- Non riavviare automaticamente `tailscaled` a ogni click quando sta già negoziando o manca temporaneamente la rete. Mantieni un comando amministrativo esplicito per il riavvio.
- Distingui installazione assente, daemon non disponibile, autenticazione necessaria, avvio in corso e stato operativo.
- Verifica che una cache negativa non impedisca una connessione già possibile e che una cache positiva non sia usata indefinitamente dopo una disconnessione.
- Il valore `hostname or ip` sceglie soltanto un campo: implementa un vero fallback se il nome non si risolve. Applica la stessa politica a connessione e diagnostica.

**Test richiesto:** prima lettura `Starting`, riavvio simulato riuscito, successiva lettura `Running`. Il codice deve effettuare la nuova interrogazione e aggiornare lo stato; non deve rifiutare RDP riusando la vecchia cache.

## 12. WIFI-01 — Parsing SSID e gestione non distruttiva dei profili

### Implementazione richiesta

1. Correggi tutti i parser dell'output terse di `nmcli`, non soltanto la scansione. Gestisci correttamente due punti e backslash escapati, connessioni attive, identificazione profili e rilevamento segnale.
2. Usa un parser centralizzato con test oppure dati strutturati tramite un'interfaccia appropriata. Non risolvere con sostituzioni parziali o regex incoerenti tra funzioni.
3. Costruisci i pulsanti Wi-Fi con API DOM e `addEventListener`; passa l'SSID come dato. Non inserirlo in attributi `onclick` contenenti stringhe JavaScript concatenate.
4. Preserva correttamente apostrofi, virgolette, backslash, Unicode e caratteri significativi per HTML. Non eseguire codice proveniente dal nome di una rete.
5. Evita di cancellare preventivamente tutti i profili funzionanti dell'SSID prima di verificare nuove credenziali. Mantieni un percorso di ripristino se la password inserita è errata o la connessione scade.
6. Distingui il nome del profilo NetworkManager dall'SSID reale e gestisci correttamente i casi in cui differiscono.
7. Mostra un risultato reale per Connetti e Dimentica: non dichiarare successo se i comandi necessari sono falliti.

### Accettazione

Testa almeno `Office:Guest`, `L'ufficio`, nomi con backslash, virgolette, Unicode e una stringa innocua che intercetti eventuale esecuzione JavaScript. Verifica che un tentativo di cambio password fallito non distrugga la configurazione precedentemente funzionante.

## 13. UPD-01 — Aggiornamento sistema e gestione coordinata dei mount

### Implementazione richiesta

- Imposta lo stato `running` sotto lock prima di creare il worker. Se il thread non può partire, ripristina uno stato coerente.
- Evita aggiornamenti simultanei, includendo i casi di più richieste e, se l'architettura lo consente, di più processi del backend. Usa un lock adatto al modello di esecuzione; non basarti soltanto sullo stato mostrato dalla UI.
- Registra lo stato iniziale di ciascun mount interessato. Ripristina quello stato, senza imporre RO a un sistema che era intenzionalmente RW.
- Verifica separatamente root e boot. Se lo sblocco necessario fallisce, interrompi in modo coerente invece di tentare comunque un aggiornamento non eseguibile.
- Coordina l'updater con salvataggi, installer e operazioni manuali di remount. Un'altra richiesta non deve rimontare RO mentre APT sta scrivendo.
- Preferisci salvataggi sulla partizione dati persistente scrivibile. Gestisci scritture di configurazione atomiche e concorrenti preservando permessi e contenuto; non usare remount automatici indiscriminati per nascondere una configurazione dei mount errata.
- Pubblica `completed` soltanto dopo sincronizzazione e ripristino previsto dei mount. Se APT riesce ma il ripristino fallisce, mostra un esito distinto e un messaggio chiaro, anche nell'API.
- Gestisci correttamente errori APT, lock occupato e assenza di rete. Non uccidere brutalmente `dpkg` nel mezzo di una transazione come normale gestione dei timeout.
- Valuta il riavvio del backend durante l'aggiornamento: il lavoro e il risultato non devono dipendere esclusivamente da un thread daemon destinato a sparire con Flask. Usa un worker supervisionato o documenta e verifica un meccanismo equivalente.
- I log dell'aggiornamento non devono includere segreti e devono rimanere consultabili secondo la strategia di logging scelta.

### Accettazione

Due richieste quasi simultanee devono avviare un solo lavoro. Testa: sistema inizialmente RO, sistema inizialmente RW, root sbloccata ma boot non scrivibile, APT fallito, ripristino RO fallito e tentativo concorrente di salvataggio/remount. La UI deve distinguere aggiornamento pacchetti riuscito da ripristino finale non riuscito.

## 14. BOOT-03 — Modalità direct-to-RDP configurabile

Implementa questa funzionalità dopo aver corretto ciclo di vita RDP e gestione della rete. È già un'idea del TODO; ora deve diventare una modalità utilizzabile e testata.

### Configurazione proposta

Mantieni il comportamento attuale come default. Una struttura possibile in `settings.yaml` è:

```yaml
startup:
  mode: dashboard             # dashboard | direct_rdp
  connect_timeout_seconds: 20
  max_initial_attempts: 1
  fallback_to_dashboard: true
```

Puoi adattare nomi e struttura allo schema del progetto, purché esista una sola fonte di verità e una migrazione documentata. Se introduci `auto_connect`, deve essere `false` per default. Non modificare l'host predefinito scelto dall'utente.

### Comportamento richiesto

1. In modalità `dashboard`, avvia normalmente il kiosk con le ottimizzazioni BOOT-01 e BOOT-02.
2. In modalità `direct_rdp`, avvia X11/Openbox e il coordinatore, lasciando inizialmente Chromium spento.
3. Un solo coordinatore attende i prerequisiti realmente necessari alla connessione e usa la stessa istanza del gestore RDP della dashboard. Non creare una seconda implementazione indipendente dei comandi FreeRDP o un processo che importi un altro manager autonomo. Verifica che X11 accetti effettivamente connessioni: la sola esistenza del file socket non è sufficiente.
4. Tutte le attese devono avere una scadenza complessiva. Il valore di 20 secondi sopra è un default configurabile di progetto, non una stima del tempo di boot.
5. Appena possibile, avvia la connessione usando host e credenziali conservati sul server.
6. Se mancano host valido o credenziali necessarie al flusso scelto, apri il menu senza un ciclo di fallimenti ripetuti. La necessità di credenziali dipende dalla configurazione RDP effettiva: non assumere che tutti i server abbiano lo stesso comportamento.
7. Se rete/VPN non arrivano, il PC è spento, l'autenticazione fallisce o il processo termina, apri una sola istanza del kiosk e mostra un messaggio comprensibile.
8. Prevedi un modo affidabile per aprire subito il menu locale, per esempio un tasto documentato durante l'avvio o un piccolo controllo nativo. Per annullare l'autoconnessione non deve essere necessario che Chromium sia già attivo.
9. Una richiesta di apertura del menu annulla anche un tentativo pendente. Una callback tardiva non deve avviare RDP sopra il menu dopo l'annullamento.
10. Dopo una disconnessione volontaria torna al menu senza riconnettere immediatamente lo stesso PC. Una nuova connessione deve essere una scelta esplicita o una policy separata chiaramente configurata.
11. Mantieni il funzionamento di overlay e assistenza VNC. La disponibilità di VNC non è un prerequisito per avviare RDP.
12. Se il browser viene aperto come fallback, la logica dello splash non deve aggiungere nuovamente le attese eliminate.

Una ricarica del browser non deve riavviare l'autoconnessione. Gestisci esplicitamente anche il riavvio del backend, evitando processi duplicati e tentativi automatici senza limite; descrivi se la sessione viene ripristinata, terminata o ricondotta al menu in base alla supervisione scelta.

### Accettazione

Testa host pronto, rete ritardata, VPN assente, host spento, autenticazione fallita, host rimosso dalla configurazione, apertura manuale del menu, disconnessione volontaria e conclusione tardiva di un tentativo annullato. Nessuno scenario deve creare sessioni multiple o un ciclo infinito tra browser e FreeRDP.

## 15. Configurazione e compatibilità trasversali

- Introduci uno schema esplicito con validazione di porte, tipi, enum, timeout e limiti; messaggi di errore comprensibili e codici HTTP coerenti.
- Quando la UI salva una sezione, non deve sovrascrivere impostazioni di altre sezioni come VNC, startup o accesso web. Effettua merge controllati e preserva le opzioni che il form non sta modificando.
- Se alcune impostazioni sensibili non sono modificabili dall'interfaccia, non renderle scrivibili indirettamente attraverso un generico endpoint di salvataggio.
- Aggiorna le configurazioni già esistenti senza perdere host, password o preferenze. Mantieni leggibili i file validi della versione dell'audit.
- In caso di YAML invalido, evita di sostituire silenziosamente la configurazione con valori di esempio potenzialmente sbagliati. Fornisci errore e percorso di recupero senza distruggere l'originale.
- Definisci dove risiedono codice, configurazione persistente, segreti, stato runtime e log. Mantieni questa separazione identica fra installer e applicazione.

## 16. TEST-01 — Verifiche richieste

Scegli test mirati ai difetti reali e alle nuove transizioni. Non costruire una suite enorme che replichi ogni dettaglio dell'implementazione. I test ordinari devono poter girare senza root, Raspberry, VPN, server Windows o riavvii reali.

| ID | Scenario minimo | Esito atteso |
| --- | --- | --- |
| T01 | Credenziale fittizia salvata, lettura pagine/API | Nessun segreto inviato al client |
| T02 | Chiamata amministrativa remota non autenticata | Rifiutata; nessun comando privilegiato eseguito |
| T03 | Uso, password transitoria, sostituzione, cancellazione | Semantica distinta, nessuna perdita involontaria |
| T04 | VNC limitato a Tailscale con VPN assente | Nessun listener LAN o senza password |
| T05 | VNC disabilitato e aggiornamento installer | Rimane disabilitato |
| T06 | Log RDP non scrivibile e root RO | Fallback controllato; sessione gestita correttamente |
| T07 | Installazione in destinazione vuota | Clone e deployment riusciti, exit code corretto |
| T08 | Aggiornamento con configurazioni personalizzate | Configurazioni e segreti preservati |
| T09 | Ext4 senza label, mount `/data` fallito | UUID corretto; nessuna attivazione RO dopo fallimento |
| T10 | Migrazione ripetuta e rollback con dati modificati | Nessun duplicato, nessuna configurazione recente persa |
| T11 | Splash con tutto pronto | Nessuna attesa artificiale; transizione breve |
| T12 | Prima fetch pendente e rete assente | Comandi di recupero sempre accessibili |
| T13 | Risposte lente e chiusura dello splash | Una richiesta attiva; polling specifico cancellato |
| T14 | Richieste concorrenti allo stato | Raccolta condivisa e worker limitati |
| T15 | DNS/Tailscale/nmcli bloccati simulati | Health locale e UI disponibili |
| T16 | Vecchia sessione A pulita dopo avvio di B | B resta tracciata, attiva e disconnettibile |
| T17 | Doppio Connetti e Annulla durante avvio | Una sessione; nessuna ripartenza tardiva |
| T18 | Cache Tailscale `Starting`, poi `Running` | Nuova lettura, niente rifiuto da cache obsoleta |
| T19 | SSID con `:`, apostrofi, backslash e Unicode | Parsing e pulsanti corretti, nessuna esecuzione JS |
| T20 | Cambio password Wi-Fi fallito | Profilo funzionante precedente preservato |
| T21 | Due richieste contemporanee di aggiornamento | Un solo lavoro avviato |
| T22 | APT riuscito ma ripristino mount fallito | Stato finale distinto da successo completo |
| T23 | Updater partendo da RO e da RW | Stato iniziale ripristinato correttamente |
| T24 | Direct-to-RDP, errore, annullamento e disconnessione | Un solo coordinatore, fallback unico, niente loop |
| T25 | Salvataggio di una singola sezione impostazioni | Altre sezioni conservate e validazione applicata |

Usa fixture e password fittizie. Per le gare fra thread usa sincronizzazione controllata anziché affidarti a sleep casuali. Per il frontend usa timer simulati e risposte differite. Per gli installer simula i comandi sensibili oppure usa un sistema disposable dedicato.

Aggiungi controlli sintattici Python, shell e JavaScript compatibili con il progetto. Ricorda che `bash -n` non identifica il caso dell'`EOF` eseguito come comando né il clone in una destinazione già popolata.

## 17. Misure sul Raspberry e obiettivi di prestazione

Se il dispositivo di test è disponibile, raccogli prima e dopo almeno:

```bash
systemd-analyze time
systemd-analyze critical-chain thinclient-ui.service
systemd-analyze blame | head -25
systemctl list-dependencies --reverse network-online.target

journalctl -b -o short-monotonic \
  -u thinclient.service \
  -u thinclient-ui.service \
  -u NetworkManager.service \
  -u tailscaled.service \
  --no-pager

vcgencmd get_throttled

findmnt -T /
findmnt -T /data
findmnt -T /opt/thinclient/config
findmnt -T /var/lib/tailscale
```

Adatta i nomi delle unità ai componenti eventualmente introdotti e ai percorsi reali. Esegui i comandi solo sul target corretto.

Misura separatamente:

1. Accensione → prima schermata visibile.
2. Avvio del backend → endpoint locale pronto.
3. Accensione → dashboard realmente utilizzabile.
4. Accensione → rete e Tailscale utilizzabili.
5. Accensione → sessione RDP effettivamente utilizzabile.

Le unità `Type=simple` vengono considerate avviate prima che l'applicazione sia necessariamente pronta: integra systemd con timestamp applicativi e, quando utile, una registrazione del boot. L'esistenza del processo FreeRDP non equivale a una sessione Windows utilizzabile.

Confronta più avvii a condizioni comparabili; cinque misure per configurazione sono un riferimento pratico. Riporta mediana e intervallo osservato, distinguendo Ethernet/Wi-Fi, host disponibile/non disponibile e stato RO/RW. Non sommare come indipendenti tempi di servizi che partono in parallelo.

Non impostare un obiettivo assoluto di boot inferiore a cinque secondi senza misure. Il primo risultato atteso è eliminare l'attesa artificiale della UI; il guadagno di direct-to-RDP si misura sul target.

Non introdurre come scorciatoie predefinite `fsck.mode=skip`, disabilitazione indiscriminata dello swap o overclock della MicroSD. Eventuali modifiche a memoria GPU, governor, cache Chromium e servizi devono essere motivate da compatibilità e misure. Conserva le verifiche necessarie all'affidabilità del dispositivo.

## 18. DOC-01 — Documentazione e consegna finale

Aggiorna il repository in modo che una nuova installazione riproduca il comportamento documentato.

### Documenti da allineare

- `README.md`: installazione, aggiornamento, prerequisiti, accesso web, VNC, startup, logging e modalità RO.
- `TODO.md`: marca come completate solo le attività implementate; distinguile da test hardware ancora da svolgere.
- `CHANGELOG.md`: cambiamenti, bug corretti e incompatibilità/migrazioni. Usa la versione appropriata allo stato reale del repository, senza forzare un numero ormai occupato.
- Configurazioni di esempio e istruzioni di rollback.
- Eventuale breve report tecnico nel repository, secondo le convenzioni esistenti.

### Contenuto obbligatorio del report di consegna

1. Commit di partenza e commit/branch risultante.
2. Tabella dei task SEC/FS/INS/BOOT/RDP/NET/WIFI/UPD con stato: implementato, già risolto, verificato solo con mock, verificato su dispositivo oppure bloccato con motivo concreto.
3. File modificati e ragione delle modifiche.
4. Comandi dei test, risultati effettivi e limiti delle verifiche.
5. Misure prima/dopo, se raccolte, chiaramente separate dalle simulazioni.
6. Procedura di aggiornamento di una macchina esistente, incluso il cambio di accesso web e la preservazione delle configurazioni.
7. Procedura di rollback che conservi i dati recenti.
8. Istruzioni per attivare direct-to-RDP e per tornare alla dashboard.
9. Eventuali problemi residui osservati; non presentare come verificati comportamenti che richiedono hardware non disponibile.

Il lavoro è concluso quando le modifiche sono implementate, i test pertinenti sono eseguiti, l'installer è coerente e i limiti rimasti sono espliciti. Se una prova hardware manca, consegna comunque tutto il lavoro completabile e la procedura precisa per eseguirla.

## 19. Riferimenti dell'audit

I collegamenti al codice sono fissati alla revisione esaminata; cerca le funzioni equivalenti nella revisione attuale.

| Area | Riferimento |
| --- | --- |
| Revisione analizzata | [Commit 3f08a27](https://github.com/hidaba/HidaThin/commit/3f08a273b4c2dda5d05821f8981dc7a31a6361ec) |
| API, credenziali, stato e bind HTTP | [app/main.py](https://github.com/hidaba/HidaThin/blob/3f08a273b4c2dda5d05821f8981dc7a31a6361ec/app/main.py) |
| Sessioni RDP, log e processi | [app/rdp.py](https://github.com/hidaba/HidaThin/blob/3f08a273b4c2dda5d05821f8981dc7a31a6361ec/app/rdp.py) |
| Updater e remount | [app/system.py](https://github.com/hidaba/HidaThin/blob/3f08a273b4c2dda5d05821f8981dc7a31a6361ec/app/system.py) |
| Cache VPN | [app/tailscale.py](https://github.com/hidaba/HidaThin/blob/3f08a273b4c2dda5d05821f8981dc7a31a6361ec/app/tailscale.py) |
| Parser e profili Wi-Fi | [app/wifi.py](https://github.com/hidaba/HidaThin/blob/3f08a273b4c2dda5d05821f8981dc7a31a6361ec/app/wifi.py) |
| Splash e dashboard | [templates/index.html](https://github.com/hidaba/HidaThin/blob/3f08a273b4c2dda5d05821f8981dc7a31a6361ec/templates/index.html) |
| Gestione PC e password | [templates/hosts.html](https://github.com/hidaba/HidaThin/blob/3f08a273b4c2dda5d05821f8981dc7a31a6361ec/templates/hosts.html) |
| Pulsanti Wi-Fi | [templates/wifi.html](https://github.com/hidaba/HidaThin/blob/3f08a273b4c2dda5d05821f8981dc7a31a6361ec/templates/wifi.html) |
| Installer | [install.sh](https://github.com/hidaba/HidaThin/blob/3f08a273b4c2dda5d05821f8981dc7a31a6361ec/install.sh) |
| Read-only e persistenza | [scripts/setup-readonly-fs.sh](https://github.com/hidaba/HidaThin/blob/3f08a273b4c2dda5d05821f8981dc7a31a6361ec/scripts/setup-readonly-fs.sh) |
| Launcher VNC | [scripts/x11vnc-start.sh](https://github.com/hidaba/HidaThin/blob/3f08a273b4c2dda5d05821f8981dc7a31a6361ec/scripts/x11vnc-start.sh) |
| Kiosk | [scripts/xinitrc](https://github.com/hidaba/HidaThin/blob/3f08a273b4c2dda5d05821f8981dc7a31a6361ec/scripts/xinitrc) |
| Servizi e ottimizzazioni | [systemd](https://github.com/hidaba/HidaThin/tree/3f08a273b4c2dda5d05821f8981dc7a31a6361ec/systemd), [optimize-boot.sh](https://github.com/hidaba/HidaThin/blob/3f08a273b4c2dda5d05821f8981dc7a31a6361ec/scripts/optimize-boot.sh) |
| Piano originale | [TODO.md](https://github.com/hidaba/HidaThin/blob/3f08a273b4c2dda5d05821f8981dc7a31a6361ec/TODO.md) |

Documentazione primaria utile, da verificare rispetto alle versioni realmente installate:

- [Python subprocess: thread, preexec_fn e start_new_session](https://docs.python.org/3.11/library/subprocess.html).
- [CPython socketmodule.c: risoluzione indirizzi e connessione](https://github.com/python/cpython/blob/3.13/Modules/socketmodule.c).
- [systemd-analyze: significato e limiti delle misure](https://www.freedesktop.org/software/systemd/man/252/systemd-analyze.html).
- [NetworkManager-wait-online: effetto delle dipendenze di rete](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/NetworkManager-wait-online.service.html).
- [Raspberry Pi: opzioni legacy e memoria GPU](https://www.raspberrypi.com/documentation/computers/legacy_config_txt.html). Non applicare automaticamente opzioni legacy a versioni o modelli sui quali non sono supportate.
