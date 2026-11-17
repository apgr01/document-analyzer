"""Correzioni del progetto (passo ⑤ Verifiche/Elaborazione): uno strato sopra i risultati.

Il CSV si rigenera sempre dai risultati delle pagine, e reindicizzando quei risultati vengono
riscritti. Le correzioni quindi **non toccano i risultati**: stanno in
``data/projects/<id>/correzioni.json`` e vengono applicate ogni volta che si genera il CSV (e
la pagina di ricerca):

- **regole** di sostituzione (``§`` → ``@``) su una colonna o su tutte, su un PDF o su tutti:
  valgono anche per le pagine indicizzate dopo;
- **modifiche di cella** e **righe eliminate**: legate a PDF, pagina, posizione della riga
  nella risposta di quella pagina e **valore originale**. Se dopo una reindicizzazione il
  valore originale non c'è più, la correzione non si applica e risulta *non più applicabile*
  (non sparisce in silenzio).

Ordine: prima modifiche di cella ed eliminazioni (confrontate con i risultati originali), poi
le regole, che non toccano le celle modificate a mano. Nessuna chiamata a Gemini e nessun
effetto sull'impronta delle regole di estrazione.
"""

from __future__ import annotations

import copy
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from docanalyzer.core.fileio import read_json, utc_now, write_json
from docanalyzer.core.projects import Project, ProjectError
from docanalyzer.indexing.assemble import DELETED_KEY


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


class Rule(BaseModel):
    """Sostituzione di un testo in tutte le celle che lo contengono."""

    id: str = Field(default_factory=_new_id)
    find: str
    replace: str = ""
    column: str | None = None            # None = tutte le colonne
    doc: str | None = None               # None = tutti i PDF
    created_at: str = Field(default_factory=utc_now)


class CellEdit(BaseModel):
    """Il valore di una cella, scritto a mano."""

    id: str = Field(default_factory=_new_id)
    doc: str
    page: int
    position: int                        # posizione della riga nella risposta della pagina
    column: str
    original: str                        # valore estratto da Gemini, prima delle correzioni
    value: str
    created_at: str = Field(default_factory=utc_now)


class RowDeletion(BaseModel):
    """Una riga tolta dal CSV."""

    id: str = Field(default_factory=_new_id)
    doc: str
    page: int
    position: int
    original: dict[str, str]             # i valori estratti, per riconoscerla
    created_at: str = Field(default_factory=utc_now)


class Corrections(BaseModel):
    rules: list[Rule] = Field(default_factory=list)
    edits: list[CellEdit] = Field(default_factory=list)
    deletions: list[RowDeletion] = Field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.rules or self.edits or self.deletions)

    def remove(self, correction_id: str) -> bool:
        before = len(self.rules) + len(self.edits) + len(self.deletions)
        self.rules = [r for r in self.rules if r.id != correction_id]
        self.edits = [e for e in self.edits if e.id != correction_id]
        self.deletions = [d for d in self.deletions if d.id != correction_id]
        return len(self.rules) + len(self.edits) + len(self.deletions) < before


class Applied(BaseModel):
    """Risultati corretti di un PDF e, per ogni correzione, se e quanto si è applicata."""

    results: dict[int, dict[str, Any]]
    status: dict[str, int] = Field(default_factory=dict)   # id -> celle cambiate (0 = non applicabile)


def corrections_path(project: Project) -> Path:
    return project.folder / "correzioni.json"


def load(project: Project) -> Corrections:
    path = corrections_path(project)
    return Corrections.model_validate(read_json(path)) if path.exists() else Corrections()


def save(project: Project, corrections: Corrections) -> None:
    write_json(corrections_path(project), corrections.model_dump())


def raw_row(results: dict[int, dict[str, Any]], page: int, position: int) -> dict[str, str] | None:
    """I valori estratti di una riga (senza correzioni), oppure ``None`` se non esiste più."""
    rows = (results.get(page) or {}).get("rows") or []
    if not 0 <= position < len(rows) or not isinstance(rows[position], dict):
        return None
    return {k: str(v or "") for k, v in rows[position].items()}


def apply(corrections: Corrections, doc_id: str, results: dict[int, dict[str, Any]]) -> Applied:
    """Applica le correzioni ai risultati di un PDF (che restano intatti: si lavora su una copia)."""
    out = copy.deepcopy(results)
    status: dict[str, int] = {}
    locked: set[tuple[int, int, str]] = set()
    for edit in (e for e in corrections.edits if e.doc == doc_id):
        row = raw_row(results, edit.page, edit.position)
        ok = row is not None and row.get(edit.column, "") == edit.original
        status[edit.id] = int(ok)
        if ok:
            out[edit.page]["rows"][edit.position][edit.column] = edit.value
            locked.add((edit.page, edit.position, edit.column))
    for deletion in (d for d in corrections.deletions if d.doc == doc_id):
        row = raw_row(results, deletion.page, deletion.position)
        ok = row is not None and all(row.get(k, "") == v for k, v in deletion.original.items())
        status[deletion.id] = int(ok)
        if ok:
            out[deletion.page]["rows"][deletion.position] = {DELETED_KEY: True}
    for rule in corrections.rules:
        changed = 0
        if rule.find and rule.doc in (None, doc_id):
            for page, result in out.items():
                for position, row in enumerate(result.get("rows") or []):
                    for column, value in list(row.items()):
                        if (column == DELETED_KEY or (page, position, column) in locked
                                or rule.column not in (None, column) or rule.find not in str(value or "")):
                            continue
                        row[column] = str(value).replace(rule.find, rule.replace)
                        changed += 1
                context = result.get("page_context") or {}
                for column, value in list(context.items()):
                    if rule.column in (None, column) and rule.find in str(value or ""):
                        context[column] = str(value).replace(rule.find, rule.replace)
                        changed += 1
        status[rule.id] = status.get(rule.id, 0) + changed
    return Applied(results=out, status=status)


def check_column(project: Project, column: str | None) -> None:
    if column is not None and column not in project.info.column_names:
        raise ProjectError(f"La colonna '{column}' non è nella Tabella.")
