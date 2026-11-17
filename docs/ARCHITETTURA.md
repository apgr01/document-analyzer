# Architettura

Come è organizzato il codice e **perché**. Utile per orientarsi prima di modificarlo.

## Principi

1. **Vision-first.** Ogni pagina viene trasformata in immagine e letta da Gemini. Estrarre
   il testo dal PDF è più economico, ma perde tabelle, icone e disposizione grafica, che nei
   cataloghi tecnici sono il contenuto principale.
2. **Il contenuto lo decide l'utente, non il codice.** Il programma non sa nulla di motori,
   codici o cataloghi. Tutto ciò che riguarda un catalogo sta in testi modificabili: la
   **guida all'indicizzazione** del catalogo (com'è fatto, come leggerne una pagina) e la
   **Tabella** del progetto (cosa estrarre). Un nuovo catalogo non richiede codice nuovo.
3. **Una pipeline sola.** Biblioteca → analisi del catalogo → progetto creato dalla scheda di
   un catalogo → ① Tabella → ② PDF e pagine → ③ Prova → ④ Indicizzazione → ⑤ Verifiche →
   ⑥ Risultati. Ogni
   decisione ha un posto solo, e niente si crea per vie traverse.
4. **Ogni chiamata a Gemini si paga una volta sola.** I risultati di ogni pagina vengono
   salvati su disco con un manifest; tutto ciò che viene dopo (unione, controlli, CSV) è
   deterministico e si può rifare all'infinito senza quota.
5. **Nessun limite preventivo.** Il programma non blocca richieste grandi (pagine, MB,
   cataloghi, lunghezza delle indicazioni): avvisa della quantità e dei tempi, e se Gemini
   rifiuta mostra l'errore.
6. **Dati dell'utente separati dall'applicazione.** Il codice sta nel repository, i dati nel
   *workspace* (`data/`). Si aggiorna il programma senza toccare i dati, e viceversa.
7. **Moduli piccoli con un solo compito**, collegati da uno strato applicativo (`app.py`)
   indipendente dall'interfaccia.

## Mappa dei moduli

```
src/docanalyzer/
├── cli.py              riga di comando ridotta (biblioteca, indicizzazione dei progetti, RAG)
├── ui.py               domande, messaggi, tabelle nel terminale
├── web/                interfaccia grafica (docanalyzer ui)
│   ├── server.py       API JSON (FastAPI) sopra app.py e i moduli qui sotto
│   ├── jobs.py         lavori in background: avanzamento, annullamento
│   ├── theme.py        temi: quali fogli di stile caricare (o incorporare) per il tema scelto
│   └── static/         pagina HTML, CSS e JavaScript (senza librerie esterne):
│                       app.js progetti e passi, library.js biblioteca e analisi,
│                       guided.js creazione del progetto, settings.js la Tabella,
│                       verifiche.js il passo ⑤, stile.js la pagina Stile,
│                       snake.js il mini gioco mostrato durante l'attesa
│                       css/: tokens.css (scale), themes/ (colori), app.css, game.css
├── app.py              strato applicativo: progetti, regole composte, risultati
├── library_analysis.py analisi di un catalogo: scheda (A) e guida all'indicizzazione (B)
├── guided_project.py   creazione del progetto: la Tabella dell'utente, i cataloghi simili
├── prova.py            ③ prova di indicizzazione su un campione di pagine
│
├── core/               infrastruttura comune alle due modalità
│   ├── paths.py        percorsi dell'applicazione
│   ├── config.py       configurazione validata (Pydantic)
│   ├── workspace.py    struttura della cartella dati
│   ├── projects.py     progetti: Tabella, PDF, impostazioni per PDF (pagine, guida, note)
│   ├── library.py      biblioteca: cartelle, tag, dati presenti, collezioni, guida
│   ├── documents.py    registro dei documenti (id, SHA-256)
│   ├── render.py       PDF -> PNG con cache
│   ├── pdf_tools.py    estratti PDF, testo nativo ripulito
│   ├── manifest.py     stato per pagina, per riprendere il lavoro
│   ├── page_runner.py  esecuzione parallela con arresto ordinato
│   ├── gemini.py       client Gemini: pool di chiavi, ritmo, errori
│   ├── fake_gemini.py  client simulato (test, prove senza quota)
│   ├── prompts.py      caricamento dei prompt da configs/prompts/
│   └── fileio.py       scrittura atomica di file
│
├── indexing/           modalità INDICIZZAZIONE (PDF -> CSV)
│   ├── spec.py         le regole di estrazione: modello, validazione, impronta
│   ├── prompt.py       prompt e JSON Schema per ogni pagina
│   ├── extractor.py    Gemini pagina per pagina -> JSON salvati (anche la prova)
│   ├── assemble.py     JSON -> righe del CSV, controlli, anomalie
│   ├── search_page.py  pagina di ricerca HTML autonoma sul CSV unico
│   └── export.py       scrittura di CSV e report anomalie
│
└── rag/                modalità RAG (domande e risposte, separata)
    ├── pipeline.py     descrizione delle pagine con la guida del catalogo, indice, risposte
    └── vector_index.py wrapper ChromaDB (dipendenza opzionale)
```

Le dipendenze vanno in una sola direzione: `cli / web → app → indexing/rag → core`. Nessun modulo
di `core` conosce le modalità, e le due modalità non si conoscono tra loro.

## Il flusso dell'indicizzazione

```
biblioteca:  PDF ─► documents/<id>/source.pdf + library.yaml (scheda)
analisi:     pagine scelte ─► Gemini (A) ─► proposta di scheda
             scheda proposta + pagine chiave ─► Gemini (B) ─► guida all'indicizzazione
progetto:    Tabella (utente) + PDF ─► projects/<id>/project.yaml
             (per PDF: pagine e guida copiate dalla biblioteca, note)

regole di un PDF = Tabella  +  note del PDF  (+ guida del catalogo come contesto)
                   App.project_rules()  App.document_rules()

prova / indicizzazione:
  render.py      pagine selezionate ─► pages/page-NNNN.png   (cache, saltate se presenti)
  prompt.py      regole + guida ─► prompt + JSON Schema
  extractor.py   per ogni pagina, in parallelo:
                   Gemini(immagine, testo, prompt, schema) ─► extractions/<progetto>/page-NNNN.json
                   manifest.json aggiornato (done / failed)       (prova: projects/<id>/prova/)
  assemble.py    tutti i JSON ─► contesto ereditato, normalizzazione, duplicati,
                                 ordinamento, controlli
  export.py      ─► exports/<progetto>/<progetto>.csv, documenti/<id>.csv, anomalie, ricerca.html
```

### Perché l'output strutturato

Gemini riceve un **JSON Schema** costruito dalle colonne della Tabella e deve rispondere
con un oggetto conforme (`page_context`, `rows`, `notes`, ...). Rispetto a chiedere "scrivi
un CSV" evita problemi di separatori, virgolette e righe spezzate, e rende la risposta
verificabile. Tutti i valori sono stringhe: tipi e formati vengono controllati dopo, in modo
deterministico, da `assemble.py`.

### Perché il contesto di pagina

Molti documenti mettono un'informazione in intestazione (es. il modello di motore) e poi una
tabella che non la ripete, a volte proseguendo sulla pagina successiva. Le colonne segnate
come **dato di intestazione** nella Tabella (`context: true` nelle regole) vengono chieste
anche come `page_context`; in fase di assemblaggio una riga
senza quel valore lo prende dalla sua pagina o, se manca, dall'ultima pagina che lo aveva.
In questo modo le pagine si elaborano **in parallelo** (nessuna dipende dalla precedente
durante la chiamata a Gemini) e la continuità si ricostruisce dopo.

### Perché l'impronta delle regole

Il manifest salva un'impronta (hash) di tutto ciò che influenza le risposte: descrizione,
riga, colonne, istruzioni (comprese le note del PDF), mappature, guida, modello e modalità di
input. Se cambia dopo un'estrazione, mescolare pagine vecchie e nuove produrrebbe un CSV
incoerente: il programma lo rileva (*regole cambiate: da rifare*) e chiede se rifare. Le
modifiche che non toccano le risposte (nome del progetto, `required`) non cambiano l'impronta:
basta rigenerare il CSV. L'impronta è per documento: le note o la guida di un PDF rendono
vecchio solo quel PDF.

## Progetti

Un **progetto** è l'unità di lavoro: una Tabella, uno o più PDF, un CSV unico. Si crea solo
dalla scheda di un catalogo (`App.create_project`, chiamato da `guided_project.py`).

```
progetto ── Tabella: descrizione, riga, colonne (nome, descrizione, dato di intestazione,
         │           chiave), altre indicazioni   ── decisa dall'utente, sempre modificabile
         ├── PDF: alfa, beta, gamma
         │     └── per PDF: pagine (copia delle collezioni), guida (copia della scheda), note,
         │                  pagine dell'elenco di riferimento
         ├── prova/: ultima prova per PDF, con l'impronta delle regole
         ├── verifiche/: esiti per verifica e PDF, segnalazioni accettate, elenchi di riferimento
         ├── correzioni.json: regole di sostituzione, celle corrette, righe eliminate
         └── export: CSV unico + CSV per PDF + anomalie con il file + ricerca.html
```

- **I 6 passi** (① Tabella, ② PDF e pagine, ③ Prova, ④ Indicizzazione, ⑤ Verifiche,
  ⑥ Risultati): il
  riepilogo del progetto (`project_steps` nel server) calcola lo stato di ogni passo e il
  **prossimo passo**, da Tabella, differenze con la biblioteca, prova (`prova.is_stale`) e
  avanzamento (`App.project_progress`, che legge solo i manifest). Ogni decisione ha un posto
  solo: *cosa* (① Tabella), *da dove e come leggere* (② pagine, guida, note).
- **Regole composte** (`App.project_rules`, `App.document_rules`): le regole di estrazione
  (`IndexingSpec`) non sono più un file scritto da qualcuno ma derivano dalla Tabella; per
  ogni PDF si aggiungono note e pagine (`IndexingSpec.for_document`) e la guida del catalogo
  accompagna ogni pagina. L'utente non vede mai YAML.
- **Copie dalla biblioteca** (`DocumentSettings.pages/collections/guide`): pagine e guida sono
  **copie**, perché fanno parte delle regole. Regola generale: *ciò che descrive si legge in
  diretta, ciò che comanda si copia*. `App.library_changes` confronta le copie con la
  biblioteca di oggi (collezioni cambiate o eliminate, guida diversa) e `update_from_library`
  ricopia su richiesta; i PDF già indicizzati diventano vecchi per l'impronta e si rifanno solo
  loro. Descrizione e dati presenti invece si leggono in diretta.
- **Note per PDF**: le differenze di un catalogo si esprimono come istruzioni aggiuntive solo
  per lui, invece di complicare le regole comuni. Le colonne non cambiano, così il CSV resta
  unico.
- **Righe uguali di PDF diversi** vengono tenute (lo stesso codice in due cataloghi è
  un'informazione); i duplicati dentro un PDF sono già tolti in fase di assemblaggio.
- **Contesto ereditato** solo dentro ciascun PDF: ogni documento viene assemblato a sé, poi i
  risultati vengono uniti.

### Verifiche e correzioni (`verifiche.py`, `correzioni.py`)

- **Provenienza delle righe**: l'assemblaggio mette in ogni riga `_src` = [pagina, posizione
  nella risposta di quella pagina] (`assemble.SOURCE_KEY`). Non finisce nel CSV, ma lega ogni
  riga del CSV al risultato da cui viene: è ciò che permette di correggerla, eliminarla o
  rifarne la pagina.
- **Correzioni come strato** (`correzioni.py`, `projects/<id>/correzioni.json`): i risultati
  delle pagine non si toccano mai. `correzioni.apply` lavora su una copia dei risultati di un
  PDF: prima celle corrette e righe eliminate, riconosciute da pagina, posizione e **valore
  originale** (se dopo una reindicizzazione il valore letto è diverso, la correzione risulta
  *non più applicabile* invece di colpire la riga sbagliata), poi le regole di sostituzione,
  che non toccano le celle corrette a mano. `App.document_index` applica le correzioni prima
  dell'assemblaggio, quindi valgono per CSV, pagina di ricerca e verifiche; non entrano
  nell'impronta delle regole di estrazione.
- **Verifiche** (`verifiche.py`): lavorano sulle righe corrette (`DocData`: indice assemblato,
  risultati originali, pagine attese, pagine fallite, testo nativo delle pagine in cache in
  `documents/<id>/text/pagine.json`). Il confronto dei valori usa `norm` (NFKC, minuscole,
  solo lettere e cifre). Solo l'elenco di riferimento chiama Gemini (`verify_reference.md`,
  un estratto ritagliato con le pagine dell'elenco, risposta validata in modo rigoroso come le
  altre); le altre sono deterministiche e il server le esegue subito, senza lavoro in
  background. Caratteri e doppioni confrontano i PDF scelti tra loro.
- **Esiti e firma** (`verifiche/risultati.json`): per verifica e PDF le segnalazioni, un
  riepilogo e una **firma** di ciò che determina l'esito (file dei risultati, impostazioni della
  verifica, correzioni di quel PDF — tutte per caratteri e doppioni —, elenco di riferimento).
  Se la firma cambia l'esito risulta *superato*. Le segnalazioni hanno un id stabile (hash del
  contenuto): quelle marcate *va bene così* stanno in `verifiche/accettate.json` e restano
  accettate finché la segnalazione non cambia.
- **Rifare singole pagine**: `POST /index` con `redo` = {pdf: [pagine]} cancella i risultati di
  quelle pagine, le riporta da fare nel manifest (`Manifest.reset_pages`) e le rifà, nella
  modalità di invio del progetto o in quella scelta per quella volta.

### La prova (`prova.py`)

- **Campione**: per ogni PDF scelto, `sample_pages` prende tra le pagine da indicizzare prima
  quelle d'esempio della biblioteca, poi pagine distribuite uniformemente; con *altre pagine*
  esclude quelle già provate (`history` in `prova.json`). Il numero per catalogo è libero.
- **Esecuzione**: `Extractor.preview` con le stesse regole e la stessa guida
  dell'indicizzazione, in `projects/<id>/prova/<documento>/`. Lo stato (`prova.json`) registra
  per PDF pagine, pagine fallite e impronta delle regole; una nuova prova sostituisce solo i
  PDF provati.
- **Vista**: `prova_view` assembla le righe come l'export vero (contesto, controlli,
  anomalie) e scrive il CSV di prova; un PDF la cui impronta è cambiata risulta *superato*.
- **Riuso**: all'avvio dell'indicizzazione `seed_index` copia le pagine della prova tra quelle
  fatte, se l'impronta coincide e solo per le pagine da indicizzare. Il piano mostra quante
  pagine vengono dalla prova; se restano solo quelle, l'indicizzazione le completa senza
  chiamare Gemini.

## Biblioteca

I PDF **vivono nella biblioteca**; i progetti li usano ma non li possiedono. Togliere un PDF da
un progetto o eliminare un progetto non cancella il PDF né i suoi risultati; un PDF si elimina
dalla biblioteca solo se nessun progetto lo usa.

```
data/documents/<id>/library.yaml    scheda: cartella, tag, descrizione, dati presenti, collezioni, guida
data/library/folders.yaml           cartelle (anche vuote)
```

- **Cartelle**: percorsi testuali (`Motori/Diesel`), un catalogo sta in una sola cartella.
  Rinominare o spostare una cartella aggiorna le schede che contiene.
- **Tag del catalogo**: liberi, senza doppioni (maiuscole e minuscole non contano). Filtrano
  i cataloghi di tutte le cartelle.
- **Dati presenti** (`fields` nella scheda): l'inventario dei dati indicizzabili del catalogo
  (nome + descrizione facoltativa), senza ordine. Servono a capire il PDF e a proporre
  progetti; le colonne del CSV le decide il progetto.
- **Collezioni di pagine**: intervalli continui con un **tag fisso** (`PAGE_TAGS` in
  `core/library.py`) e un commento. I tag sono fissi perché il programma li usa: le pagine
  `dati` diventano di default le pagine da indicizzare nei progetti, le pagine `esempio`
  vengono provate per prime; indice, legenda, esempi e la prima pagina di ogni sezione di dati
  sono le **pagine chiave** (`LibraryCard.key_pages`) mostrate a Gemini per la guida. Una
  pagina può stare in più collezioni.
- **Guida all'indicizzazione** (`LibraryCard.guide`, Markdown): come leggere una pagina isolata
  del catalogo. È per Gemini (la descrizione è per le persone) e accompagna ogni pagina del
  catalogo nei progetti, che ne usano una copia.
- **Analisi con Gemini** (`library_analysis.py`), **due richieste in fila** nello stesso
  lavoro:
  - **A, la scheda**: estratto PDF delle pagine scelte (o PDF intero) e prompt in due parti,
    le **indicazioni** modificabili dall'utente (`configs/prompts/library_analyze.md`,
    personali in `data/library/analysis_prompt.md`) e la **cornice** fissa
    (`library_analyze_frame.md`: corrispondenza delle pagine, tag disponibili, scheda
    attuale, regole sui numeri di pagina, formato della risposta) che viene *dopo* le
    indicazioni, le racchiude tra delimitatori e dichiara di prevalere su di esse;
  - **B, la guida**: la scheda appena proposta unita a quella attuale (`guide_card`), le
    pagine scelte più le pagine chiave (`guide_pages`), indicazioni (`library_guide.md`,
    personali in `data/library/guide_prompt.md`) e cornice fissa (`library_guide_frame.md`:
    risposta `{guide_markdown, notes}`). Un errore di B (anche di Gemini) non perde A: finisce
    in `guide_error` e la guida si rigenera dopo (`run_guide`, solo B, dalla scheda attuale);
  - risposte a schema rigido (`response_json_schema`, tag come `enum`), poi **ricontrollate in
    modo rigoroso** con modelli Pydantic (`extra="forbid"`, `strict=True`): un campo mancante o
    in più, un tipo sbagliato, un tag inesistente o una guida vuota rendono la risposta *non
    valida* (`InvalidAnswerError`), archiviata con la risposta originale ma mai applicata. Con
    la struttura a posto, le singole voci inutilizzabili (pagine fuori dal documento, campi
    doppi) vengono scartate e segnalate;
  - il risultato è una proposta salvata in `documents/<id>/analyses/` (`kind`: *analisi* o
    *guida*), applicata solo per le voci scelte, senza doppioni; la guida si può correggere
    prima di applicarla. Nessun limite su pagine, MB o indicazioni: le richieste rifiutate
    perché troppo pesanti (400/413) diventano `RequestTooLargeError`, mostrato all'utente.
- **Ritorno nella scheda** (`App.document_in_projects`): per ogni progetto che usa il PDF,
  pagine da indicizzare, se la guida copiata coincide con quella della scheda, pagine fatte e
  fallite tra quelle scelte, righe, errori, avvisi e impronta cambiata; per i progetti con la
  Tabella completa rigenera anche il CSV di quel PDF dai risultati salvati (senza Gemini),
  scaricabile dalla scheda.
- **Creazione del progetto** (`guided_project.py`): parte da un catalogo e dalla **Tabella
  scritta dall'utente** (`GuidedRequest`: nome, descrizione, riga, colonne con *dato di
  intestazione*, altre indicazioni). Gemini non la riscrive: una sola richiesta, solo testo,
  con la tabella e le schede di **tutti i cataloghi analizzati** (`LibraryCard.analyzed`), senza
  limiti di numero né tagli alle descrizioni. Cataloghi e sezioni hanno codici (`C3`, `C3/2`,
  `P/1`) che nello schema sono `enum`; stessa cornice fissa e stessa convalida rigorosa
  dell'analisi (una risposta che prova a riscrivere la tabella ha un campo in più: non valida),
  più i controlli sui codici (sconosciuti, ripetuti, il catalogo di partenza tra i candidati:
  non valida) e le correzioni segnalate (coperture con nomi che non sono colonne, sezioni di un
  altro catalogo). Il report (`data/library/guided/<id>.json`) diventa un progetto con la
  Tabella, i PDF, le pagine dalle sezioni scelte e le guide copiate. Senza Gemini,
  `create_direct` crea il progetto con il solo catalogo di partenza.
- **Scala**: l'interfaccia riceve l'elenco completo in una risposta (centinaia di schede sono
  pochi KB) e filtra nel browser; le miniature vengono create solo quando servono e restano
  in cache (`documents/<id>/thumbs/`).

## La pagina di ricerca

`search_page.py` genera un unico file HTML con i dati incorporati in JSON e un piccolo script:
nessun server, nessuna libreria, si apre ovunque. La ricerca normalizza testo e query
(minuscole, senza accenti, senza spazi/punti/trattini) e confronta per sottostringa: semplice
e adatta a codici scritti in modi diversi. Le righe che contengono la query intera vanno in
cima. I filtri nascono dalle colonne con 2-60 valori distinti. Con circa 30.000 righe il file
pesa ~4,5 MB e la ricerca richiede pochi millisecondi; oltre qualche centinaio di migliaia di
righe converrebbe un indice vero (es. SQLite FTS) servito da un server.

## L'interfaccia grafica (`docanalyzer ui`)

```
browser (static/*.js) ──HTTP JSON──► web/server.py ──► App, analisi, progetto guidato, prova, Extractor
        ▲                                   │
        └──── GET /api/jobs/<id> ◄── web/jobs.py: thread in background + RunControl
                (ogni secondo)               (avanzamento per pagina, annullamento)
```

### Stile e temi

Lo stile è a livelli, come nei design system:

1. **scale** (`css/tokens.css`): spazi, dimensioni del testo, raggi, durate, più le misure dei
   componenti (padding dei pulsanti e dei campi, pannelli, badge);
2. **colori per ruolo** (`css/themes/`): superficie, testo, accento, successo, avviso, errore,
   Gemini, collezioni di pagine, gioco. `light.css` è il tema di base e li definisce **tutti**;
   gli altri temi (`dark.css`, o uno nuovo) ridefiniscono solo quelli che cambiano;
3. **componenti** (`css/app.css`, `css/game.css`): usano solo le variabili. Le regole di base
   degli elementi (campi, menu) sono scritte con `:where()`, che ha specificità zero, così ogni
   classe può modificarle senza `!important`.

Il tema si sceglie in configurazione (`ui.theme`: `auto`, `light`, `dark` o il nome di un
file in `themes/`); `web/theme.py` decide quali fogli collegare nella pagina e quale CSS
incorporare nelle pagine autonome (la pagina di ricerca esportata usa così lo stesso tema).
Anche il gioco legge i suoi colori dal tema (`--game-*`), compreso il disegno sul canvas.
Nel JavaScript non ci sono colori né stili fissi: solo classi, e `style` per i valori
calcolati (la larghezza di una barra di avanzamento). Un test (`tests/test_style.py`) lo
controlla, insieme al fatto che ogni variabile usata sia definita. La pagina `#/stile` mostra
variabili e componenti con il tema in uso.

Scelte:

- **Server locale + pagina web**, non un file HTML da solo: il browser non può leggere le
  chiavi nel `.env` né elaborare i PDF; il server ascolta solo su `127.0.0.1`.
- **FastAPI + JavaScript semplice** invece di Streamlit: Streamlit riesegue la pagina a ogni
  interazione, scomodo per bozze, conferme e versioni; un'interfaccia scritta a mano lascia
  il pieno controllo del flusso e resta leggibile senza strumenti di compilazione.
- **Nessuna logica nell'interfaccia**: le API chiamano gli stessi oggetti della riga di
  comando, quindi i due modi d'uso producono gli stessi file e possono essere alternati.
- **Lavori in background, uno per progetto o per catalogo**: chiamate lunghe e
  indicizzazione non bloccano il server; `RunControl` porta l'avanzamento pagina per pagina e la richiesta di
  annullamento fino a `run_pages`.
- **Niente parte verso Gemini da sola**: gli endpoint che usano Gemini (analisi, guida,
  ricerca dei cataloghi simili, prova, indicizzazione) sono separati da quelli che preparano o
  mostrano (`.../preview`, `.../plan`), e la pagina li chiama solo dopo una conferma con il
  numero di richieste, il peso degli allegati e una stima dei tempi.
- **PyMuPDF e thread**: miniature e lavori possono arrivare insieme, quindi tutte le
  aperture di PDF passano da un unico lucchetto (`PDF_LOCK`).

## Cosa riceve Gemini per ogni pagina

`indexing.input` in configurazione:

| Modalità | Allegati | Note |
|---|---|---|
| `image+text` (default) | PNG della pagina + testo nativo estratto nel prompt | immagine per struttura e associazioni, testo per caratteri esatti |
| `image` | PNG della pagina | per PDF con testo estratto inaffidabile |
| `pdf` | PDF di una pagina | Gemini usa testo e grafica da sé; risoluzione non controllabile |

Il testo nativo viene ripulito (`pdf_tools.page_text`): i frammenti duplicati e sovrapposti
del *finto grassetto* vengono eliminati prima di ricomporre le righe; tra frammenti lontani
sulla stessa riga si inserisce ` | ` per separare le colonne.

Le colonne di contesto non vengono ripetute nelle righe (Gemini le dà una volta in
`page_context`) per tenere corte le risposte.

### Modalità di invio: una pagina o più pagine per richiesta

Il progetto sceglie come inviare le pagine (`ProjectInfo.send_mode`, usata da prova e
indicizzazione tramite `App.send_options`):

- **`pagina`** (una per richiesta): massima precisione sulle pagine dense; un errore costa
  una pagina sola. Le richieste però sono tante, e nel piano gratuito di Gemini il collo di
  bottiglia è il **numero di richieste al giorno**, non i token.
- **`insieme`**: per ogni PDF un **estratto ritagliato dal PDF originale**
  (`build_subset_pdf`) con le sue pagine da indicizzare, in una richiesta; prompt
  `indexing_batch.md` con la corrispondenza delle pagine, schema `{"pages": [{"page": n,
  ...come una pagina...}]}` (`build_block_schema`). Ogni elemento diventa il `page-NNNN.json`
  di quella pagina, come nella modalità per pagina, quindi assemblaggio, controlli, impronta
  e riuso della prova non cambiano. I PDF non si mescolano mai (le righe restano abbinate al
  loro PDF). Il lavoro è in `Extractor._extract_together` con `run_blocks`
  (`page_runner.py`): il manifest resta per pagina e ogni pagina viene segnata appena salvata,
  così una quota esaurita a metà non perde quelle già ottenute.
  - **Divisione automatica**: se la risposta è interrotta per lunghezza (`IncompleteResponseError`
    con `reason == "MAX_TOKENS"`) o la richiesta è troppo grande (`RequestTooLargeError`), il
    gruppo si divide a metà e si riprova, fino alla pagina singola.
  - Pagine non restituite da Gemini: fallite ("non restituita"), si rifanno al giro dopo.
  - `pages_per_request` (facoltativo) divide in partenza le pagine di un PDF in gruppi.

La modalità **non entra nell'impronta**: i risultati sono per pagina in entrambi i casi, e si
può passare da una all'altra (per esempio rifare una pagina alla volta solo le pagine fallite)
senza rifare il resto.

## Il client Gemini

`core/gemini.py` gestisce N chiavi API come un pool:

- ogni chiave ha un *prossimo istante libero*; il ritmo `requests_per_minute_per_key` è
  rispettato **per chiave e tra tutti i thread** (un unico lock);
- `429` al minuto → pausa della chiave; `429` giornaliero → chiave esclusa; quando tutte
  sono escluse → `QuotaExhaustedError`, che ferma l'elaborazione in modo ordinato;
- `5xx` e rete → nuovo tentativo con attesa crescente (backoff esponenziale);
- `503` sovraccarico ("high demand") → nuovo tentativo a intervallo fisso, senza consumare
  tentativi: è un problema momentaneo di Google, uguale per tutte le chiavi, e raddoppiare le
  attese allungherebbe solo i tempi; oltre `max_wait_minutes` → `ServiceUnavailableError`, che
  ferma il lavoro in modo ordinato come le quote esaurite;
- annullamento: ogni lavoro registra nel proprio thread l'evento "Ferma" (`cancellation`), che il
  client controlla prima di ogni tentativo e durante ogni attesa;
- risposte interrotte (lunghezza massima) o bloccate dai filtri → errore immediato della
  pagina con spiegazione, senza tentativi inutili;
- altri errori → subito, con messaggio chiaro.

**Quote.** Il tipo di quota superata (al minuto / giornaliera) e l'attesa suggerita si leggono
dai *dettagli* dell'errore 429 (`QuotaFailure.quotaId`, `RetryInfo.retryDelay`). Poiché le
quote valgono per progetto, oltre al limite per chiave c'è un **ritmo complessivo adattivo**
(`_AdaptiveLimit`): a ogni episodio di quota superata scende al 90% delle richieste riuscite
nell'ultimo minuto, poi risale del 10% ogni 20 successi. Gli errori di quota non fanno
fallire le pagine: oltre 15 minuti di quota esaurita il lavoro si ferma in modo ordinato.

PDF fino a 15 MB vengono inviati direttamente nella richiesta; oltre, tramite la Files API
(caricati con la chiave del tentativo, attesi fino allo stato ACTIVE, poi eliminati).

`orologio` e `sleep` sono iniettabili: i test verificano rotazione e attese senza aspettare
davvero. `FakeGeminiClient` ha la stessa interfaccia (`LLMClient`) e permette di provare
l'intero programma senza rete (`DOCANALYZER_FAKE_GEMINI=1`).

## Scelte e alternative scartate

| Scelta | Alternativa | Motivo |
|---|---|---|
| Tabella scritta dall'utente, regole composte dal programma | Specifica YAML scritta da Gemini in una configurazione guidata | Cosa estrarre è una decisione dell'utente; il programma la traduce in regole validabili senza mostrare YAML, e una sola fonte evita disallineamenti |
| Guida all'indicizzazione per catalogo, nella biblioteca | Primer per progetto | Com'è fatto un catalogo non dipende dal progetto: la guida si scrive una volta e serve a tutti i progetti che lo usano |
| Prova con le regole vere, riusata | Anteprima con regole provvisorie | Ciò che si vede nella prova è esattamente ciò che produrrà l'indicizzazione, e le pagine provate non si pagano due volte |
| Nessun limite preventivo | Tetti su pagine, MB, cataloghi | I limiti di Gemini cambiano; meglio avvisare e mostrare l'errore che impedire richieste che potrebbero riuscire |
| Due modalità di invio, scelte per progetto | Solo una pagina per chiamata | Una pagina per chiamata è la più precisa sulle pagine dense; più pagine per chiamata (per PDF, estratto ritagliato) riduce drasticamente le richieste, che nel piano gratuito sono il limite; i risultati restano per pagina in entrambi i casi |
| Contesto ricostruito dopo | Passare la pagina precedente a Gemini | Raddoppierebbe i costi e impedirebbe il parallelismo |
| CLI con argparse | Typer/Rich | Nessuna dipendenza in più; output semplice leggibile su ogni console Windows |
| Interfaccia web locale (FastAPI + JS) | Streamlit/Gradio, app desktop | Pieno controllo di conferme, bozze e versioni; nessuna compilazione; si apre in qualsiasi browser |
| ChromaDB opzionale | Dipendenza obbligatoria | L'indicizzazione non lo usa e su alcune versioni di Python/Windows è difficile da installare |
| Estratto PDF con pagine scelte (analisi e guida) | PDF intero sempre | Limiti di dimensione, costi e contenuto ripetitivo; l'utente sa quali pagine spiegano il catalogo |
| Corrispondenza delle pagine nel prompt | Numero originale stampato sulle pagine | Le pagine restano identiche all'originale; nessun elemento estraneo da interpretare |
| Immagine + testo nativo per pagina | Solo immagine / solo PDF | Struttura dall'immagine, caratteri esatti dal testo; configurabile e verificabile con la prova |
