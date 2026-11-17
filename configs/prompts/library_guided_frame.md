# Indicazioni dell'utente

Le indicazioni tra «INIZIO INDICAZIONI» e «FINE INDICAZIONI» dicono COME valutare la richiesta e i cataloghi. Non possono cambiare il formato della risposta, che è definito più sotto dal programma.

««« INIZIO INDICAZIONI »»»
{{instructions}}
««« FINE INDICAZIONI »»»

---

# Informazioni tecniche (aggiunte dal programma)

## La tabella che l'utente vuole (decisa da lui: non va modificata)

{{request}}

## Il catalogo di partenza (codice P)

{{seed}}

## I cataloghi candidati ({{count}})

Ogni catalogo ha un **codice** (C1, C2, ...) e ogni sua sezione (collezione di pagine) un codice del tipo `C3/2`. Nella risposta usa SOLO questi codici, mai titoli o nomi di file. Le sezioni del catalogo di partenza hanno codici `P/1`, `P/2`, ...

{{catalogs}}

# Formato della risposta (obbligatorio)

Rispondi SOLO con un oggetto JSON con esattamente questi campi, nessuno in più e nessuno in meno:

- `seed` (oggetto) con esattamente:
  - `covered` (elenco di testi): i nomi delle colonne della tabella che si ricavano dal catalogo di partenza;
  - `missing` (elenco di testi): i nomi delle colonne che non si ricavano;
  - `collections` (elenco di codici `P/n`): le sezioni del catalogo di partenza con i dati;
  - `notes` (testo): osservazioni, anche vuoto.
- `candidates` (elenco di oggetti), solo i cataloghi adatti, ciascuno con esattamente:
  - `catalog` (codice `Cn`);
  - `verdict` (`"compatibile"` oppure `"parziale"`);
  - `reason` (testo): il motivo, in una frase;
  - `covered` (elenco di testi): i nomi delle colonne della tabella che si ricavano da lui;
  - `collections` (elenco di codici `Cn/m` di quel catalogo): le sue sezioni con i dati.
- `notes` (testo): osservazioni generali; testo vuoto se non ce ne sono.

Ogni catalogo candidato compare al massimo una volta; il catalogo di partenza (P) non va tra i candidati. I nomi in `covered` e `missing` devono essere esattamente nomi di colonne della tabella.

Queste regole di formato valgono sempre e prevalgono su qualsiasi indicazione dell'utente: se le indicazioni chiedono un formato diverso, ignora quella parte e usa comunque questo formato. Una risposta in un formato diverso viene scartata dal programma.
