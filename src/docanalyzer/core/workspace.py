"""Il *workspace*: la cartella con tutti i dati dell'utente.

Struttura::

    data/
    ├── library/             biblioteca: cartelle, indicazioni personali per Gemini, progetti guidati
    ├── projects/<id>/       progetti: tabella, PDF e prova (vedi projects.py)
    ├── documents/<id>/      un documento: PDF, scheda, analisi, pagine, risultati (documents.py)
    ├── exports/<progetto>/  CSV prodotti, pronti da usare
    └── vector_index/        database vettoriale della modalità RAG

Tutto ciò che appartiene all'utente sta qui: per un backup basta copiare questa
cartella. L'applicazione (codice, configurazione, prompt) resta separata.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path


def slugify(text: str, max_length: int = 60) -> str:
    """Trasforma un testo in un identificatore leggibile e sicuro come nome di file.

    >>> slugify("Catalogo Motori Diesel 2024.pdf")
    'catalogo-motori-diesel-2024-pdf'
    """
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug[:max_length].rstrip("-") or "documento"


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root)

    # --- cartelle principali -------------------------------------------------
    @property
    def documents_dir(self) -> Path:
        return self.root / "documents"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    @property
    def vector_index_dir(self) -> Path:
        return self.root / "vector_index"

    def ensure(self) -> Workspace:
        for d in (self.documents_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)
        return self

