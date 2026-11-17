# Glossario di docanalyzer

Le parole usate nel programma, nell'interfaccia e nella documentazione, con il significato
preciso di ciascuna. Serve a non confondere cose che si somigliano (tag, note, pagine...).

**Legenda dello stato**

- ✅ **esiste oggi** e funziona così (versione 0.3.0, pipeline unica: vedi la
  [roadmap](ROADMAP.md));
- (tolto) parola delle versioni precedenti, spiegata per chi la ritrova.

---

## 1. Il quadro in una figura

```
                 BIBLIOTECA                                    PROGETTO (= una tabella)
   ┌───────────────────────────────────────┐        ┌───────────────────────────────────────────┐
   │ catalogo (PDF) ── scheda               │        │ ① Tabella: riga, colonne (con dati di     │
   │   descrizione, tag, dati presenti,     │        │    intestazione), altre indicazioni       │
   │   collezioni di pagine,                │        │ ② PDF e pagine: per PDF pagine e guida    │
   │   guida all'indicizzazione             │ copia  │    (copiate), note                        │
   │                                        │ ─────► │ ③ Prova ✨ su poche pagine                │
   │ ✨ analisi → proposta: scheda + guida  │        │ ④ Indicizzazione ✨                       │
   │ ✨ crea progetto (dalla scheda):       │ crea   │ ⑤ Verifiche (✨ elenco di riferimento)     │
   │    Tabella + cataloghi simili  ────────┼──────► │    e correzioni                           │
   │                                        │        │ ⑥ Risultati: CSV unico, anomalie, ricerca │
   └───────────────────────────────────────┘        └───────────────────────────────────────────┘
   ✨ = passaggio che usa Gemini (sempre con conferma, il prompt è visibile prima dell'invio)
```

In breve: **la biblioteca serve a capire i PDF** (a te e a Gemini: la guida); **il progetto
decide la struttura del CSV** (la Tabella) ed è l'unico che indicizza.

---

## 2. Termini generali

**PDF / catalogo / documento** ✅
La stessa cosa vista da punti diversi: un file PDF caricato nel programma. Nell'interfaccia si
dice *catalogo* (perché i casi d'uso sono cataloghi tecnici), nel codice *documento*. Ha un
**id** leggibile ricavato dal nome del file (`catalogo-motori-diesel`) e un'**impronta del
contenuto** (SHA-256) che permette di riconoscere lo stesso PDF anche con un altro nome: un PDF
non viene mai caricato due volte.

**Workspace** ✅
La cartella `data/` con tutti i dati dell'utente (PDF, schede, progetti, risultati). Per un
backup basta copiarla.

**Gemini** ✅
Il modello di Google che legge le pagine. Ogni chiamata è una **richiesta**; si paga in
**token** e ha dei limiti (**quote**) per minuto e per giorno. In **modalità simulata** il
programma finge le risposte, per provare senza chiavi e senza costi.

**Lavoro** ✅
Un'operazione lunga che chiama Gemini (analisi, guida, ricerca dei cataloghi simili, prova,
indicizzazione). Mostra l'avanzamento e i **messaggi** (sovraccarico, quote), si può
**fermare**, e intanto, volendo, si può giocare a **Gemini Snake** (nascosto finché non lo si apre).

**Nessun limite preventivo** ✅
Il programma non impedisce richieste grandi (tante pagine, PDF pesanti, molti cataloghi,
indicazioni lunghe): prima dell'invio dice quante richieste partiranno, quanto pesano e quanto
dureranno (stima indicativa). Se Gemini rifiuta, l'errore viene mostrato.

---

## 3. La biblioteca: capire i PDF

**Biblioteca** ✅
L'elenco di tutti i PDF, indipendente dai progetti. I PDF *vivono* qui: i progetti li usano
ma non li possiedono. Togliere un PDF da un progetto o eliminare un progetto non cancella il
PDF; un PDF si elimina dalla biblioteca solo se nessun progetto lo usa.

**Cartella** ✅
Dove sta un catalogo nella biblioteca (es. `Motori/Diesel`). Ogni catalogo sta in **una
sola** cartella. Serve solo a tenere ordine.

**Tag del catalogo** ✅
Etichette **libere** e **multiple** (es. `motori`, `diesel`, `da studiare`). Servono a
filtrare e ritrovare i cataloghi in tutte le cartelle. *Non confonderli con i tag di pagina.*

**Scheda (del catalogo)** ✅
La pagina di un catalogo con tutto ciò che si sa di lui: titolo, cartella, tag, descrizione,
dati presenti, collezioni di pagine, guida all'indicizzazione, analisi archiviate, progetti in
cui è usato. Da qui si crea un progetto.

**Descrizione (del catalogo)** ✅
Testo libero, **per le persone**, su cosa contiene il PDF e com'è organizzato (marca,
prodotti, sezioni, particolarità). Scritta a mano o proposta dall'analisi. Serve anche a
trovare i cataloghi simili. *Non entra nelle regole* (vedi *guida* e *note*).

**Dati presenti** ✅
L'**inventario** dei dati che si potrebbero estrarre in una tabella da quel catalogo (motore,
versione, componente, pistone...), **senza ordine**, ciascuno con una descrizione facoltativa
(unità, formato, dove si trova). Non sono una decisione di indicizzazione: le **colonne** le
sceglie il progetto. Servono a capire il PDF, a scrivere la Tabella con un clic e a trovare i
cataloghi simili.

**Catalogo analizzato** ✅
Un catalogo con almeno una descrizione o dei dati presenti. È tra questi che Gemini cerca i
cataloghi simili quando crei un progetto. (Prima si diceva *catalogo elaborato*.)

**Collezione di pagine** ✅
Un **intervallo continuo** di pagine con **un tag di pagina** e un **commento** facoltativo
(es. *pagine 9-250, Dati, "tabelle codici per motore"*). Una pagina può stare in più collezioni.
Può essere scritta a mano, proposta da Gemini o **dedotta** da Gemini dall'indice senza vedere
quelle pagine. Insieme le collezioni sono la **mappa** del catalogo.

**Tag di pagina** ✅
L'elenco **fisso** di etichette per le collezioni (fisso perché il programma le usa): *dati,
pagina d'esempio, copertina, indice, introduzione, legenda/simboli, tabelle tecniche,
disegni/immagini, avvertenze/note, pubblicità/vuota, altro*. Le pagine **dati** sono quelle da
indicizzare (di default nei progetti); le **pagine d'esempio** vengono provate per prime.

**Pagine chiave** ✅
Le pagine che spiegano il catalogo: quelle segnate *indice*, *legenda* e *pagina d'esempio*,
più la prima pagina di ogni collezione *dati*. Gemini le riceve per scrivere la guida.

**Visualizzatore** ✅
Nella scheda: miniature a sinistra, pagina grande a destra, frecce per sfogliare,
*Apri il PDF ↗* per aprire l'originale nel browser alla pagina mostrata. Serve a creare le
collezioni.

**Guida all'indicizzazione** ✅
Testo (Markdown), **per Gemini**, che spiega come leggere una **pagina isolata** di quel
catalogo: struttura e sezioni, com'è fatta una pagina di dati, convenzioni e sigle, e
soprattutto cosa non si capisce da una pagina da sola (intestazioni non ripetute, tabelle che
continuano, celle vuote con un significato). **Non decide le colonne**, che cambiano da
progetto a progetto. La scrive Gemini con l'analisi, si può correggere a mano e **rigenerare
dalla scheda attuale**. Accompagna ogni pagina del catalogo quando un progetto lo indicizza;
il progetto ne usa una **copia**. (Prende il posto del *primer* di progetto.)

**Analisi (con Gemini)** ✅
Due richieste in fila sullo stesso catalogo:
1. la **scheda**: Gemini guarda le pagine scelte (o il PDF intero) e propone descrizione, tag,
   dati presenti, collezioni, osservazioni;
2. la **guida**: con quella scheda, le stesse pagine e le pagine chiave, Gemini scrive la guida
   all'indicizzazione.

Il risultato è una **proposta**. Se la seconda richiesta non riesce, la scheda proposta resta.

**Proposta** ✅
Il risultato di un'analisi (o di una rigenerazione della guida): **non viene applicato da
solo**. Si sceglie voce per voce cosa copiare nella scheda, e la guida si può correggere prima
di applicarla. Resta nell'**archivio delle analisi** con uno stato: *da rivedere*,
*applicata*, *scartata* o *non valida*.

---

## 4. Il progetto: decidere ed estrarre

**Progetto** ✅
**Una tabella**: uno o più PDF con struttura compatibile, estratti con le **stesse colonne**,
che producono **un CSV unico**. Si crea **solo dalla scheda di un catalogo**. Lo stesso PDF può
stare in più progetti (per esempio uno "per motore" e uno "per componente"): i risultati
restano separati.

**Creare un progetto** ✅
Dalla scheda di un catalogo: scrivi la **Tabella**, poi crei il progetto con il solo catalogo
di partenza, oppure Gemini cerca i **cataloghi simili** tra tutti i cataloghi analizzati e
risponde con un **report**: quali colonne copre il catalogo di partenza e con quali sezioni, e
i **candidati** (*compatibile* o *parziale*, con motivo, colonne coperte e sezioni con i dati).
Scegli candidati e sezioni e **crei il progetto**. Gemini **non cambia la tabella**. (Prima si
chiamava *progetto guidato*, e Gemini proponeva anche la tabella.)

**Passi del progetto** ✅
Il percorso di ogni progetto: **① Tabella** (cosa vuoi), **② PDF e pagine** (da dove e come
leggerli), **③ Prova**, **④ Indicizzazione**, **⑤ Verifiche**, **⑥ Risultati**. Ogni passo ha uno stato
(*fatto*, *in corso*, *da rivedere*, *da fare*, *facoltativo*) e il progetto indica sempre il
**prossimo passo**.

**Tabella** ✅
Cosa deve uscire dal progetto, decisa e scritta dall'utente: **nome**, **descrizione** (a cosa
serve l'indice), **cosa rappresenta una riga**, **colonne** (nome, descrizione, *dato di
intestazione*, *chiave*), **altre indicazioni**. È la stessa per tutti i PDF del progetto e si modifica
al passo ①. Accanto alle colonne vedi la **copertura** nei PDF del progetto (es. *pistone: 1
PDF su 3*), ricavata dai loro dati presenti. (Prima si chiamava anche *impostazioni globali*.)

**Riga ("cosa rappresenta una riga")** ✅
La scelta più importante: la **granularità** della tabella (una riga per motore, per codice,
per coppia codice ricambio/codice originale...). Due tabelle con le stesse colonne ma righe diverse non si accorpano.

**Colonna** ✅
Nome + descrizione (cosa contiene, formato), nell'ordine del CSV.

**Colonne aggiunte dal programma** ✅
`PAGINA_PDF` (pagina del PDF da cui viene la riga) e `FILE_ORIGINE` (nome del file PDF così
com'è): ci sono in ogni riga, in fondo, e la Tabella le mostra sempre. Non le compila Gemini,
che non riceve il nome del file; i due nomi sono riservati.

**Dato di intestazione** ✅
Una colonna segnata *Intestazione*: un dato che compare una volta sola nella pagina o nella
sezione (es. il nome del motore nel titolo) e vale per ogni riga anche se non è ripetuto. Con
il **contesto ereditato** passa anche alle pagine successive dello stesso PDF che non lo
riportano. (Nel codice: colonna di contesto, `context: true`.)

**PDF del progetto** ✅
I PDF che il progetto usa, ciascuno con le sue **impostazioni per PDF**. Il nome porta alla sua
**scheda della biblioteca**. Altri PDF si aggiungono con *Aggiungi PDF dalla biblioteca…*.

**Impostazioni per PDF (nel progetto)** ✅
Valgono solo dentro quel progetto:
- **pagine da indicizzare**: si scelgono **spuntando le collezioni** della scheda (di default
  quelle *dati*) e vengono **copiate**; oppure si scrivono a mano (vuoto = tutto il PDF);
- **guida**: la **copia** della guida all'indicizzazione della scheda;
- **note per il PDF**: istruzioni di estrazione in più, solo per lui (es. "in questo catalogo
  la versione è sotto il nome del motore").

**Note per il PDF** vs **guida** vs **descrizione** ✅
La *descrizione* (biblioteca) dice **com'è** il PDF, alle persone; la *guida* (biblioteca,
copiata nel progetto) dice a Gemini **come leggerlo**, in qualsiasi progetto; le *note*
(progetto) dicono **cosa fare di diverso** con quel PDF in quel progetto. Guida e note entrano
nelle regole, la descrizione no.

**Regole (di estrazione)** ✅
Tutto ciò che determina il risultato dell'estrazione di un PDF, **composto dal programma**:
la Tabella, le note e le pagine di quel PDF e la sua guida, più il modello di Gemini e il modo
di input. L'utente non le scrive come file: le decide nei passi ① e ②. (Prima erano *primer* e
*specifica* YAML scritti da Gemini.)

**Impronta (delle regole)** ✅
Un riassunto delle regole salvato insieme ai risultati. Se le regole cambiano, i risultati di
quel PDF sono **vecchi** (*regole cambiate: da rifare*) e il programma rifà **solo** i PDF
interessati: la Tabella riguarda tutti, guida e note solo il loro PDF.

**Copie e Aggiorna dalla biblioteca** ✅
Pagine da indicizzare e guida sono copie: se nella biblioteca cambiano, il progetto non cambia
da solo ma lo segnala (*La biblioteca è cambiata*), e **Aggiorna dalla biblioteca** le ricopia.

**Estratto PDF** ✅
Un PDF temporaneo con le sole pagine scelte, mandato a Gemini al posto dell'originale
(nell'analisi e nella guida). Nel prompt c'è la **corrispondenza delle pagine** (pagina 3
dell'estratto = pagina 45 dell'originale); sulle pagine non viene stampato nulla.

**Prova** ✅
Il passo ③: l'estrazione con le **regole vere** su poche **pagine da indicizzare** per
catalogo (4 di default, numero modificabile; prima le pagine d'esempio, poi distribuite;
*Altre pagine* per pagine non ancora provate), sui PDF scelti. Mostra le righe che usciranno.
Se le regole cambiano dopo, la prova di quel PDF è *superata*; se no, le pagine provate
**contano già come indicizzate**.

**Indicizzazione** ✅
L'estrazione di tutte le pagine da indicizzare di tutti i PDF del progetto, secondo la
**modalità di invio**. Gemini riceve la Tabella, la guida e le note del PDF. Il lavoro è
**riprendibile**: le pagine fatte (anche dalla prova) non si rifanno.

**Modalità di invio** ✅
Come le pagine arrivano a Gemini, nella prova e nell'indicizzazione (scelta per progetto):
- **una pagina per richiesta**: la pagina come **immagine + testo nativo** (modo di input
  predefinito), una richiesta per pagina;
- **tutte le pagine di un PDF insieme**: un **estratto ritagliato dal PDF originale** con le
  sue pagine da indicizzare, una richiesta per PDF (i PDF non si mescolano); facoltativo un
  massimo di pagine per richiesta. Se la risposta è troppo lunga il programma divide da solo.

Non cambia le regole: i risultati sono sempre per pagina.

**Colonna chiave** ✅
Una colonna che identifica una riga (es. il motore); con più colonne chiave conta la loro
combinazione. Non cambia l'estrazione: serve alle **verifiche** (elenco di riferimento,
doppioni, valori vuoti, contenuto sulla pagina).

**Verifiche** ✅
Il passo ⑤: controlli sui risultati dell'indicizzazione, per PDF. *Copertura delle pagine*,
*contenuto sulla pagina*, *elenco di riferimento* (l'unica con Gemini), *caratteri sospetti*,
*valori vuoti*, *doppioni*. Ogni verifica produce **segnalazioni**; una segnalazione si può
marcare **va bene così** (resta, ma non conta più). Una verifica è **da rieseguire**
(*superata*) quando dopo di lei cambiano i risultati, le correzioni o le impostazioni di quel
PDF. La prova non si verifica.

**Elenco di riferimento** ✅
Le pagine di un catalogo che elencano tutte le voci (indice, sommario, listino…): Gemini le
trascrive (colonne chiave e pagina stampata) e il programma le confronta con il CSV. Lo
**scarto** è la differenza costante tra pagina stampata e pagina del PDF. L'elenco letto si può
correggere a mano.

**Correzioni** ✅
Ciò che l'utente cambia nel CSV al passo ⑤, senza toccare ciò che ha letto Gemini:
**sostituzioni** (trova → sostituisci in una colonna o in tutte, in un PDF o in tutti; valgono
anche per le pagine indicizzate dopo), **celle corrette** e **righe eliminate**. Si applicano a
ogni generazione del CSV e si possono togliere. Una correzione di cella o di riga è **non più
applicabile** se, rifatta la pagina, Gemini legge un valore diverso.

**Risultati** ✅
- **CSV unico** del progetto (con le correzioni), con la colonna del file d'origine e della pagina;
- **CSV per PDF**;
- **anomalie**: righe con problemi (colonne vuote, pagine non riuscite, note di Gemini...);
- **pagina di ricerca**: un file HTML autonomo per cercare nel CSV unico.

Nella scheda di ogni PDF, **Nei progetti**, si vede in quali progetti è usato e come procede la
sua indicizzazione in ciascuno, con il CSV di quel PDF da scaricare.

**Parole tolte** (versioni precedenti)
*Configurazione guidata* / *Regole* come passo (Gemini scriveva primer e specifica a
versioni), *primer di progetto*, *specifica*, *obiettivo*, *CSV d'esempio* o *di riferimento*,
*raggruppamento*, *progetto dalla selezione*, *primer* (anche la modalità RAG usa la guida del catalogo).

---

## 5. Dalla biblioteca al progetto ✅

Regola: **ciò che descrive si legge in diretta, ciò che comanda si copia.**

| Informazione della biblioteca | Come passa al progetto | Dove serve |
|---|---|---|
| descrizione del PDF | in diretta | ricerca dei cataloghi simili |
| dati presenti | in diretta | ricerca dei cataloghi simili; copertura delle colonne; colonne con un clic |
| collezioni (mappa delle pagine) | in diretta | scelta delle pagine; campione della prova |
| pagine da indicizzare (collezioni scelte) | **copia** | regole di estrazione di quel PDF |
| guida all'indicizzazione | **copia** | regole di estrazione di quel PDF |
| tag e cartella | in diretta | interfaccia |

Le informazioni descrittive non entrano nelle regole, quindi correggerle non rende vecchi i
risultati. Pagine e guida invece sì: *Aggiorna dalla biblioteca* mostra le differenze e dice
quali PDF andrebbero rifatti. Il progetto **non scrive** nella biblioteca.

---

## 6. Parole che si somigliano

**I "tag"** — due cose diverse:

| Termine | Dove | Liberi? | A cosa servono |
|---|---|---|---|
| tag del catalogo | scheda | sì | filtrare e ritrovare i cataloghi |
| tag di pagina | collezioni | no, elenco fisso | dire cosa c'è in un intervallo di pagine |

**I testi liberi** — chi li scrive e a cosa servono:

| Termine | Dove | Descrive o comanda? | Entra nelle regole? |
|---|---|---|---|
| descrizione | scheda del catalogo | descrive il PDF, alle persone | no |
| commento | collezione di pagine | descrive quelle pagine | no |
| osservazioni | analisi (Gemini) | dubbi e note di Gemini | no |
| guida all'indicizzazione | scheda del catalogo (copia nel progetto) | spiega a Gemini come leggere il PDF | **sì** |
| descrizione del progetto | Tabella | a cosa serve l'indice | **sì** |
| altre indicazioni | Tabella | regole per tutti i PDF | **sì** |
| note per il PDF | progetto, passo ② | regole in più per quel PDF | **sì** |
| indicazioni per Gemini | analisi, guida, cataloghi simili | dicono a Gemini cosa cercare o scrivere | no |

**Le "pagine"** — selezioni diverse:

| Selezione | Dove si sceglie | A cosa serve |
|---|---|---|
| pagine da inviare | analisi (scheda) | cosa guarda Gemini per proporre la scheda (e la guida) |
| pagine chiave | dalle collezioni (automatiche) | aggiunte per scrivere la guida |
| pagine d'esempio | collezione *pagina d'esempio* | pagine rappresentative: chiave per la guida, prime nella prova |
| pagine della prova | passo ③ | dove si prova l'estrazione con le regole vere |
| pagine da indicizzare | progetto, per PDF (dalle collezioni *dati*) | cosa viene estratto davvero |

**I dati e le colonne**:

| Termine | Dove | Conta nell'indicizzazione? |
|---|---|---|
| dati presenti | scheda del catalogo | no: inventario, serve a capire e a trovare i simili |
| colonne della Tabella | progetto, passo ① | **sì**, sono le colonne del CSV |

**Le "proposte" di Gemini** — niente viene applicato da solo:

| Passaggio | Cosa propone | Dove si decide |
|---|---|---|
| analisi | una scheda e una guida per un catalogo | proposta nella scheda, voce per voce |
| rigenera la guida | una nuova guida | proposta nella scheda |
| cataloghi simili | candidati e sezioni con i dati | report, candidato per candidato |

---

## 7. Regole di sicurezza dei prompt ✅

- **Indicazioni** (modificabili dall'utente) e **cornice** (fissa, scritta dal programma) sono
  separate: la cornice contiene il **formato della risposta** e prevale sulle indicazioni.
- Ogni risposta strutturata viene **convalidata in modo rigoroso**: se la struttura non torna
  (campi mancanti o in più, tipi sbagliati, valori o codici inesistenti, guida vuota) è **non
  valida**, non viene usata e resta in archivio con la risposta originale.
- Dentro una risposta valida, le singole voci inutilizzabili (es. pagine fuori dal documento,
  colonne che non sono della tabella) vengono scartate e **segnalate**.
