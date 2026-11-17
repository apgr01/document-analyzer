# Roadmap

Stato del progetto, decisioni prese e prossimi passi. Va aggiornato a ogni step.

## Visione

Uno strumento generico per estrarre informazioni da documenti PDF, modulare e resiliente,
basato su un unico pilastro:

> **Vision-first** — ogni PDF viene sempre renderizzato in immagini ed elaborato da un
> modello multimodale (Gemini), guidato da testi scritti dall'utente in linguaggio naturale.

| Modalità | Descrizione | Stato |
|---|---|---|
| **Indicizzazione** | PDF → CSV secondo la Tabella dell'utente (righe, colonne, regole), con biblioteca e guida per catalogo | ✅ pipeline unica (`0.3.0`, 2026-11-15) |
| **RAG** | Descrizione delle pagine con la guida del catalogo, ricerca semantica, risposte con citazione delle fonti | ✅ funzionante (riga di comando), da migliorare |
| **Struttura** | Albero del documento (capitoli, sezioni) in JSON | 🔜 da progettare |

## Requisiti di progetto

Decisi insieme e da rispettare in tutti gli step:

- **Utente non esperto** — il programma guida: un percorso solo, con il prossimo passo sempre
  in vista; se manca qualcosa (tabella, guida, chiavi) lo dice e propone come procurarlo.
- **Generalità** — il contenuto del CSV dipende da ciò che l'utente chiede (la Tabella) e da
  com'è fatto il catalogo (la guida), non dal codice. Nessuna regola specifica di un catalogo
  nel programma.
- **Nessun limite preventivo** — si avvisa di quantità e tempi, non si impediscono invii; gli
  errori di Gemini si mostrano.
- **Interfaccia grafica** nel browser per l'uso quotidiano, CLI curata e leggibile su Windows.
- **Embedding locali** multilingue per il RAG (niente quota per l'indicizzazione vettoriale).
- **Modularità** — fasi separate e rilanciabili; ogni chiamata a Gemini si paga una volta.
- **Didattico** — codice commentato, documentazione aggiornata, un commit per argomento.

## Fase 0 — Consolidamento

- [x] **Step 1 — Fondamenta della repo**: `pyproject.toml`, `.gitignore`, README, roadmap,
  changelog.
- [x] **Step 2 — Ristrutturazione**: pacchetto `docanalyzer` con comando `docanalyzer`; workspace
  dati separato dall'applicazione; registro documenti (id leggibile + SHA-256); manifest e
  esecuzione parallela comuni; client Gemini con pool di chiavi, ritmo condiviso ed errori
  per codice HTTP; prompt in `configs/prompts/`; `upsert` nel RAG; configurazione ripulita.
- [x] **Modalità indicizzazione** (anticipata per un bisogno concreto): specifica YAML,
  estrazione strutturata pagina per pagina, contesto ereditato, controlli e report anomalie,
  export CSV e unione di più documenti.
- [x] **Bozze automatiche**: primer da PDF intero o da pagine scelte; specifica da descrizione a parole + CSV
  d'esempio + pagine campione.
- [x] **Esperienza d'uso**: CLI guidata (`doctor`, `add`, `list`, domande quando manca
  qualcosa, stima dei tempi, ripresa), guida passo passo.
- [x] **Configurazione guidata** (`docanalyzer setup`): l'utente sceglie le pagine significative,
  Gemini propone primer e specifica, anteprima con le stesse regole dell'indicizzazione,
  correzioni a parole in un ciclo con versioni, ripresa e salvataggio; partenza da file
  esistenti per cataloghi dello stesso tipo.
- [x] **Input per pagina configurabile** (`image+text` di default, `image`, `pdf`); testo
  nativo ripulito dal finto grassetto.
- [x] **Robustezza**: risposte troncate/bloccate riconosciute senza tentativi inutili; righe
  più corte (colonne di contesto non ripetute); riuso delle pagine dell'anteprima; specifica
  predefinita per documento.
- [x] **Interfaccia grafica** (`docanalyzer ui`): server locale + pagina web; configurazione con
  miniature cliccabili, prompt visibile prima dell'invio, conferme con il numero di richieste,
  bozze, versioni, indicizzazione con avanzamento e annullamento, risultati e download.
- [x] **Progetti** con più PDF della stessa struttura: primer e specifica comuni, note e
  pagine per singolo PDF (anche proposte da Gemini), configurazione con pagine da più PDF e
  prova su ognuno, indicizzazione unica, **CSV unico** e CSV per PDF.
- [x] **Pagina di ricerca** HTML autonoma sul CSV unico (ricerca tollerante, filtri, link ai
  PDF, download dei risultati).
- [x] **Gemini Snake**: mini gioco nella pagina di attesa, per divertimento.
- [x] **Quote**: classificazione dai dettagli dell'errore e ritmo complessivo adattivo
  (emerso dalla prima indicizzazione reale con 10 chiavi dello stesso progetto).
- [x] **Consumo e costi**: riepilogo di richieste e token; opzione `thinking_level`.
- [x] **Test**: test senza rete con Gemini simulato, più prove dell'interfaccia in Chromium
  (Playwright).

## Fase 1 — Biblioteca e collaudo sui cataloghi reali

- [x] **A · Biblioteca**: cartelle, tag, ricerca, scheda (descrizione, campi), collezioni di
  pagine con tag fissi, progetto dalla selezione con pagine e obiettivo precompilati.
- [x] **B · Analisi con Gemini** di un catalogo: prompt predefinito modificabile, pagine scelte
  dall'utente (estratto PDF) o PDF intero, gestione dei rifiuti per richieste troppo pesanti;
  proposta di descrizione, tag, campi e collezioni da accettare o correggere.
- [ ] ~~**B2 · Analisi in blocco**~~: per ora non serve, si resta sul singolo catalogo.
- [x] **Dati presenti e tag *dati***: i campi della scheda diventano un inventario senza ordine;
  il tag di pagina *da indicizzare* diventa *dati*.
- [x] **Impostazioni globali del progetto** (descrizione, riga, colonne vincolanti con
  copertura); PDF del progetto che rimandano alla scheda; configurazione guidata che usa
  impostazioni e schede.
- [x] **Pagine per PDF scelte dalle collezioni** e *Aggiorna dalla biblioteca* (regola: ciò che
  descrive si legge in diretta, ciò che comanda si copia).
- [x] **Progetto guidato** dalla scheda del PDF, al posto del raggruppamento in biblioteca.
- [x] **Ritorno nella scheda**: progetti in cui il PDF è usato e stato dell'indicizzazione.
- [x] **Progetto in 5 passi** con il prossimo passo sempre in vista.
- [x] **Pipeline unica**: biblioteca → analisi del catalogo (scheda e **guida
  all'indicizzazione** in due richieste) → progetto creato solo dalla scheda di un catalogo, con
  la **Tabella scritta dall'utente** e i cataloghi simili trovati da Gemini → ① Tabella ② PDF e
  pagine ③ **Prova** ④ Indicizzazione ⑤ Risultati. Regole composte dal programma (Tabella +
  guida + note); tolti configurazione guidata, primer e specifiche di progetto, CSV d'esempio,
  limiti preventivi; riga di comando ridotta. 132 test, percorso completo provato in Chromium.
- [x] **⑤ Verifiche ed elaborazione** (nuovo passo, Risultati diventa ⑥): copertura delle
  pagine, contenuto sulla pagina (valori cercati nel testo nativo, su tutte le righe), elenco di
  riferimento letto da Gemini e confrontato con il CSV (voci mancanti, solo nel CSV, scarto delle
  pagine), caratteri sospetti, valori vuoti, doppioni; *va bene così*, rifai singole pagine,
  **correzioni** reversibili (sostituisci tutte, celle, righe eliminate) applicate a ogni
  generazione del CSV; colonne **chiave** nella Tabella. Possibili sviluppi: valori fuori schema
  (la "forma" prevalente di una colonna), annotare nella guida ciò che le verifiche scoprono.
- [x] **Stile parametrizzato e temi**: scale e colori come variabili CSS a livelli, temi chiaro
  e scuro come file che ridefiniscono solo i colori, tema scelto in configurazione, pagina
  *Stile* con variabili e componenti; nessun colore o stile fisso nel JavaScript (controllato da
  un test). La pagina di ricerca esportata usa lo stesso tema.
- [x] **RAG con la guida del catalogo**: la descrizione delle pagine usa la stessa guida
  dell'indicizzatore (tolti i primer: un concetto solo); scelta delle pagine; test della
  pipeline e dell'indice vettoriale (ChromaDB con un embedding di prova, senza rete).
- [x] ~~**C · Raggruppamento**~~ dei cataloghi selezionati: realizzato e poi sostituito dal
  *progetto guidato*, che parte dalla tabella voluta invece che dai cataloghi.

## Altri passi della fase 0

- [ ] **Step 3 — Qualità del retrieval (RAG)**: embedding multilingue locali configurabili,
  soglia di rilevanza.

## Prossimi passi (da discutere)

Indicizzazione, in ordine di utilità prevista:

1. **Collaudo su cataloghi reali** e messa a punto dei prompt (`configs/prompts/`): analisi,
   guida, cataloghi simili, estrazione. Confrontare le modalità di input con la prova.
2. **CSV d'esempio** (tolto per semplificare): come riferimento di formato nella Tabella e per
   misurare la prova (copertura, precisione), da reintrodurre in un posto solo.
3. **Rifare solo alcune pagine** dopo una correzione (es. solo quelle con anomalie),
   accettando consapevolmente regole miste; oggi una correzione propone di rifare tutto.
4. ~~**Più pagine per richiesta**~~ → fatto: invio *insieme*, una richiesta per PDF con un
   estratto ritagliato, divisione automatica se la risposta è troppo lunga. Le quote
   giornaliere del piano gratuito sono diventate il collo di bottiglia (circa 100 pagine al
   giorno con una pagina per richiesta). Da misurare sui cataloghi reali: righe perse rispetto
   all'invio per pagina.
5. **Rilettura di verifica** opzionale: seconda chiamata sulle pagine con anomalie o con
   poche righe rispetto alle attese.
6. **Classificazione rapida delle pagine** per saltare automaticamente copertine, indici e
   legende senza segnarle nelle collezioni.
7. **Stima dei costi e del tempo** più precisa, in base ai token effettivi (l'SDK li
   restituisce in `usage_metadata`).
8. **Cache del contesto** di Gemini per guida e tabella, ripetute identiche in ogni pagina:
   ridurrebbe i costi sui cataloghi lunghi.

Altro:

- Modalità **Struttura**: indice gerarchico del documento; l'analisi del catalogo (collezioni
  di pagine) è un buon punto di partenza.
- RAG con filtri sui metadati e ricerca ibrida (keyword per codici esatti + vettoriale).
- Interfaccia grafica: modalità RAG (domande sui cataloghi).
- Pagina di ricerca: colonne visibili configurabili, ricerca per campo, pubblicazione su un
  sito (oggi è un file autonomo).

## Note dal collaudo

- **Quote per progetto.** I limiti di Gemini valgono per progetto Google Cloud, non per
  chiave: più chiavi dello stesso progetto non aumentano la capacità. Documentato nella
  guida.
- **Finto grassetto.** PyMuPDF lo estrae come parola ripetuta (`MOTOREMOTORE`), non
  come lettere triplicate come pdfplumber: gestito eliminando i frammenti sovrapposti.

- Negli indici fatti a mano capita che le righe della **seconda** pagina di una scheda
  riportino il numero della **prima** pagina. Il programma registra la pagina in cui la riga
  compare davvero; se servisse l'altro comportamento si può aggiungere un'opzione di output.
