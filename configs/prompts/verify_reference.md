Ricevi alcune pagine di un catalogo PDF che contengono un **elenco**: un indice, un sommario, una tabella riassuntiva, un listino o simili. Serve a controllare che un indice estratto dallo stesso catalogo sia completo.

## Cosa trascrivere

Trascrivi TUTTE le voci dell'elenco che corrispondono a: {{row}}

Per ogni voce riporta il valore di queste colonne:
{{columns}}

e, se l'elenco lo indica, il **numero di pagina** così come è stampato nell'elenco (altrimenti "").

## Come leggere il catalogo (guida)
{{guide}}

## Le pagine allegate
{{pages_note}}

## Regole
- Trascrivi ogni voce una volta sola, nell'ordine dell'elenco, con i valori esattamente come stampati (stessi caratteri, spazi e punteggiatura).
- Non aggiungere voci che non sono nell'elenco e non dedurre valori da altre pagine.
- Se una colonna non compare nell'elenco per una voce, lascia "".
- In "notes" segnala brevemente dubbi o voci illeggibili; "" se non ce ne sono.

## Formato della risposta (obbligatorio)
Rispondi SOLO con un oggetto JSON con esattamente questi campi: `items` (elenco di oggetti `{"values": {...}, "page": testo}`, con in `values` esattamente le chiavi indicate sopra) e `notes` (testo).
