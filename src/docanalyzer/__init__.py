"""docanalyzer — elaborazione vision-first di documenti PDF con Gemini.

Il pacchetto offre due modalità d'uso, che condividono la stessa infrastruttura
(workspace, rendering delle pagine, client Gemini):

- **indicizzazione**: biblioteca di cataloghi, analisi con Gemini (scheda e guida
  all'indicizzazione) e progetti che estraggono dalle pagine le righe della Tabella decisa
  dall'utente, in un CSV unico;
- **RAG**: descrive le pagine, le indicizza in un database vettoriale e risponde
  a domande in linguaggio naturale.
"""

__version__ = "0.5.0"
