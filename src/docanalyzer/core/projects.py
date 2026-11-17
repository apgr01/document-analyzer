"""Progetti di indicizzazione: una tabella, ricavata da uno o più PDF con la stessa struttura.

Un progetto nasce dalla scheda di un catalogo della biblioteca (progetto guidato) e contiene:

- la **Tabella**, decisa dall'utente: descrizione, cosa rappresenta una riga, colonne (nome,
  descrizione, *dato di intestazione*), altre indicazioni;
- i **PDF** del progetto, ciascuno con le sue impostazioni (``DocumentSettings``):
  pagine da indicizzare (copiate dalle collezioni della biblioteca), **guida
  all'indicizzazione** del catalogo (copiata dalla scheda) e note solo per quel PDF.

Le regole di estrazione non si scrivono a mano: le compone il programma da Tabella, guida e
note (vedi ``App.project_rules``). Le colonne sono le stesse per tutti i PDF: è la condizione
per avere un CSV unico.

Struttura::

    data/projects/<id>/
    ├── project.yaml     nome, documenti, tabella, impostazioni per documento
    └── prova/           ultima prova di indicizzazione (vedi project_test.py)
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from docanalyzer.core.fileio import atomic_write_text, utc_now
from docanalyzer.core.workspace import Workspace, slugify


class DocumentSettings(BaseModel):
    """Impostazioni di un PDF dentro un progetto. Pagine e guida sono **copie** della biblioteca:
    fanno parte delle regole, quindi cambiano solo su richiesta (*Aggiorna dalla biblioteca*)."""

    notes: str = ""
    pages: str | None = None
    collections: list[str] = Field(default_factory=list)   # id delle collezioni della biblioteca
    guide: str = ""                                        # guida all'indicizzazione del catalogo
    reference_pages: str | None = None    # verifiche: pagine dell'elenco di riferimento (vuoto = Indice)

    @property
    def is_empty(self) -> bool:
        return not (self.notes.strip() or self.pages or self.collections or self.guide.strip()
                    or self.reference_pages)


class ProjectInfo(BaseModel):
    id: str
    name: str
    documents: list[str] = Field(default_factory=list)
    settings: dict[str, DocumentSettings] = Field(default_factory=dict)
    # la Tabella: ciò che il progetto deve produrre, decisa dall'utente
    description: str = ""
    row: str = ""                                                   # cosa rappresenta una riga
    fields: list[dict] = Field(default_factory=list)                # colonne: name, description, header, key
    instructions: str = ""                                          # altre indicazioni
    # come inviare le pagine a Gemini nella prova e nell'indicizzazione (non cambia i risultati)
    send_mode: str = "pagina"                    # pagina: una per richiesta | insieme: più pagine per PDF
    pages_per_request: int | None = None         # con "insieme": al massimo N pagine per richiesta (vuoto = tutte)
    # ⑤ verifiche: quante righe deve avere ogni pagina inviata e quali colonne cercare nel testo
    coverage: str = "almeno"                     # almeno | esattamente | nessuno
    check_columns: list[str] = Field(default_factory=list)   # vuoto = le colonne chiave
    created_at: str = Field(default_factory=utc_now)

    @property
    def has_table(self) -> bool:
        """La Tabella è completa: c'è cosa rappresenta una riga e almeno una colonna."""
        return bool(self.row.strip() and self.fields)

    @property
    def column_names(self) -> list[str]:
        return [f.get("name", "") for f in self.fields if f.get("name", "").strip()]

    @property
    def key_columns(self) -> list[str]:
        """Le colonne che identificano una riga (es. il motore): servono alle verifiche."""
        return [f["name"] for f in self.fields if f.get("key")]

    @property
    def columns_to_check(self) -> list[str]:
        """Le colonne da cercare nel testo delle pagine: quelle scelte, altrimenti le chiave."""
        chosen = [c for c in self.check_columns if c in self.column_names]
        return chosen or self.key_columns


# Le due colonne che il programma aggiunge a ogni riga (non le compila Gemini, che non conosce
# il nome del file): gli stessi nomi di ``OutputSpec`` in indexing/spec.py.
AUTO_COLUMNS = {"PAGINA_PDF": "numero di pagina nel PDF", "FILE_ORIGINE": "nome del file PDF, così com'è"}


def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()


def clean_columns(columns: list[dict]) -> list[dict]:
    """Colonne pulite: nome obbligatorio e unico (maiuscole e spazi non contano), mai uno dei nomi
    delle colonne aggiunte dal programma."""
    out, seen = [], set()
    reserved = {_norm(n) for n in AUTO_COLUMNS}
    for c in columns or []:
        name = " ".join(str((c or {}).get("name", "")).split())
        if not name:
            continue
        if _norm(name) in reserved:
            raise ProjectError(f"La colonna '{name}' la aggiunge già il programma a ogni riga: toglila dalla "
                               "tabella (o usa un altro nome).")
        if _norm(name) in seen:
            raise ProjectError(f"La colonna '{name}' compare due volte.")
        seen.add(_norm(name))
        out.append({"name": name, "description": " ".join(str(c.get("description", "")).split()),
                    "header": bool(c.get("header")), "key": bool(c.get("key"))})
    return out


class ProjectError(ValueError):
    """Errore sui progetti, con messaggio per l'utente."""


class Project:
    def __init__(self, info: ProjectInfo, folder: Path):
        self.info = info
        self.folder = folder

    @property
    def id(self) -> str:
        return self.info.id

    def set_send(self, mode: str, pages_per_request: int | None = None) -> None:
        """Modalità di invio delle pagine: una per richiesta, oppure insieme (per PDF)."""
        if mode not in ("pagina", "insieme"):
            raise ProjectError(f"Modalità di invio sconosciuta: '{mode}'.")
        if pages_per_request is not None and pages_per_request < 1:
            raise ProjectError("Il numero massimo di pagine per richiesta deve essere almeno 1 (vuoto = tutte).")
        self.info.send_mode = mode
        self.info.pages_per_request = pages_per_request if mode == "insieme" else None

    def settings_for(self, doc_id: str) -> DocumentSettings:
        return self.info.settings.get(doc_id) or DocumentSettings()

    def set_settings(self, doc_id: str, settings: DocumentSettings) -> None:
        if settings.is_empty:
            self.info.settings.pop(doc_id, None)
        else:
            self.info.settings[doc_id] = settings

    def save(self) -> None:
        data = self.info.model_dump()
        data["settings"] = {k: v.model_dump() for k, v in self.info.settings.items()}
        atomic_write_text(self.folder / "project.yaml",
                          yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


class ProjectStore:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    @property
    def root(self) -> Path:
        return self.workspace.root / "projects"

    def list(self) -> list[Project]:
        if not self.root.exists():
            return []
        return [self._load(p.parent) for p in sorted(self.root.glob("*/project.yaml"))]

    def _load(self, folder: Path) -> Project:
        data = yaml.safe_load((folder / "project.yaml").read_text(encoding="utf-8")) or {}
        return Project(ProjectInfo.model_validate(data), folder)

    def get(self, ref: str) -> Project:
        projects = self.list()
        for p in projects:
            if ref in (p.id, p.info.name) or slugify(ref) == p.id:
                return p
        matches = [p for p in projects if slugify(ref) in p.id]
        if len(matches) == 1:
            return matches[0]
        raise ProjectError(f"Progetto '{ref}' non trovato.")

    def find(self, ref: str) -> Project | None:
        try:
            return self.get(ref)
        except ProjectError:
            return None

    def containing(self, doc_id: str) -> list[Project]:
        return [p for p in self.list() if doc_id in p.info.documents]

    def create(self, name: str, documents: list[str] | None = None) -> Project:
        base = slugify(name)
        candidate, n = base, 2
        while (self.root / candidate).exists():
            candidate, n = f"{base}-{n}", n + 1
        folder = self.root / candidate
        folder.mkdir(parents=True)
        project = Project(ProjectInfo(id=candidate, name=name.strip() or candidate,
                                      documents=list(documents or [])), folder)
        project.save()
        return project

    def add_document(self, project: Project, doc_id: str) -> None:
        if doc_id not in project.info.documents:
            project.info.documents.append(doc_id)
            project.save()

    def remove_document(self, project: Project, doc_id: str) -> None:
        if doc_id in project.info.documents:
            project.info.documents.remove(doc_id)
            project.info.settings.pop(doc_id, None)
            project.save()

    def remove(self, project: Project) -> None:
        shutil.rmtree(project.folder)
