"""Strato applicativo: collega configurazione, workspace, biblioteca, progetti e Gemini.

L'interfaccia web e la riga di comando usano solo questa classe, così la logica non dipende
dall'interfaccia.

La pipeline (vedi docs/GUIDA_INDICIZZAZIONE.md): biblioteca → analisi del catalogo (scheda e
guida all'indicizzazione) → progetto creato da un catalogo → ① Tabella → ② PDF e pagine →
③ Prova → ④ Indicizzazione → ⑤ Risultati. Le **regole di estrazione** non si scrivono a mano:
le compone il programma (``project_rules`` / ``document_rules``) dalla Tabella del progetto,
dalla guida del catalogo e dalle note del PDF.
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from docanalyzer import correzioni
from docanalyzer.core.config import Config, load_config
from docanalyzer.core.documents import Document, DocumentStore
from docanalyzer.core.gemini import GeminiClient, LLMClient
from docanalyzer.core.library import Library, LibraryCard, LibraryError
from docanalyzer.core.manifest import Manifest
from docanalyzer.core.projects import Project, ProjectError, ProjectStore, clean_columns
from docanalyzer.core.render import format_pages
from docanalyzer.core.workspace import Workspace
from docanalyzer.indexing.assemble import AssembledIndex, assemble, merge
from docanalyzer.indexing.export import write_anomalies_by_document, write_index
from docanalyzer.indexing.extractor import Extractor, load_page_results, selected_pages
from docanalyzer.indexing.spec import ColumnSpec, IndexingSpec

FAKE_ENV_VAR = "DOCANALYZER_FAKE_GEMINI"


@dataclass
class ExportResult:
    csv_path: Path
    anomalies_path: Path | None
    index: AssembledIndex
    stale: bool = False   # regole cambiate dopo l'estrazione


@dataclass
class ProjectExport:
    csv_path: Path
    anomalies_path: Path | None
    index: AssembledIndex                                   # CSV unico
    documents: list[tuple[Document, ExportResult]] = field(default_factory=list)
    not_indexed: list[Document] = field(default_factory=list)
    search_page: Path | None = None

    @property
    def stale(self) -> list[Document]:
        return [d for d, r in self.documents if r.stale]


class App:
    def __init__(self, config: Config | None = None, client: LLMClient | None = None):
        self.config = config or load_config()
        self.workspace = Workspace(self.config.workspace_path).ensure()
        self.documents = DocumentStore(self.workspace)
        self.projects = ProjectStore(self.workspace)
        self.library = Library(self.workspace, self.documents)
        self._client = client
        self.events: deque[dict] = deque(maxlen=300)
        self.ensure_cards()

    # --- messaggi per l'utente ----------------------------------------------------------
    def emit(self, message: str) -> None:
        """Messaggio di servizio (sovraccarico, quote, ...): nel terminale e per l'interfaccia web."""
        from tqdm import tqdm

        tqdm.write(message)
        self.events.append({"ts": time.time(), "text": message})

    def events_since(self, ts: float, limit: int = 15) -> list[dict]:
        return [e for e in self.events if e["ts"] >= ts][-limit:]

    # --- biblioteca -------------------------------------------------------------------------
    def ensure_cards(self) -> None:
        """Ogni documento ha la sua scheda della biblioteca (i documenti delle versioni
        precedenti la ricevono vuota, nella cartella principale)."""
        for doc in self.documents.list():
            if not self.library.has_card(doc):
                self.library.save_card(doc, LibraryCard())

    def add_to_library(self, pdf_path: Path, folder: str = "") -> Document:
        """Aggiunge un PDF alla biblioteca, nella cartella indicata."""
        doc = self.documents.add(Path(pdf_path))
        self.library.save_card(doc, LibraryCard(folder=folder))
        return doc

    def delete_document(self, doc: Document) -> None:
        """Elimina un PDF dalla biblioteca, con pagine e risultati; solo se nessun progetto lo usa."""
        using = self.projects.containing(doc.id)
        if using:
            names = ", ".join(f"'{p.info.name}'" for p in using)
            raise LibraryError(f"'{doc.info.title}' è usato dai progetti {names}: toglilo prima dai progetti.")
        self.documents.remove(doc)

    # --- progetti ----------------------------------------------------------------------------
    def create_project(self, name: str, docs: list[Document], *, row: str, columns: list[dict],
                       description: str = "", instructions: str = "",
                       sections: dict[str, list[str]] | None = None) -> Project:
        """Nuovo progetto con la sua Tabella e i suoi PDF.

        Per ogni PDF: le pagine dalle collezioni indicate in ``sections`` (altrimenti le sue
        collezioni *dati*) e la guida all'indicizzazione della sua scheda, entrambe copiate.
        """
        name = " ".join((name or "").split())
        if not name:
            raise ProjectError("Dai un nome al progetto.")
        columns = clean_columns(columns)
        if not " ".join(row.split()) or not columns:
            raise ProjectError("Compila la tabella: cosa rappresenta una riga e almeno una colonna.")
        project = self.projects.create(name, [d.id for d in docs])
        info = project.info
        info.description, info.row = description.strip(), " ".join(row.split())
        info.fields, info.instructions = columns, instructions.strip()
        for doc in docs:
            self.link_from_library(project, doc, (sections or {}).get(doc.id))
        project.save()
        return project

    def add_to_project(self, project: Project, doc: Document) -> None:
        """Aggiunge un PDF della biblioteca a un progetto (pagine *dati* e guida copiate)."""
        if doc.id in project.info.documents:
            return
        self.projects.add_document(project, doc.id)
        self.link_from_library(project, doc)
        project.save()

    def remove_from_project(self, project: Project, doc: Document) -> None:
        """Toglie un documento dal progetto: il PDF resta nella biblioteca."""
        self.projects.remove_document(project, doc.id)

    def remove_project(self, project: Project) -> None:
        """Elimina il progetto; i suoi PDF (e i risultati) restano nella biblioteca."""
        self.projects.remove(project)

    def project_documents(self, project: Project) -> list[Document]:
        docs = []
        for doc_id in project.info.documents:
            try:
                docs.append(self.documents.get(doc_id))
            except Exception:  # documento eliminato: lo si ignora
                continue
        return docs

    @staticmethod
    def send_options(project: Project) -> dict:
        """Come inviare le pagine a Gemini, per ``Extractor.run`` / ``preview``."""
        return {"send": project.info.send_mode, "max_pages": project.info.pages_per_request}

    def project_export_dir(self, project: Project) -> Path:
        return self.workspace.exports_dir / project.id

    # --- dalla biblioteca al progetto (copie: fanno parte delle regole) ------------------------
    def pages_from_collections(self, doc: Document, ids: list[str]) -> tuple[list[int], list[str]]:
        """Le pagine delle collezioni indicate e gli id che non esistono più nella scheda."""
        card = self.library.card(doc)
        by_id = {c.id: c for c in card.collections}
        pages = sorted({p for i in ids if i in by_id for p in by_id[i].pages})
        return pages, [i for i in ids if i not in by_id]

    def link_from_library(self, project: Project, doc: Document, collection_ids: list[str] | None = None) -> None:
        """Copia nel progetto le pagine (dalle collezioni indicate o da quelle *dati*) e la guida."""
        card = self.library.card(doc)
        ids = collection_ids if collection_ids else [c.id for c in card.collections if c.tag == "dati"]
        pages, missing = self.pages_from_collections(doc, ids)
        current = project.settings_for(doc.id)
        project.set_settings(doc.id, current.model_copy(update={
            "pages": format_pages(pages) if pages else None,
            "collections": [i for i in ids if i not in missing] if pages else [],
            "guide": card.guide,
        }))

    def library_changes(self, project: Project) -> list[dict]:
        """Per ogni PDF: cosa direbbe oggi la biblioteca rispetto alle copie del progetto.

        ``pages_changed``: le collezioni scelte sono cambiate o state eliminate; ``guide_changed``:
        la guida della scheda è diversa da quella copiata. ``new_data``: collezioni *dati* non
        scelte (solo un suggerimento).
        """
        out = []
        for doc in self.project_documents(project):
            settings = project.settings_for(doc.id)
            card = self.library.card(doc)
            library_pages, missing = None, []
            if settings.collections:
                pages, missing = self.pages_from_collections(doc, settings.collections)
                library_pages = format_pages(pages) if pages else None
            pages_changed = bool(settings.collections) and (library_pages != settings.pages or bool(missing))
            guide_changed = card.guide.strip() != settings.guide.strip()
            out.append({
                "doc_id": doc.id, "title": doc.info.title, "pages": settings.pages,
                "library_pages": library_pages, "missing": len(missing),
                "new_data": [{"id": c.id, "start": c.start, "end": c.end, "comment": c.comment}
                             for c in card.collections if c.tag == "dati" and c.id not in settings.collections],
                "pages_changed": pages_changed, "guide_changed": guide_changed,
                "has_guide": bool(settings.guide.strip()), "library_has_guide": bool(card.guide.strip()),
                "changed": pages_changed or guide_changed,
            })
        return out

    def update_from_library(self, project: Project, doc_ids: list[str]) -> list[str]:
        """Ricopia pagine (dalle collezioni scelte) e guida dalla biblioteca per i PDF indicati."""
        updated = []
        for change in self.library_changes(project):
            if change["doc_id"] not in doc_ids or not change["changed"]:
                continue
            settings = project.settings_for(change["doc_id"])
            doc = self.documents.get(change["doc_id"])
            update: dict = {}
            if change["pages_changed"]:
                if not change["library_pages"]:
                    raise LibraryError(f"'{change['title']}': nessuna delle collezioni scelte esiste più nella "
                                       "biblioteca. Scegli di nuovo le pagine da indicizzare.")
                _, missing = self.pages_from_collections(doc, settings.collections)
                update["pages"] = change["library_pages"]
                update["collections"] = [i for i in settings.collections if i not in missing]
            if change["guide_changed"]:
                update["guide"] = self.library.card(doc).guide
            project.set_settings(doc.id, settings.model_copy(update=update))
            updated.append(doc.id)
        project.save()
        return updated

    # --- regole di estrazione (composte dal programma) -----------------------------------------
    def project_rules(self, project: Project) -> IndexingSpec:
        """Le regole comuni a tutti i PDF, dalla Tabella del progetto."""
        info = project.info
        if not info.has_table:
            raise ProjectError("Completa la Tabella del progetto (passo ①): cosa rappresenta una riga e "
                               "almeno una colonna.")
        return IndexingSpec(
            name=project.id, description=info.description, row=info.row, instructions=info.instructions,
            columns=[ColumnSpec(name=f["name"], description=f.get("description", ""), context=bool(f.get("header")))
                     for f in info.fields],
        )

    def document_rules(self, project: Project, doc: Document,
                       base: IndexingSpec | None = None) -> tuple[IndexingSpec, str]:
        """Regole e guida per un PDF: le regole comuni più le sue note e le sue pagine; la guida
        del suo catalogo accompagna ogni pagina."""
        base = base or self.project_rules(project)
        settings = project.settings_for(doc.id)
        return base.for_document(settings.notes, settings.pages, doc.info.title), settings.guide

    def document_progress(self, project: Project, doc: Document, base: IndexingSpec | None = None) -> dict:
        """Pagine da indicizzare, fatte e fallite di un PDF nel progetto, e se le regole sono cambiate.

        Usa solo il manifest (veloce anche con molte pagine).
        """
        spec, guide = self.document_rules(project, doc, base)
        selected = set(selected_pages(doc, spec))
        info = {"to_index": len(selected), "done": 0, "failed": 0, "stale": False, "indexed": False}
        manifest_path = doc.extraction_dir(spec.name) / "manifest.json"
        if manifest_path.exists():
            manifest = Manifest.load_or_create(manifest_path, doc.info.page_count)
            info.update(done=len(selected & manifest.done_pages()), failed=len(selected & set(manifest.failed_pages())),
                        stale=self._is_stale(spec, manifest, guide), indexed=True)
        return info

    def project_progress(self, project: Project) -> dict | None:
        """Avanzamento dell'indicizzazione di tutto il progetto (None se la Tabella è incompleta)."""
        if not project.info.has_table:
            return None
        base = self.project_rules(project)
        total = {"to_index": 0, "done": 0, "failed": 0, "stale": []}
        for doc in self.project_documents(project):
            p = self.document_progress(project, doc, base)
            total["to_index"] += p["to_index"]
            total["failed"] += p["failed"]
            if p["stale"]:
                total["stale"].append(doc.id)     # risultati con regole vecchie: da rifare
            else:
                total["done"] += p["done"]
        return total

    def document_in_projects(self, doc: Document) -> list[dict]:
        """In quali progetti è usato un PDF e a che punto è la sua indicizzazione in ciascuno.

        Rigenera anche il CSV di quel PDF (dai risultati salvati, senza Gemini), così si può
        scaricare dalla scheda della biblioteca.
        """
        out = []
        for project in self.projects.containing(doc.id):
            settings = project.settings_for(doc.id)
            info: dict = {
                "id": project.id, "name": project.info.name, "configured": project.info.has_table,
                "pages": settings.pages, "from_library": bool(settings.collections),
                "has_guide": bool(settings.guide.strip()),
                "guide_changed": settings.guide.strip() != self.library.card(doc).guide.strip(),
                "to_index": 0, "done": 0, "failed": 0, "rows": None, "errors": 0, "warnings": 0,
                "stale": False, "csv": False,
            }
            out.append(info)
            if not project.info.has_table:
                continue
            progress = self.document_progress(project, doc)
            info.update(to_index=progress["to_index"], done=progress["done"], failed=progress["failed"])
            if not progress["indexed"]:
                continue
            spec, guide = self.document_rules(project, doc)
            result = self.export(doc, spec, guide, target_dir=self.project_export_dir(project) / "documenti",
                                 corrections=correzioni.load(project))
            info.update(rows=result.index.stats.get("righe_finali", 0), errors=result.index.stats.get("errori", 0),
                        warnings=result.index.stats.get("avvisi", 0), stale=result.stale, csv=True)
        return out

    # --- risultati -----------------------------------------------------------------------------
    def document_index(self, doc: Document, spec: IndexingSpec,
                       corrections: correzioni.Corrections | None = None) -> tuple[AssembledIndex, Manifest]:
        """Le righe di un documento dai risultati salvati, con le correzioni del progetto se date."""
        manifest_path = doc.extraction_dir(spec.name) / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Il documento '{doc.id}' non è ancora stato indicizzato in questo progetto.")
        manifest = Manifest.load_or_create(manifest_path, doc.info.page_count)
        results = load_page_results(doc, spec.name)
        if corrections is not None and not corrections.empty:
            results = correzioni.apply(corrections, doc.id, results).results
        expected = sorted(set(selected_pages(doc, spec)) | set(results))
        return assemble(spec, results, doc.info.source_filename, expected, manifest.failed_pages()), manifest

    def export(self, doc: Document, spec: IndexingSpec, guide: str, target_dir: Path,
               corrections: correzioni.Corrections | None = None) -> ExportResult:
        """Rigenera il CSV di un documento dai risultati salvati (senza chiamare Gemini), applicando le
        correzioni del progetto se date."""
        index, manifest = self.document_index(doc, spec, corrections)
        csv_path = target_dir / f"{doc.id}.csv"
        anomalies = write_index(index, spec, csv_path)
        return ExportResult(csv_path, anomalies, index, stale=self._is_stale(spec, manifest, guide))

    def _is_stale(self, spec: IndexingSpec, manifest: Manifest, guide: str) -> bool:
        current = spec.extraction_fingerprint(guide, self.config.gemini.model, self.config.indexing.input)
        return manifest.meta.get("fingerprint") not in (None, current)

    def export_project(self, project: Project) -> ProjectExport:
        """CSV unico del progetto + un CSV per documento (senza chiamare Gemini)."""
        base = self.project_rules(project)
        out_dir = self.project_export_dir(project)
        corrections = correzioni.load(project)
        parts: list[tuple[Document, ExportResult]] = []
        missing: list[Document] = []
        for doc in self.project_documents(project):
            spec, guide = self.document_rules(project, doc, base)
            if not (doc.extraction_dir(spec.name) / "manifest.json").exists():
                missing.append(doc)
                continue
            parts.append((doc, self.export(doc, spec, guide, target_dir=out_dir / "documenti",
                                           corrections=corrections)))
        merged = merge(base, [r.index for _, r in parts], deduplicate=False)
        merged.stats.update(
            documenti_indicizzati=len(parts),
            documenti_totali=len(parts) + len(missing),
            errori=sum(r.index.stats.get("errori", 0) for _, r in parts),
            avvisi=sum(r.index.stats.get("avvisi", 0) for _, r in parts),
            pagine_da_elaborare=sum(r.index.stats.get("pagine_da_elaborare", 0) for _, r in parts),
        )
        csv_path = out_dir / f"{project.id}.csv"
        write_index(merged, base, csv_path)
        anomalies = write_anomalies_by_document(
            [(d.info.source_filename, r.index) for d, r in parts], base, out_dir / f"{project.id}_anomalie.csv"
        )
        result = ProjectExport(csv_path, anomalies, merged, parts, missing)
        if parts:
            from docanalyzer.indexing.search_page import build_search_page

            result.search_page = build_search_page(self, project, result)
        return result

    # --- Gemini ---------------------------------------------------------------------
    @property
    def simulated(self) -> bool:
        return os.getenv(FAKE_ENV_VAR, "").strip().lower() in ("1", "true", "si", "sì", "yes")

    def client(self) -> LLMClient:
        """Il client viene creato solo quando serve: le operazioni che non chiamano Gemini
        funzionano anche senza chiavi API."""
        if self._client is None:
            if self.simulated:
                from docanalyzer.core.fake_gemini import FakeGeminiClient

                self._client = FakeGeminiClient()
            else:
                self._client = GeminiClient.from_env(self.config.gemini, log=self.emit)
        return self._client

    def extractor(self) -> Extractor:
        return Extractor(self.client(), self.config)

    # --- modalità RAG ----------------------------------------------------------------------------
    def guide_text(self, doc: Document) -> str:
        """La guida all'indicizzazione del catalogo (dalla biblioteca): accompagna ogni pagina
        anche quando la modalità RAG la descrive. Vuota se il catalogo non è stato analizzato."""
        return self.library.card(doc).guide
