# Guida: dai cataloghi PDF a un CSV

Questa guida accompagna passo per passo dall'installazione al CSV finale. Gli esempi usano
cataloghi di ricambi motore, ma il procedimento è lo stesso per qualunque PDF.

I comandi sono scritti per **Windows PowerShell**; su macOS/Linux cambia solo
l'attivazione dell'ambiente virtuale (`source .venv/bin/activate`).

**In breve:** si lavora nell'interfaccia grafica nel browser.

```powershell
docanalyzer ui
```

Il percorso è uno solo, sempre lo stesso:

```
Biblioteca ──► Analisi del catalogo ──► Progetto dal catalogo ──► ① Tabella ② PDF e pagine ③ Prova ④ Indicizzazione ⑤ Verifiche ⑥ Risultati
 (carichi i     (Gemini: scheda e         (scrivi la tabella;        (controlli e correzioni, poi il CSV unico e la pagina di ricerca)
  PDF)           guida all'indicizzazione)  Gemini trova i simili)
```

1. **Biblioteca**: carichi i PDF e li organizzi in cartelle.
2. **Analisi del catalogo**, uno alla volta: Gemini propone la *scheda* (descrizione, tag,
   dati presenti, collezioni di pagine) e subito dopo scrive la **guida all'indicizzazione**,
   cioè come leggere una pagina isolata di quel catalogo. Rivedi e applichi.
3. **Progetto**: lo crei dalla scheda di un catalogo scrivendo **a mano la tabella** che vuoi
   (cosa rappresenta una riga e le colonne). Gemini non la tocca: cerca solo, tra i cataloghi
   analizzati, quelli che possono produrre righe della stessa tabella.
4. Nel progetto: controlli PDF e pagine, fai una **prova** su poche pagine, poi
   **indicizzi** tutto, **verifichi e correggi** i risultati e scarichi il CSV.

---

## 0. Installazione (una volta sola)

```powershell
git clone https://github.com/apgr01/document-analyzer.git
cd document-analyzer
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
copy .env.example .env
notepad .env
```

Nel file `.env` inserisci le chiavi, una per riga:

```
GEMINI_API_KEY_01=la-tua-prima-chiave
GEMINI_API_KEY_02=la-tua-seconda-chiave
```

Poi verifica:

```powershell
docanalyzer doctor --online
```

> **Se PowerShell non permette di attivare l'ambiente** ("l'esecuzione di script è
> disabilitata"), esegui una volta `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
>
> **Ogni volta che apri un nuovo terminale** entra nella cartella del progetto e riattiva
> l'ambiente con `.venv\Scripts\Activate.ps1`.

> **Quote e chiavi.** I limiti di Gemini (richieste al minuto e al giorno) valgono per
> **progetto** Google Cloud, non per singola chiave: più chiavi aumentano davvero la
> capacità solo se appartengono a progetti diversi. Il programma se ne accorge da solo:
> - **quota al minuto superata** → rallenta il ritmo complessivo fino a quello che il
>   progetto sopporta e aspetta il tempo indicato da Google (un messaggio
>   "rallento a circa N richieste/minuto"); poi risale piano piano;
> - **quota giornaliera esaurita** → la chiave viene esclusa; quando lo sono tutte il lavoro
>   si ferma in modo ordinato.
>
> In entrambi i casi le pagine **non** vengono segnate come fallite: rilanciando si riparte
> da dove ci si era fermati. Se conosci il limite del tuo progetto puoi indicarlo in
> `configs\default.yaml` (`gemini.max_requests_per_minute_total`) per evitare del tutto gli
> errori di quota.

---

## 1. Avvio: `docanalyzer ui`

```powershell
docanalyzer ui
```

Il comando avvia un piccolo server **solo su questo computer** e apre il browser su
`http://127.0.0.1:8765`. Lascia aperta la finestra del terminale finché usi l'interfaccia;
per chiuderla premi Ctrl+C.

In alto ci sono due sezioni: **Progetti** (l'elenco dei progetti, ciascuno con i suoi passi e
il prossimo passo da fare) e **Biblioteca** (tutti i PDF).

**Protezioni, ovunque:**
- i pulsanti con la stellina ✨ usano Gemini e chiedono sempre conferma, dicendo **quante
  richieste** partiranno, quanto pesano gli allegati e quanto dureranno (stime indicative);
  il tasto Invio non invia mai nulla;
- **nessun limite preventivo**: il programma non blocca richieste grandi (tante pagine, PDF
  pesanti, molti cataloghi, indicazioni lunghe), avvisa soltanto. Se Gemini rifiuta una
  richiesta, l'errore viene mostrato così com'è;
- prima di inviare puoi vedere il **prompt esatto** (*Vedi il prompt*);
- i testi che scrivi restano bozze salvate nel browser finché non li salvi o li invii; se
  hai modificato una descrizione, la guida o le note senza salvare, cambiando pagina viene
  chiesto se perdere le modifiche;
- su ogni progetto (e su ogni catalogo) può girare una sola operazione alla volta;
- durante un'operazione i messaggi di Gemini (sovraccarico, quote, rallentamenti) compaiono
  sotto la barra di avanzamento; *Ferma* interrompe subito anche le attese in corso. Mentre
  aspetti puoi giocare a **Gemini Snake** (*Gioca mentre aspetti*: è nascosto finché non lo apri).

---

## 2. Biblioteca

La sezione **Biblioteca** raccoglie tutti i PDF, organizzati in **cartelle**:

1. **Carica** i PDF nella cartella aperta: trascinali, oppure *Scegli PDF* / *Scegli una
   cartella*. Trascinando una cartella intera le sottocartelle vengono ricreate. Un PDF già
   presente (stesso contenuto, anche con un altro nome) non viene duplicato.
2. **Organizza**: crea cartelle (anche su più livelli, `Motori/Diesel`), rinominale o
   spostale; seleziona più cataloghi per spostarli, dare o togliere **tag**, eliminarli.
3. **Cerca e filtra**: la casella di ricerca guarda nome, file, descrizione e tag; un clic su
   un tag mostra i cataloghi con quel tag da tutte le cartelle (più tag: devono averli tutti).
   Nella colonna *Studio* vedi a che punto è ogni catalogo: dati presenti, collezioni, pagine
   di dati, **guida**, proposta di Gemini da rivedere.
4. **Apri un catalogo** (clic sul nome). In alto: *analizzato* / *da analizzare*, *guida* /
   *senza guida* e il pulsante **Crea progetto da questo catalogo…**. Poi:
   - **Scheda**: titolo, cartella, tag e una descrizione libera di cosa contiene e com'è
     fatto (per le persone).
   - **Dati presenti**: l'inventario dei dati che si potrebbero estrarre dal catalogo
     (motore, versione, codice, alesaggio...), in qualsiasi ordine, con una descrizione
     facoltativa. Non decidono le colonne del CSV, che sceglie il progetto: servono a capire
     il PDF e a trovare i cataloghi simili.
   - **Guida all'indicizzazione** (vedi il capitolo 3): il testo che accompagna ogni pagina di
     questo catalogo quando un progetto lo indicizza. Si può correggere a mano e salvare.
   - **Pagine e collezioni**: sfoglia le miniature (frecce ← → per cambiare pagina; mentre
     giochi a Snake le frecce sono del gioco); *Apri il PDF ↗* apre il PDF originale in una
     nuova scheda alla pagina che stai guardando. Clic per vedere una pagina,
     **Maiusc+clic** per selezionare un intervallo, poi scegli il tag e aggiungi la
     collezione (es. 1-2 *Copertina*, 3-4 *Indice*, 9-250 *Dati* con il commento "tabelle
     codici per motore", 12-13 *Pagina d'esempio*). Una pagina può stare in più collezioni.
     Due tag contano per il programma: le pagine **Dati** sono quelle da indicizzare (di
     default nei progetti), le **Pagine d'esempio** vengono provate per prime nella prova.
   - **Crea progetto** e **Nei progetti**: i progetti che usano questo PDF e, per ciascuno,
     le pagine da indicizzare (📚 se vengono dalla biblioteca), se la guida copiata nel
     progetto coincide con quella della scheda, e come procede l'indicizzazione (pagine fatte
     e fallite, righe, errori, avvisi, *regole cambiate: da rifare*). Da qui scarichi il
     **CSV di questo PDF**.

Togliere un PDF da un progetto o eliminare un progetto **non** cancella il PDF: resta nella
biblioteca con i suoi risultati. Si elimina dalla biblioteca, e solo se nessun progetto lo usa.

---

## 3. Analisi del catalogo: scheda e guida all'indicizzazione

Pannello **✨ Analisi con Gemini** nella scheda del catalogo. Un catalogo alla volta.

**Cosa scegli:**
- le **pagine da inviare**, sulle miniature (clic, Maiusc+clic per un intervallo, doppio
  clic per ingrandire) oppure scritte (`1-6, 20, 45-46`). *Selezione rapida* mette le prime
  6 pagine più 8 distribuite; in alternativa spunta *Invia tutto il PDF*. Di solito bastano
  copertina, indice, legenda e qualche pagina tipo: dall'indice Gemini deduce anche le parti
  che non vede;
- le **indicazioni per Gemini** su cosa cercare (modificabili: *Salva come mio predefinito*,
  *Ripristina quello di fabbrica*) e, nel pannello della guida, le **indicazioni sulla
  guida**;
- *Tieni conto della scheda attuale*: Gemini completa e corregge quello che hai già scritto.

**Cosa succede** (*Analizza con Gemini*): **due richieste in fila**, senza altri interventi.
1. **Scheda** (richiesta A): con le pagine scelte, Gemini propone descrizione, tag, dati
   presenti, collezioni di pagine e osservazioni.
2. **Guida all'indicizzazione** (richiesta B): con la scheda appena proposta, le stesse
   pagine e in più le **pagine chiave** (indice, legenda, pagine d'esempio e la prima pagina
   di ogni sezione di dati), Gemini scrive le istruzioni per leggere una pagina isolata del
   catalogo: struttura, com'è fatta una pagina di dati, convenzioni, sigle e soprattutto
   **cosa non si deduce dalla pagina da sola** (intestazioni non ripetute, tabelle che
   continuano, celle vuote con un significato). Non decide le colonne: quelle cambiano da
   progetto a progetto.

Il **formato** di entrambe le risposte è fisso: lo aggiunge il programma dopo le tue
indicazioni, con la regola che prevale su qualsiasi richiesta diversa. Ogni risposta viene
controllata: se manca un campo, ce n'è uno in più, un tipo è sbagliato o un tag non esiste,
la risposta è **non valida** e non tocca niente (resta in archivio, *vedi la risposta*). Se
la seconda richiesta non riesce, la scheda proposta resta comunque utilizzabile e la guida si
rigenera dopo.

**La proposta.** Le risposte diventano una proposta da rivedere: scegli la descrizione (non
usare, sostituisci, aggiungi in fondo), i tag, i dati presenti, le collezioni (quelle
*dedotte* sono state ricavate dall'indice senza vedere le pagine: controllale) e la **guida**,
che puoi correggere prima di applicarla. Niente cambia nella scheda finché non premi
*Applica i selezionati*. Ogni analisi resta in archivio (*Analisi archiviate*).

**Rigenerare la guida.** *✨ Rigenera la guida dalla scheda attuale…* esegue solo la seconda
richiesta, con la scheda così com'è ora (anche corretta a mano) e le sue pagine chiave, più le
pagine eventualmente selezionate nell'analisi (o tutto il PDF). La nuova guida è una proposta:
quella attuale resta finché non la applichi. Utile dopo aver sistemato collezioni o
descrizione, o se la prova mostra che Gemini fraintende qualcosa.

---

## 4. Creare un progetto (dalla scheda di un catalogo)

Un progetto produce **una tabella**, un CSV unico, da uno o più cataloghi. Si crea solo da
qui: nella scheda del catalogo di partenza premi **Crea progetto da questo catalogo…**.

**La tabella**, scritta da te:
- **nome** del progetto e **descrizione** facoltativa (a cosa serve l'indice);
- **cosa rappresenta una riga** — la decisione più importante (es. "una riga per ogni codice
  ricambio di ogni motore");
- le **colonne**, nell'ordine del CSV, ciascuna con una descrizione (cosa contiene, formato);
  un clic sui *dati presenti* del catalogo le aggiunge già descritte. La casella
  **Intestazione** segna un **dato di intestazione**: un valore che compare una volta sola
  nella pagina o nella sezione (es. il modello del motore nel titolo) e vale per tutte le
  righe; se una pagina non lo ripete viene preso dalla pagina precedente;
- in fondo alle colonne vedi sempre le due che il programma **aggiunge a ogni riga**:
  `PAGINA_PDF` (la pagina del PDF da cui viene la riga) e `FILE_ORIGINE` (il nome del file PDF
  così com'è, con spazi e caratteri speciali). Non chiederle a Gemini: non riceve il nome del
  file, e una colonna come "nome del PDF" resterebbe vuota (la tabella te lo segnala). I due
  nomi sono riservati. `PAGINA_PDF` è la pagina nel PDF, non il numero stampato sul catalogo:
  se ti serve quello, una colonna apposta ha senso;
- **altre indicazioni** facoltative, valide per tutti i PDF (es. "codici senza spazi").

Poi due strade:
- **Crea il progetto solo con questo catalogo**: subito, senza Gemini. Altri PDF si
  aggiungono dopo (passo ②);
- **✨ Cerca i cataloghi simili**: una richiesta, solo testo, con la tabella, la scheda del
  catalogo di partenza e quelle di **tutti i cataloghi analizzati** della biblioteca (nessun
  limite di numero: la conferma dice quanti sono e quanto è grande la richiesta). Gemini
  **non riscrive la tabella**: dice quali colonne si ricavano dal catalogo di partenza e
  quali sue sezioni contengono i dati, e propone i **candidati** *compatibili* (le colonne
  principali ci sono tutte) o *parziali*, con il motivo, le colonne coperte e le sezioni con
  i dati. Usa codici per cataloghi (`C1`) e sezioni (`C1/2`): se cita codici inesistenti o
  sbaglia il formato, la risposta è *non valida* e non si usa.

**Il report** mostra la tabella (in sola lettura: si modifica poi nel progetto), con accanto
a ogni colonna in quanti PDF scelti si ricava; spunti i cataloghi (i compatibili lo sono già)
e, per ciascuno, le sezioni da indicizzare. **Crea progetto** copia nel progetto, per ogni
PDF, le **pagine** delle sezioni scelte (altrimenti le collezioni *Dati*) e la **guida
all'indicizzazione** della sua scheda. Le ricerche restano nella scheda (*Ricerche
precedenti*), con il link al progetto creato.

Lo stesso catalogo può avviare più progetti, per tabelle diverse (es. "una riga per motore" e
"una riga per componente").

---

## 5. Il progetto in 6 passi

Aprendo un progetto ti trovi sul **prossimo passo** da fare, sempre indicato in alto; ogni
passo ha il suo stato (*fatto*, *in corso*, *da rivedere*, *da fare*, *facoltativo*).

### Come Gemini legge una pagina: le regole

Le regole di estrazione non si scrivono a mano: le compone il programma, per ogni PDF, da tre
parti con un posto preciso ciascuna.

| Parte | Dove si decide | Vale per |
|---|---|---|
| **Tabella** (riga, colonne, descrizione, altre indicazioni) | ① Tabella | tutti i PDF del progetto |
| **Guida all'indicizzazione** | scheda del catalogo nella biblioteca (copiata nel progetto) | quel catalogo |
| **Note** | ② PDF e pagine | quel PDF in quel progetto |

Ogni pagina viene inviata da sola (immagine e testo del PDF) insieme a queste tre parti. Se una
di esse cambia dopo l'indicizzazione, i risultati ottenuti con le regole vecchie vengono
segnalati (*regole cambiate: da rifare*), solo per i PDF interessati: la tabella riguarda
tutti, guida e note solo il loro PDF. Non si mescolano mai risultati di regole diverse.

### ① Tabella

La tabella del progetto, sempre modificabile: nome, descrizione, riga, colonne (con
*Intestazione* e *Chiave*), altre indicazioni. A destra i **dati presenti** dei PDF del progetto: un
clic li aggiunge come colonna; il numero dice in quanti PDF compaiono. Cambiare la tabella
dopo l'indicizzazione rende da rifare le pagine già fatte (e la prova): viene chiesta
conferma. Cambiare solo il nome o le colonne chiave non rifà nulla.

- **Intestazione**: un valore che compare una volta nella pagina o nella sezione (es. il
  modello del motore nel titolo) e vale per tutte le sue righe.
- **Chiave**: le colonne che identificano una riga (es. il motore; se sono più di una conta la
  loro combinazione). Non cambiano l'estrazione: servono alle verifiche del passo ⑤ (elenco di
  riferimento, doppioni, valori vuoti, contenuto sulla pagina), quindi si possono segnare
  anche dopo l'indicizzazione.

### ② PDF e pagine

Per ogni PDF:
- le **pagine da indicizzare**: spunta le collezioni della scheda (di solito *Dati*) e le
  loro pagine vengono copiate nel progetto, oppure scrivile a mano (vuoto = tutto il PDF);
- la **guida** copiata dalla biblioteca (*Guida* per leggerla; *senza guida* se il catalogo
  non è stato analizzato);
- le **note**: istruzioni in più valide solo per quel PDF (es. "in questo catalogo la
  versione è sotto il nome del motore").

*Aggiungi PDF dalla biblioteca…* aggiunge altri cataloghi (con le loro pagine *Dati* e la loro
guida). Pagine e guida sono **copie**: se nella biblioteca cambiano (collezioni modificate o
eliminate, guida corretta o rigenerata) il progetto non cambia da solo, ma lo segnala, e
**Aggiorna dalla biblioteca** le ricopia (i PDF già indicizzati andranno rifatti). Le
collezioni *Dati* nuove sono solo un suggerimento.

### ③ Prova

Prima di indicizzare tutto, Gemini estrae le righe da **poche pagine da indicizzare** per
catalogo, con esattamente le regole vere. Così vedi subito se tabella e guida funzionano.
- **Pagine per catalogo**: 4 di default, il numero si cambia. *Proponi le pagine* sceglie
  prima le pagine d'esempio che sono anche da indicizzare, poi pagine distribuite nel resto;
  **Altre pagine** ne propone di non ancora provate. Puoi anche scriverle a mano.
- Spunta i **PDF** da provare: la prova sostituisce quella precedente solo per quei PDF.
- Il risultato mostra, per ogni PDF, le righe estratte (clic per vedere la pagina), le righe
  per pagina, le pagine non riuscite, le note di Gemini e le segnalazioni dei controlli; *Scarica
  il CSV di prova*.

Non ti convince? Correggi la tabella, la guida del catalogo (nella biblioteca, poi *Aggiorna
dalla biblioteca*) o le note del PDF, e rifai la prova. Se le regole cambiano dopo la prova, la
prova di quel PDF risulta *superata*. Le pagine provate **non si pagano due volte**: se le
regole non sono cambiate, all'indicizzazione contano già come fatte.

### Come inviare le pagine a Gemini (passi ③ e ④)

In cima alla Prova e all'Indicizzazione c'è il pannello **Come inviare le pagine a Gemini**,
che vale per entrambe:

- **Una pagina per richiesta**: ogni pagina da sola (immagine e testo, secondo
  `indexing.input`). È il modo più preciso sulle pagine molto dense, ma fa una richiesta per
  pagina.
- **Tutte le pagine di un PDF insieme**: per ogni PDF un **estratto ritagliato dal PDF
  originale** con solo le sue pagine da indicizzare, in **una richiesta per PDF**; il prompt
  dice a Gemini a quale pagina dell'originale corrisponde ogni pagina dell'estratto, e Gemini
  risponde pagina per pagina. I PDF non si mescolano mai, quindi ogni riga resta abbinata al
  suo PDF e alla sua pagina. Fa molte meno richieste: è la scelta giusta quando il limite è il
  numero di richieste al giorno (piano gratuito). Se la risposta di un PDF è troppo lunga (o
  Gemini rifiuta la richiesta perché troppo grande), il programma divide da solo le sue pagine
  a metà, in più richieste dello stesso PDF. Le pagine che Gemini non restituisce risultano
  fallite e si rifanno al giro successivo.
  - *Al massimo N pagine per richiesta* (facoltativo, vuoto = tutte): divide in partenza le
    pagine di un PDF in gruppi più piccoli, utile se Gemini rifiuta richieste troppo grandi.

La modalità di invio **non cambia le regole**: i risultati sono sempre per pagina, le pagine
già fatte restano valide e puoi, per esempio, rifare una pagina per richiesta solo le pagine
fallite nell'altro modo. Conviene fare la prova nella modalità che userai per indicizzare.

### ④ Indicizzazione

Il piano mostra per ogni PDF le pagine, quelle già fatte, quelle **riusate dalla prova**,
quelle da fare e le **richieste** a Gemini (una per pagina, oppure una per PDF con l'invio
insieme), con il tempo stimato (si adatta alle quote); con l'invio insieme dice anche quanto
è grande la richiesta più grande.

- **Avvia l'indicizzazione** fa solo le pagine non ancora indicizzate, comprese quelle
  **fallite**, che si ritentano sempre. Sotto la tabella trovi il **motivo** dei fallimenti di
  ogni PDF (es. richiesta troppo grande, quota esaurita, risposta troppo lunga).
- **Rifai da capo**, sulla riga di un PDF, cancella i risultati di quel PDF e rifà tutte le sue
  pagine, senza toccare gli altri; **Rifai tutto da capo…** fa lo stesso per tutti i PDF. In
  entrambi i casi le pagine della prova non vengono riusate, e la conferma dice quante
  richieste partiranno. Puoi
chiudere la pagina: il lavoro continua finché il server è acceso, e si riprende da dove era se
lo fermi. Se le regole di qualche PDF sono cambiate, viene detto quali risultati verranno
sostituiti (solo quei PDF).

### ⑤ Verifiche ed elaborazione

Finita l'indicizzazione il progetto si apre qui. È una schermata simile ai risultati: in alto
i **PDF** (*Tutti i PDF*, oppure un clic su un PDF per lavorare solo su quello; Ctrl/⌘ + clic
per sceglierne più d'uno) e la tabella **verifiche × PDF** con l'esito di ognuna (*da
eseguire*, *nessun problema*, *N da vedere*, *da rieseguire* se dopo la verifica sono cambiati
risultati, correzioni o impostazioni di quel PDF). La prova del passo ③ non si verifica: serve
solo a vedere com'è la tabella.

**Esegui le verifiche senza Gemini** le fa tutte subito (anche il confronto con un elenco di
riferimento già letto); *Esegui* su una riga ne fa una sola. Clic su una riga per vederne le
segnalazioni.

| Verifica | Cosa controlla | Gemini |
|---|---|---|
| **Copertura delle pagine** | ogni pagina inviata ha almeno una riga (o *esattamente* una, nelle impostazioni); pagine fallite o mai elaborate | no |
| **Contenuto sulla pagina** | su **tutte** le righe: i valori delle colonne scelte si trovano nel testo della pagina da cui viene la riga (confronto senza spazi, simboli e maiuscole); se no, su quale altra pagina stanno. Le pagine senza testo (scansioni) vanno guardate a vista | no |
| **Elenco di riferimento** | un elenco che riporta tutte le voci (indice, sommario, listino…): Gemini lo trascrive (**una richiesta per PDF**, la prima volta) e il programma lo confronta con il CSV: voci **mancanti** (con le righe simili), voci **solo nel CSV**, **pagine che non tornano** (calcola lo scarto tra pagina stampata e pagina del PDF) | sì, una volta |
| **Caratteri sospetti** | caratteri rotti (`�`, quadratini, caratteri privati) e simboli rari in una colonna | no |
| **Valori vuoti** | righe con una colonna chiave o da cercare nel testo vuota | no |
| **Doppioni** | la stessa chiave su più righe, nello stesso PDF o in PDF diversi (spesso legittimo) | no |

Su ogni segnalazione (o su più segnalazioni scelte con la casella a sinistra):
- **Va bene così**: resta nell'elenco ma non conta più tra quelle da vedere (*mostra anche
  quelle che vanno bene* per rivederle);
- clic sulla **pagina** per vederla;
- **Rifai** / **Rifai le pagine**: rifà con Gemini solo quelle pagine; con l'invio *insieme*
  puoi scegliere di rifarle una pagina per richiesta, più preciso sulle pagine difficili;
- **Modifica** porta alla riga tra le righe del CSV; **Elimina** la toglie dal CSV;
- nei **valori vuoti** e nei **caratteri sospetti** il valore si corregge direttamente lì;
  i caratteri sospetti si possono anche **sostituire tutti insieme** (es. `§` → `@`).

**Impostazioni delle verifiche**: copertura (almeno una riga, esattamente una, nessun
controllo), **colonne da cercare nel testo** (vuoto = le colonne chiave; meglio codici e
modelli stampati così come sono, non descrizioni riassunte da Gemini) e, per ogni PDF, le
**pagine dell'elenco di riferimento** (vuoto = le pagine *Indice* della scheda del catalogo).
L'elenco letto da Gemini si può vedere e **correggere a mano** (*Vedi e correggi*: una voce
per riga, `valore | pagina stampata`), o rileggere.

**Righe del CSV**: tutte le righe come finiranno nel CSV, con ricerca, filtro per pagina e
pagine da 50; clic su una cella per correggerla (Invio salva, Esc annulla), × per eliminare la
riga. Le celle corrette sono evidenziate.

**Correzioni**: tutto ciò che hai cambiato, in un posto solo, e sempre reversibile:
- **Sostituisci tutte**: trova → sostituisci in una colonna o in tutte, in un PDF o in tutti.
  È una regola: vale anche per le pagine indicizzate dopo, e non tocca le celle corrette a
  mano;
- **celle corrette a mano** (con il valore letto da Gemini accanto) e **righe eliminate**
  (*Ripristina*).

Le correzioni **non toccano ciò che ha letto Gemini**: si applicano ogni volta che si
generano il CSV e la pagina di ricerca. Se rifai una pagina e Gemini legge un valore diverso,
la correzione fatta a mano su quella riga non si applica più e lo vedi scritto (*non più
applicabile*): non sparisce in silenzio. Dopo ogni correzione le verifiche già eseguite si
rifanno da sole.

### ⑥ Risultati

- il **CSV unico** del progetto e un CSV per ogni PDF (*Scarica*), più le **anomalie** (prima
  gli errori, poi gli avvisi, infine le note di Gemini; clic su una riga per vedere la pagina);
- la **pagina di ricerca** (sotto);
- *Rigenera (senza Gemini)* ricostruisce CSV e pagina di ricerca dai risultati salvati.

CSV e pagina di ricerca contengono già le correzioni del passo ⑤.

I file stanno in `data\exports\<progetto>\`.

---

## 6. La pagina di ricerca

Una pagina HTML con tutti i dati del CSV unico:
- **ricerca libera** su tutte le colonne, tollerante a spazi, punti e trattini: `ab 102 cf`
  trova `AB102CF`, `4520118` trova `4520.118`; con più parole devono esserci tutte, e in
  cima compaiono le righe che contengono la ricerca intera (il codice esatto);
- **filtri** automatici sulle colonne con pochi valori (costruttore, file, cilindri, …);
- clic sulle intestazioni per **ordinare**; risultati a pagine da 100;
- link **"apri p.N"** per aprire il PDF alla pagina da cui viene la riga;
- **Scarica risultati (CSV)**: solo le righe trovate.

Il file si rigenera a ogni indicizzazione o export. Provata con un indice di circa
30.000 righe: si apre in meno di mezzo secondo e cerca in pochi millesimi di secondo. Per
condividerla con altri basta il file `ricerca.html` (i link ai PDF funzionano se si copia
l'intera cartella `data`).

---

## 7. Riga di comando

Tutto il percorso si fa dall'interfaccia. Dalla riga di comando restano alcune operazioni
utili, per esempio per lanciare un'indicizzazione lunga da terminale:

```powershell
docanalyzer doctor                            # verifica che sia tutto pronto
docanalyzer add Catalogo.pdf --folder Motori  # aggiunge PDF alla biblioteca
docanalyzer list                              # cataloghi: cartella, analisi, guida, progetti
docanalyzer remove <catalogo>                 # elimina un catalogo (se nessun progetto lo usa)
docanalyzer project list                      # progetti e pagine indicizzate
docanalyzer project index <progetto>          # indicizza (riusa le pagine della prova)
docanalyzer project export <progetto>         # rigenera i CSV senza chiamare Gemini
docanalyzer project search <progetto>         # apre la pagina di ricerca
```

I progetti si creano solo dall'interfaccia, dalla scheda di un catalogo. I comandi `rag`
riguardano la modalità domande e risposte (RAG), separata dall'indicizzazione:

```powershell
docanalyzer rag describe <catalogo> [--pages 1-20]       # Gemini descrive le pagine, con la guida del catalogo
docanalyzer rag build                                    # indice di ricerca dalle descrizioni (senza Gemini)
docanalyzer rag ask "filtri olio per il motore MX 450?"  # risposta con le fonti (catalogo e pagina)
```

Serve `pip install -e ".[rag]"`. Come l'indicizzazione, la descrizione usa la **guida
all'indicizzazione** del catalogo: conviene analizzare il catalogo prima.

---

## 8. Impostazioni utili (`configs\default.yaml`)

| Impostazione | Default | Quando cambiarla |
|---|---|---|
| `gemini.model` | `gemini-3.6-flash` | se `doctor --online` segnala un modello non disponibile |
| `gemini.requests_per_minute_per_key` | 10 | in base ai limiti del tuo piano |
| `gemini.retry_delay_seconds` | 5 | attesa fissa prima di riprovare dopo un sovraccarico (503) o un errore di rete |
| `gemini.max_wait_minutes` | 10 | oltre questa attesa continua (sovraccarico, quote) il lavoro si ferma |
| `gemini.max_requests_per_minute_total` | (vuoto: adattivo) | il limite al minuto del tuo progetto, se lo conosci |
| `gemini.media_resolution` | (vuoto) | `high` se Gemini legge male testi minuscoli |
| `gemini.thinking_level` | (vuoto) | `low` per estrazioni più veloci ed economiche; verifica con la prova che la qualità regga |
| `render.dpi` | 200 | 250-300 per testo molto piccolo (immagini più pesanti) |
| `indexing.input` | `image+text` | `image` per PDF con testo estratto inaffidabile, `pdf` da provare in alternativa |
| `ui.theme` | `auto` | `light` o `dark` per non seguire il sistema, oppure un tuo tema (un file in `web/static/css/themes/`, vedi la pagina *Stile* in fondo all'elenco dei progetti) |

`indexing.input` decide cosa riceve Gemini per ogni pagina:

- `image+text`: immagine della pagina **più** il testo nativo del PDF. L'immagine dà la
  struttura (tabelle, icone, associazioni), il testo i caratteri esatti dei codici (riduce
  confusioni come 0/O, 8/B, 1/I). Per le scansioni si usa solo l'immagine.
- `image`: solo l'immagine.
- `pdf`: la pagina come PDF di una pagina.

Quale funzioni meglio dipende dai cataloghi: confronta le modalità con la prova sulle stesse
pagine. Cambiare modello o modalità rende da rifare i risultati già ottenuti.

---

## Problemi frequenti

| Problema | Soluzione |
|---|---|
| `Nessuna chiave API Gemini` | Crea `.env` da `.env.example` e inserisci almeno una chiave |
| `Gemini sovraccarico (503, alta richiesta)` | Momentaneo e lato Google, uguale per tutte le chiavi: il programma riprova ogni 5 secondi (`gemini.retry_delay_seconds`) senza far fallire le pagine; se dura più di 10 minuti (`gemini.max_wait_minutes`) si ferma e si riprende rilanciando. Il messaggio compare sotto la barra; *Ferma* interrompe subito |
| `quota giornaliera esaurita` | Aspetta il reset della quota (o usa chiavi di altri progetti) e rilancia: riprende da dove era |
| Molti messaggi "rallento a circa N richieste/minuto" | Normale con chiavi dello stesso progetto; per evitarli imposta `gemini.max_requests_per_minute_total` al limite del progetto |
| Le richieste al giorno finiscono dopo poche pagine | Nel piano gratuito il limite è il numero di richieste, non i token: scegli *Tutte le pagine di un PDF insieme* (una richiesta per PDF) e manda solo le pagine con i dati |
| Con l'invio insieme Gemini rifiuta la richiesta o la quota al minuto non basta | Imposta *Al massimo N pagine per richiesta* (es. 20) |
| Gemini rifiuta l'analisi perché la richiesta è troppo pesante | Il programma non blocca niente in anticipo: scegli meno pagine (o non l'intero PDF) e riprova |
| La risposta di Gemini è *non valida* | Resta in archivio (*vedi la risposta*); riprova, eventualmente con indicazioni più semplici o meno pagine |
| Troppe pagine di fila fallite | Problema generale (nome del modello, chiave non valida): `docanalyzer doctor --online` |
| `la risposta ha superato la lunghezza massima` | Pagina con moltissime righe: riduci le colonne o rendi le altre indicazioni più selettive |
| La prova ha righe inventate, mancanti o sbagliate | Rendi più precisa la riga e le descrizioni delle colonne (① Tabella), correggi o rigenera la guida del catalogo, aggiungi una nota al PDF; poi rifai la prova |
| Un dato del titolo manca nelle righe delle pagine successive | Segna la colonna come *Intestazione* nella tabella |
| Una colonna con il nome del PDF resta vuota | Gemini non riceve il nome del file: toglila, c'è già `FILE_ORIGINE` (e `PAGINA_PDF`) in ogni riga |
| Testo piccolo letto male | Aumenta `render.dpi` o imposta `gemini.media_resolution: high` |
| Vuoi provare senza consumare quota | `$env:DOCANALYZER_FAKE_GEMINI=1` (risposte simulate); per tornare normale chiudi il terminale |
| Errore imprevisto | Rilancia con `$env:DOCANALYZER_DEBUG=1` per vedere i dettagli tecnici |
