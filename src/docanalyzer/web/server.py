"""Server locale dell'interfaccia grafica: ``docanalyzer ui``.

Espone delle API JSON sopra la stessa logica dell'applicazione (``App``, analisi del catalogo,
progetto guidato, prova, ``Extractor``) e serve la pagina web in ``static/``. Ascolta solo su
127.0.0.1: è raggiungibile solo da questo computer, e le chiavi API restano nel file .env.

La pipeline: **biblioteca** (cartelle, schede) → **analisi del catalogo** (scheda e guida
all'indicizzazione) → **progetto** creato dalla scheda di un catalogo → ① Tabella → ② PDF e
pagine → ③ Prova → ④ Indicizzazione → ⑤ Risultati.

Regole dell'interfaccia, garantite anche qui:

- niente parte verso Gemini se non da un endpoint esplicito (analisi, guida, progetto guidato,
  prova, indicizzazione), che la pagina chiama solo dopo una conferma dell'utente;
- nessun limite preventivo su pagine, dimensioni o numero di cataloghi: si avvisa della
  quantità e dei tempi, e se Gemini rifiuta la richiesta l'errore viene mostrato;
- le operazioni lunghe sono *lavori* in background (vedi ``jobs.py``), uno per progetto o
  per catalogo;
- i prompt si possono vedere prima dell'invio (``.../preview``).
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from docanalyzer import __version__, correzioni, verifiche
from docanalyzer import prova as prova_mod
from docanalyzer.app import App
from docanalyzer.core.documents import Document, DocumentError, DuplicateDocumentError
from docanalyzer.core.gemini import GeminiError, load_api_keys
from docanalyzer.core.library import PAGE_TAGS, FieldDef, LibraryCard
from docanalyzer.core.manifest import Manifest
from docanalyzer.core.page_runner import RunControl
from docanalyzer.core.pdf_tools import has_text_layer, render_thumbnail
from docanalyzer.core.projects import Project, ProjectError, clean_columns
from docanalyzer.core.render import format_pages, parse_page_ranges, render_pages
from docanalyzer.guided_project import GuidedRun, create_direct, get_run, list_runs, make_request, run_guided
from docanalyzer.guided_project import create_project as create_guided_project
from docanalyzer.guided_project import prepare as prepare_guided
from docanalyzer.indexing.assemble import SOURCE_KEY
from docanalyzer.indexing.extractor import (
    SEND_MODES,
    UNLIMITED_ATTEMPTS,
    Extractor,
    SpecChangedError,
    load_page_results,
    selected_pages,
    split_blocks,
)
from docanalyzer.indexing.spec import SpecError
from docanalyzer.library_analysis import (
    HEAVY_PDF_BYTES,
    PromptStore,
    Selection,
    apply_analysis,
    attachment_size,
    build_guide_prompt,
    build_prompt,
    check_pages,
    estimate_seconds,
    get_analysis,
    guide_pages,
    list_analyses,
    quick_pages,
    run_analysis,
    run_guide,
    save_analysis,
)
from docanalyzer.web.jobs import JobConflictError, JobManager
from docanalyzer.web.theme import available_themes, check_theme, stylesheet_links

STATIC_DIR = Path(__file__).parent / "static"
# stime indicative per l'invio di più pagine insieme (estratto PDF): token e secondi per richiesta
TOKENS_PER_PDF_PAGE, TOKENS_PER_REQUEST = 800, 3000
SECONDS_PER_REQUEST, SECONDS_PER_PAGE = 20, 2
MAX_ROWS_IN_VIEW = 300
# l'interfaccia cambia a ogni aggiornamento del programma: il browser deve sempre ricontrollare
# i file (risposta "304 non modificato" se uguali), altrimenti può mescolare versioni diverse
NO_CACHE = {"Cache-Control": "no-cache"}


class _UiFiles(StaticFiles):
    """File statici dell'interfaccia, sempre ricontrollati dal browser."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.update(NO_CACHE)
        return response


def create_app(app: App, jobs: JobManager | None = None) -> FastAPI:
    api = FastAPI(title="docanalyzer", version=__version__, docs_url=None, redoc_url=None)
    jobs = jobs or JobManager()
    api.state.app = app
    api.state.jobs = jobs
    check_theme(app.config.ui.theme)              # tema inesistente: errore chiaro all'avvio

    # ------------------------------------------------------------------ errori
    def _error(status: int, message: str, **extra: Any) -> JSONResponse:
        return JSONResponse({"detail": message, **extra}, status_code=status)

    @api.exception_handler(DuplicateDocumentError)
    async def _dup(_: Request, e: DuplicateDocumentError):
        return _error(409, str(e), existing=e.existing.id)

    @api.exception_handler(DocumentError)
    async def _doc(_: Request, e: DocumentError):
        return _error(404 if "non trovato" in str(e) else 400, str(e))

    @api.exception_handler(ProjectError)
    async def _proj(_: Request, e: ProjectError):
        return _error(404 if "non trovato" in str(e) else 400, str(e))

    @api.exception_handler(SpecChangedError)
    async def _changed(_: Request, e: SpecChangedError):
        return _error(409, str(e) + " Per applicare le regole attuali rifai l'indicizzazione da capo.",
                      spec_changed=True)

    @api.exception_handler(JobConflictError)
    async def _conflict(_: Request, e: JobConflictError):
        return _error(409, str(e))

    for exc_type in (SpecError, GeminiError, ValueError):
        @api.exception_handler(exc_type)
        async def _bad(_: Request, e: Exception):
            return _error(400, str(e))

    @api.exception_handler(FileNotFoundError)
    async def _missing(_: Request, e: FileNotFoundError):
        return _error(404, str(e))

    # ------------------------------------------------------------------ utility
    def project_or_404(pid: str) -> Project:
        return app.projects.get(pid)

    def doc_of(project: Project, doc_id: str) -> Document:
        if doc_id not in project.info.documents:
            raise HTTPException(404, f"Il documento '{doc_id}' non fa parte del progetto.")
        return app.documents.get(doc_id)

    def no_job(project: Project) -> None:
        if jobs.active_for(project.id):
            raise HTTPException(409, "C'è un'operazione in corso su questo progetto.")

    def usage() -> dict[str, Any] | None:
        u = getattr(app._client, "usage", None)
        if u is None:
            return None
        return {"requests": u.requests, "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                "text": u.describe()}

    def requests_per_minute() -> int:
        keys = max(1, len(load_api_keys()))
        return app.config.gemini.max_requests_per_minute_total or app.config.gemini.requests_per_minute_per_key * keys

    def collections_view(card: LibraryCard) -> list[dict[str, Any]]:
        return [{"id": c.id, "start": c.start, "end": c.end, "tag": c.tag, "label": PAGE_TAGS[c.tag][0],
                 "comment": c.comment} for c in card.collections]

    def doc_status(project: Project, doc: Document) -> dict[str, Any]:
        settings = project.settings_for(doc.id)
        card = app.library.card(doc)
        total = doc.info.page_count
        to_index = len(parse_page_ranges(settings.pages, total)) if settings.pages else total
        info: dict[str, Any] = {
            "id": doc.id, "title": doc.info.title, "source_filename": doc.info.source_filename,
            "page_count": total, "settings": settings.model_dump(), "to_index": to_index,
            "done": 0, "failed": 0,
            "library": {"description": card.description, "data": [f.name for f in card.fields],
                        "collections": collections_view(card), "folder": card.folder, "tags": card.tags,
                        "has_guide": bool(card.guide.strip())},
        }
        manifest_path = doc.extraction_dir(project.id) / "manifest.json"
        if manifest_path.exists():
            manifest = Manifest.load_or_create(manifest_path, total)
            selected = set(parse_page_ranges(settings.pages, total) or range(1, total + 1))
            info.update(done=len(selected & manifest.done_pages()),
                        failed=len(selected & set(manifest.failed_pages())))
        return info

    def verify_state(project: Project) -> tuple[bool, int]:
        """Se le verifiche sono state eseguite e quante segnalazioni restano aperte (dall'archivio)."""
        stored = verifiche.load_results(project)
        accepted = verifiche.load_accepted(project)
        ids = {i["id"] for entries in stored.values() for entry in entries.values() for i in entry["items"]}
        return bool(stored), len(ids - accepted)

    def project_steps(project: Project, docs: list[Document], progress: dict | None,
                      changes: list[dict], prova_stale: bool | None) -> dict[str, Any]:
        """I 6 passi del progetto con il loro stato, e il prossimo passo da fare.

        Stati: "fatto", "da fare", "in corso", "da rivedere", "facoltativo".
        """
        info = project.info
        no_guide = [d for d in docs if not project.settings_for(d.id).guide.strip()]
        steps = {
            "settings": ("fatto", f"{len(info.fields)} colonne") if info.has_table
            else ("da fare", "riga e colonne"),
            "docs": ("da fare", "nessun PDF") if not docs
            else ("da rivedere", f"la biblioteca è cambiata per {len(changes)} PDF") if changes
            else ("da rivedere", f"{len(no_guide)} PDF senza guida") if no_guide
            else ("fatto", f"{len(docs)} PDF"),
            "test": ("da fare", "") if prova_stale is None
            else ("da rivedere", "regole cambiate dopo la prova") if prova_stale
            else ("fatto", ""),
        }
        todo = 0
        if progress is None:
            steps["index"] = ("da fare", "prima serve la tabella")
            steps["results"] = ("da fare", "")
        else:
            todo = progress["to_index"] - progress["done"]
            if progress["stale"]:
                steps["index"] = ("da rivedere", f"{len(progress['stale'])} PDF da rifare: regole cambiate")
            elif todo and progress["done"]:
                steps["index"] = ("in corso", f"{progress['done']}/{progress['to_index']} pagine")
            elif todo:
                steps["index"] = ("da fare", f"{todo} pagine")
            else:
                steps["index"] = ("fatto", f"{progress['done']} pagine")
            steps["results"] = ("fatto", "") if progress["done"] else \
                ("da rivedere", "risultati con regole vecchie") if progress["stale"] else ("da fare", "")
        if steps["test"][0] == "da fare" and progress and progress["done"]:
            steps["test"] = ("facoltativo", "")
        verified, open_items = verify_state(project)
        if not (progress and progress["done"]):
            steps["verify"] = ("da fare", "")
        elif not verified:
            steps["verify"] = ("da fare", "")
        else:
            steps["verify"] = ("da rivedere", f"{open_items} segnalazioni") if open_items else ("fatto", "")

        started = bool(progress and progress["done"])
        if not info.has_table:
            nxt = ("settings", "Completa la tabella: cosa rappresenta una riga e le colonne")
        elif not docs:
            nxt = ("docs", "Aggiungi i PDF dalla biblioteca")
        elif changes:
            nxt = ("docs", "Aggiorna dalla biblioteca le pagine o le guide cambiate")
        elif prova_stale is None and not started:
            nxt = ("test", "Fai una prova su poche pagine")
        elif prova_stale and not started:
            nxt = ("test", "Rifai la prova: tabella, guide o note sono cambiate")
        elif progress and (progress["stale"] or todo):
            nxt = ("index", "Rifai i PDF con le regole cambiate" if progress["stale"] else f"Indicizza {todo} pagine")
        elif not verified:
            nxt = ("verify", "Verifica i risultati dell'indicizzazione")
        else:
            nxt = ("results", "Guarda i risultati")
        return {"steps": {k: {"state": v[0], "note": v[1]} for k, v in steps.items()},
                "next": {"tab": nxt[0], "text": nxt[1]}}

    def project_summary(project: Project) -> dict[str, Any]:
        docs = app.project_documents(project)
        job = jobs.active_for(project.id)
        statuses = [doc_status(project, d) for d in docs]
        changes = [c for c in app.library_changes(project) if c["changed"]]
        progress = app.project_progress(project)
        prova_stale = prova_mod.is_stale(app, project)
        return {
            **project.info.model_dump(exclude={"settings"}),
            **project_steps(project, docs, progress, changes, prova_stale),
            "progress": progress,
            "has_table": project.info.has_table,
            "library_changes": changes,
            "documents": statuses,
            "page_count": sum(d.info.page_count for d in docs),
            "done": sum(s["done"] for s in statuses),
            "job": job.to_dict() if job else None,
        }

    # ------------------------------------------------------------------ stato
    @api.get("/api/status")
    def status():
        keys = load_api_keys()
        return {
            "version": __version__,
            "simulated": app.simulated,
            "keys": len(keys),
            "model": app.config.gemini.model,
            "input_mode": app.config.indexing.input,
            "workspace": str(app.workspace.root),
            "usage": usage(),
            "ready": bool(keys) or app.simulated,
        }

    # ------------------------------------------------------------------ progetti
    @api.get("/api/projects")
    def list_projects():
        return [project_summary(p) for p in app.projects.list()]

    @api.get("/api/projects/{pid}")
    def get_project(pid: str):
        return project_summary(project_or_404(pid))

    @api.put("/api/projects/{pid}/send")
    def project_send(pid: str, body: dict = Body(...)):
        """Come inviare le pagine a Gemini (prova e indicizzazione): una per richiesta o insieme."""
        project = project_or_404(pid)
        no_job(project)
        raw = body.get("pages_per_request")
        project.set_send(str(body.get("mode") or "pagina"), int(raw) if raw not in (None, "") else None)
        project.save()
        return project_summary(project)

    @api.put("/api/projects/{pid}/settings")
    def project_settings(pid: str, body: dict = Body(...)):
        """① Tabella: nome, descrizione, cosa è una riga, colonne, altre indicazioni."""
        project = project_or_404(pid)
        no_job(project)
        info = project.info
        name = " ".join(str(body.get("name", info.name) or "").split())
        row = " ".join(str(body.get("row", info.row) or "").split())
        columns = clean_columns(body["columns"] if isinstance(body.get("columns"), list) else info.fields)
        if not name:
            raise ProjectError("Dai un nome al progetto.")
        if not row or not columns:
            raise ProjectError("La tabella deve avere cosa rappresenta una riga e almeno una colonna.")
        info.name, info.row, info.fields = name, row, columns
        if "description" in body:
            info.description = str(body["description"] or "").strip()
        if "instructions" in body:
            info.instructions = str(body["instructions"] or "").strip()
        project.save()
        return project_summary(project)

    @api.delete("/api/projects/{pid}")
    def delete_project(pid: str):
        project = project_or_404(pid)
        no_job(project)
        app.remove_project(project)
        return {"deleted": project.id}

    @api.delete("/api/projects/{pid}/documents/{doc_id}")
    def remove_document(pid: str, doc_id: str):
        project = project_or_404(pid)
        no_job(project)
        doc = doc_of(project, doc_id)
        if len(project.info.documents) == 1:
            raise ProjectError("È l'ultimo PDF del progetto: elimina il progetto invece di toglierlo.")
        app.remove_from_project(project, doc)
        return {"removed": doc.id}

    @api.put("/api/projects/{pid}/documents/{doc_id}/settings")
    def document_settings(pid: str, doc_id: str, body: dict = Body(...)):
        """Note e pagine di un PDF nel progetto (la guida si aggiorna solo dalla biblioteca)."""
        project = project_or_404(pid)
        no_job(project)
        doc = doc_of(project, doc_id)
        current = project.settings_for(doc.id)
        collections = [str(c) for c in body.get("collections") or []]
        if collections:
            # pagine dalle collezioni della biblioteca: le calcola il programma (copia)
            found, missing = app.pages_from_collections(doc, collections)
            if missing:
                raise ValueError("Alcune collezioni non esistono più nella biblioteca: ricarica la pagina.")
            pages = format_pages(found)
        else:
            pages = str(body.get("pages") or "").strip() or None
            if pages:
                parse_page_ranges(pages, doc.info.page_count)  # errore leggibile se non valide
        project.set_settings(doc.id, current.model_copy(update={
            "notes": str(body.get("notes") or ""), "pages": pages, "collections": collections}))
        project.save()
        return doc_status(project, doc)

    @api.post("/api/projects/{pid}/documents/from-library")
    def project_add_from_library(pid: str, body: dict = Body(...)):
        project = project_or_404(pid)
        no_job(project)
        added = []
        for doc in docs_from_body(body):
            if doc.id not in project.info.documents:
                app.add_to_project(project, doc)
                added.append(doc.id)
        return {"added": added}

    @api.get("/api/projects/{pid}/library-changes")
    def library_changes(pid: str):
        return app.library_changes(project_or_404(pid))

    @api.post("/api/projects/{pid}/library-update")
    def library_update(pid: str, body: dict = Body(...)):
        project = project_or_404(pid)
        no_job(project)
        updated = app.update_from_library(project, [str(d) for d in body.get("docs") or []])
        return {"updated": updated, "project": project_summary(app.projects.get(project.id))}

    @api.get("/api/projects/{pid}/documents/{doc_id}/guide")
    def project_guide(pid: str, doc_id: str):
        project = project_or_404(pid)
        doc = doc_of(project, doc_id)
        return {"guide": project.settings_for(doc.id).guide, "library_guide": app.library.card(doc).guide}

    # ------------------------------------------------------------------ ③ prova
    def prova_plan_from_body(project: Project, body: dict) -> dict[str, list[int]]:
        docs = {d.id: d for d in app.project_documents(project)}
        plan: dict[str, list[int]] = {}
        for doc_id, pages in (body.get("plan") or {}).items():
            if doc_id not in docs:
                raise ProjectError(f"Il documento '{doc_id}' non fa parte del progetto.")
            text = format_pages([int(p) for p in pages]) if isinstance(pages, list) else str(pages or "")
            if text.strip():
                plan[doc_id] = parse_page_ranges(text, docs[doc_id].info.page_count)
        return plan

    @api.get("/api/projects/{pid}/prova")
    def prova_get(pid: str, count: int = prova_mod.DEFAULT_PAGES):
        project = project_or_404(pid)
        view = prova_mod.prova_view(app, project)
        view["default_count"] = prova_mod.DEFAULT_PAGES
        view["plan"] = {k: format_pages(v) for k, v in prova_mod.default_plan(app, project, count).items()}
        return view

    @api.post("/api/projects/{pid}/prova/plan")
    def prova_sample(pid: str, body: dict = Body(...)):
        """Pagine proposte per la prova (``more``: pagine non ancora provate)."""
        project = project_or_404(pid)
        count = max(1, int(body.get("count") or prova_mod.DEFAULT_PAGES))
        ids = body.get("docs") if isinstance(body.get("docs"), list) else None
        plan = prova_mod.default_plan(app, project, count, [str(i) for i in ids] if ids is not None else None,
                                      more=bool(body.get("more")))
        return {"plan": {k: format_pages(v) for k, v in plan.items()}}

    @api.post("/api/projects/{pid}/prova")
    def prova_start(pid: str, body: dict = Body(...)):
        project = project_or_404(pid)
        app.project_rules(project)                   # errore leggibile se la tabella è incompleta
        plan = prova_plan_from_body(project, body)
        if not plan:
            raise ProjectError("Scegli almeno un PDF e almeno una pagina per la prova.")
        app.client()                                 # errore subito se mancano le chiavi
        total = sum(len(p) for p in plan.values())

        def work(job):
            return prova_mod.run_prova(app, project, plan, job.control)

        return jobs.submit(project.id, "test", f"Prova di indicizzazione ({total} pagine)", work).to_dict()

    @api.get("/api/projects/{pid}/prova.csv")
    def prova_csv(pid: str):
        project = project_or_404(pid)
        path = prova_mod.prova_dir(project) / f"{project.id}_prova.csv"
        if not path.exists():
            raise HTTPException(404, "Nessuna prova.")
        return FileResponse(path, filename=path.name, media_type="text/csv")

    # ------------------------------------------------------------------ ④ indicizzazione
    def estimate_minutes(project: Project, pages: int, blocks: list[int]) -> int:
        """Tempo indicativo: con l'invio insieme richieste grandi in parallelo (una per chiave)."""
        if project.info.send_mode == "insieme":
            seconds = [SECONDS_PER_REQUEST + SECONDS_PER_PAGE * n for n in blocks]
            parallel = app.config.indexing.max_workers or max(1, len(load_api_keys()))
            total = max(max(seconds, default=0), sum(seconds) / parallel)
            return max(1, round(total / 60)) if seconds else 0
        return max(1, round(pages / requests_per_minute())) if pages else 0

    def failure_reason(failures: list[str]) -> str:
        """Il motivo più frequente tra le pagine fallite di un PDF (accorciato)."""
        if not failures:
            return ""
        reason = max(set(failures), key=failures.count)
        return reason if len(reason) <= 300 else reason[:300] + "…"

    def index_plan_for(project: Project) -> dict[str, Any]:
        base = app.project_rules(project)
        extractor = Extractor(None, app.config)  # type: ignore[arg-type]  (solo impronte)
        state = prova_mod.load_state(project)["documents"]
        together = project.info.send_mode == "insieme"
        rows = []
        for doc in app.project_documents(project):
            spec, guide = app.document_rules(project, doc, base)
            pages = selected_pages(doc, spec)
            manifest_path = doc.extraction_dir(spec.name) / "manifest.json"
            done: set[int] = set()
            failures: list[str] = []
            changed = False
            fingerprint = extractor.fingerprint(spec, guide)
            if manifest_path.exists():
                m = Manifest.load_or_create(manifest_path, doc.info.page_count)
                done = m.done_pages()
                failures = [e for n, e in m.failed_pages().items() if n in set(pages)]
                changed = bool(done) and m.meta.get("fingerprint") != fingerprint
            prova = state.get(doc.id) or {}
            reusable = set(prova.get("pages", [])) if prova.get("fingerprint") == fingerprint else set()
            todo = [p for p in pages if changed or p not in done]
            from_prova = len([p for p in todo if p in reusable])
            to_send = [p for p in todo if p not in reusable]
            blocks = split_blocks(to_send, project.info.pages_per_request) if to_send and together else []
            restart = split_blocks(pages, project.info.pages_per_request) if together else []
            rows.append({
                "id": doc.id, "title": doc.info.title, "pages": len(pages),
                "pages_text": spec.pages or f"1-{doc.info.page_count}",
                "done": len([p for p in pages if p in done]) if not changed else 0,
                "todo": len(to_send), "from_prova": from_prova, "failed": len(failures),
                "failed_reason": failure_reason(failures), "spec_changed": changed,
                "requests": len(blocks) if together else len(to_send), "blocks": [len(b) for b in blocks],
                "restart_requests": len(restart) if together else len(pages),
                "restart_blocks": [len(b) for b in restart],
                "has_notes": bool(project.settings_for(doc.id).notes.strip()), "has_guide": bool(guide.strip()),
            })
        todo = sum(r["todo"] for r in rows)
        requests = sum(r["requests"] for r in rows)
        minutes = estimate_minutes(project, todo, [n for r in rows for n in r["blocks"]])
        biggest = max((n for r in rows for n in r["blocks"]), default=0)
        all_pages = sum(r["pages"] for r in rows)
        return {
            "documents": rows, "send_mode": project.info.send_mode,
            "pages_per_request": project.info.pages_per_request,
            "pages": sum(r["pages"] for r in rows), "done": sum(r["done"] for r in rows), "todo": todo,
            "requests": requests, "from_prova": sum(r["from_prova"] for r in rows),
            "spec_changed": [r["id"] for r in rows if r["spec_changed"]],
            "estimate_minutes": minutes,
            # rifare tutto da capo (risultati cancellati, prova non riusata)
            "restart": {"pages": all_pages, "requests": sum(r["restart_requests"] for r in rows),
                        "minutes": estimate_minutes(project, all_pages,
                                                    [n for r in rows for n in r["restart_blocks"]])},
            "biggest_request": {"pages": biggest,
                                "tokens": TOKENS_PER_REQUEST + TOKENS_PER_PDF_PAGE * biggest} if biggest else None,
        }

    @api.get("/api/projects/{pid}/index/plan")
    def index_plan(pid: str):
        return index_plan_for(project_or_404(pid))

    @api.post("/api/projects/{pid}/index")
    def start_index(pid: str, body: dict = Body(default={})):
        """Avvia l'indicizzazione delle pagine da fare (comprese le fallite, sempre ritentate).

        ``force``: rifà da capo i PDF le cui regole sono cambiate (consenso esplicito).
        ``restart``: ``true`` per rifare da capo tutti i PDF, oppure un elenco di id (solo quei PDF):
        i loro risultati vengono cancellati e la prova non viene riusata.
        """
        project = project_or_404(pid)
        base = app.project_rules(project)
        force = bool(body.get("force"))
        extractor = app.extractor()
        docs = app.project_documents(project)
        restart_raw = body.get("restart")
        restart = {d.id for d in docs} if restart_raw is True else {str(i) for i in restart_raw or []}
        if restart - {d.id for d in docs}:
            raise ProjectError("Alcuni PDF da rifare non fanno parte del progetto.")
        if isinstance(restart_raw, list):
            docs = [d for d in docs if d.id in restart]          # da capo solo questi PDF, gli altri non si toccano
        redo_raw = body.get("redo") if isinstance(body.get("redo"), dict) else {}
        redo = {str(k): sorted({int(p) for p in v}) for k, v in redo_raw.items() if v}
        if redo:
            if set(redo) - {d.id for d in docs}:
                raise ProjectError("Alcuni PDF da rifare non fanno parte del progetto.")
            docs = [d for d in docs if d.id in redo]              # solo le pagine scelte di questi PDF
        send = app.send_options(project)
        if body.get("send") in SEND_MODES:                        # modalità scelta per questa volta
            send = {"send": body["send"], "max_pages": project.info.pages_per_request}
        rules = {d.id: app.document_rules(project, d, base) for d in docs}
        total = 0
        # prima dell'avvio: se le regole di un PDF sono cambiate serve il consenso esplicito
        # (force), che rifà da capo SOLO quei PDF
        for doc in docs:
            spec, guide = rules[doc.id]
            if doc.id in redo:
                manifest = extractor.open_manifest(doc, spec, guide)                 # regole cambiate: errore
                for n in redo[doc.id]:
                    extractor.result_path(doc.extraction_dir(spec.name), n).unlink(missing_ok=True)
                manifest.reset_pages(redo[doc.id])
                total += len(redo[doc.id])
                continue
            if doc.id in restart:
                manifest = extractor.open_manifest(doc, spec, guide, force=True)      # da capo
            else:
                try:
                    manifest = extractor.open_manifest(doc, spec, guide)
                except SpecChangedError:
                    if not force:
                        raise
                    manifest = extractor.open_manifest(doc, spec, guide, force=True)
                if prova_mod.seed_index(app, project, doc, spec, guide, extractor):   # pagine della prova già fatte
                    manifest = extractor.open_manifest(doc, spec, guide)
            total += len(manifest.pages_to_process(UNLIMITED_ATTEMPTS, only=selected_pages(doc, spec)))

        def work(job):
            done_before = 0
            reports = {}
            for doc in docs:
                if job.control.cancel.is_set():
                    break
                spec, guide = rules[doc.id]

                def progress(done: int, _total: int, msg: str, offset=done_before, title=doc.info.title) -> None:
                    job.done, job.total = offset + done, total
                    job.message = f"Indicizzazione di {title}" + (f" — {msg}" if "richiest" in msg else "")

                control = RunControl(progress=progress, cancel=job.control.cancel)
                pages = format_pages(redo[doc.id]) if doc.id in redo else None
                report = extractor.run(doc, spec, guide, pages=pages, show_progress=False, control=control,
                                       retry_failed=True, **send)
                reports[doc.id] = {
                    "succeeded": report.succeeded,
                    "failed": {str(k): v for k, v in report.failed.items()},
                    "not_attempted": report.not_attempted,
                    "stopped_reason": report.stopped_reason,
                }
                done_before += report.requested
                if report.stopped_reason and not job.control.cancel.is_set():
                    break      # quota esaurita o troppi errori: inutile continuare con gli altri PDF
            result = app.export_project(project)
            stopped = next((r["stopped_reason"] for r in reports.values() if r["stopped_reason"]), None)
            return {"documents": reports, "stats": result.index.stats, "stopped_reason": stopped}

        return jobs.submit(project.id, "index", f"Indicizzazione del progetto '{project.info.name}'", work).to_dict()

    # ------------------------------------------------------------------ ⑤ verifiche/elaborazione
    def docs_param(project: Project, docs: str | None) -> list[str] | None:
        if not docs:
            return None
        ids = [d for d in docs.split(",") if d]
        unknown = set(ids) - set(project.info.documents)
        if unknown:
            raise ProjectError(f"PDF non nel progetto: {', '.join(sorted(unknown))}.")
        return ids

    @api.get("/api/projects/{pid}/verifiche")
    def verify_overview(pid: str):
        project = project_or_404(pid)
        app.project_rules(project)
        return verifiche.overview(app, project)

    @api.put("/api/projects/{pid}/verifiche/impostazioni")
    def verify_settings(pid: str, body: dict = Body(...)):
        project = project_or_404(pid)
        info = project.info
        if "coverage" in body:
            if body["coverage"] not in verifiche.COVERAGE_MODES:
                raise ProjectError("Copertura: scegli tra almeno una riga, esattamente una riga o nessun controllo.")
            info.coverage = body["coverage"]
        if "check_columns" in body:
            info.check_columns = [c for c in body["check_columns"] or [] if c in info.column_names]
        for doc_id, text in (body.get("reference_pages") or {}).items():
            doc = doc_of(project, str(doc_id))
            text = str(text or "").strip() or None
            if text:
                try:
                    parse_page_ranges(text, doc.info.page_count)
                except ValueError as e:
                    raise ProjectError(f"{doc.info.title}, pagine dell'elenco: {e}") from e
            project.set_settings(doc.id, project.settings_for(doc.id).model_copy(update={"reference_pages": text}))
        project.save()
        return verifiche.overview(app, project)

    @api.post("/api/projects/{pid}/verifiche/accetta")
    def verify_accept(pid: str, body: dict = Body(...)):
        project = project_or_404(pid)
        ids = [str(i) for i in body.get("ids") or []]
        verifiche.set_accepted(project, ids, bool(body.get("accepted", True)))
        return {"ids": ids, "accepted": bool(body.get("accepted", True))}

    @api.get("/api/projects/{pid}/verifiche/riferimento/{doc_id}")
    def verify_reference_get(pid: str, doc_id: str):
        project = project_or_404(pid)
        doc = doc_of(project, doc_id)
        return {"reference": verifiche.load_reference(project, doc.id), "key_columns": project.info.key_columns,
                "pages": format_pages(verifiche.reference_pages(app, project, doc))}

    @api.put("/api/projects/{pid}/verifiche/riferimento/{doc_id}")
    def verify_reference_save(pid: str, doc_id: str, body: dict = Body(...)):
        """L'elenco di riferimento corretto a mano."""
        project = project_or_404(pid)
        doc = doc_of(project, doc_id)
        current = verifiche.load_reference(project, doc.id) or {"pages": "", "notes": "", "created_at": None}
        keys = project.info.key_columns
        items = []
        for it in body.get("items") or []:
            values = {c: " ".join(str((it.get("values") or {}).get(c, "")).split()) for c in keys}
            if any(values.values()):
                items.append({"values": values, "page": str(it.get("page") or "").strip()})
        verifiche.save_reference(project, doc.id, {**current, "items": items, "edited": True})
        return verify_reference_get(pid, doc_id)

    @api.post("/api/projects/{pid}/verifiche/{check}")
    def verify_run(pid: str, check: str, body: dict = Body(default={})):
        """Esegue una verifica, o ``tutte`` quelle senza Gemini (``checks``: solo alcune), sui PDF scelti.

        Senza Gemini l'esito arriva subito (``results``); se un elenco di riferimento va letto
        con Gemini parte un lavoro (``job``).
        """
        project = project_or_404(pid)
        app.project_rules(project)
        free = [c for c in verifiche.CHECKS if c not in verifiche.PAID_CHECKS]
        if check == "tutte":
            checks = [c for c in free if not body.get("checks") or c in body["checks"]]
        elif check in verifiche.CHECKS:
            checks = [check]
        else:
            raise HTTPException(404, "Verifica sconosciuta.")
        ids = docs_param(project, ",".join(body["docs"])) if isinstance(body.get("docs"), list) else None
        reread = bool(body.get("reread"))
        if check in verifiche.PAID_CHECKS and verifiche.references_to_read(app, project, ids, reread):
            client = app.client()

            def work(job):
                return verifiche.run_check(app, project, check, ids, client=client, reread=reread,
                                           progress=lambda m: setattr(job, "message", m))

            label = f"Verifica: {verifiche.CHECKS[check].lower()} (lettura con Gemini)"
            return {"job": jobs.submit(project.id, "verify", label, work).to_dict()}
        results, skipped = {}, {}
        for c in checks:
            try:
                results[c] = verifiche.run_check(app, project, c, ids)
            except ProjectError as e:
                if check != "tutte":
                    raise
                skipped[c] = str(e)
        if check == "tutte" and (not body.get("checks") or "riferimento" in body["checks"]):
            # il confronto con l'elenco di riferimento è senza Gemini, sui PDF che l'hanno già letto
            with_list = [d.id for d in app.project_documents(project)
                         if (ids is None or d.id in ids) and verifiche.load_reference(project, d.id) is not None]
            if with_list:
                try:
                    results["riferimento"] = verifiche.run_check(app, project, "riferimento", with_list)
                except ProjectError as e:
                    skipped["riferimento"] = str(e)
        return {"results": results, "skipped": skipped}

    @api.get("/api/projects/{pid}/verifiche/{check}")
    def verify_details(pid: str, check: str, docs: str | None = None):
        project = project_or_404(pid)
        return verifiche.details(project, check, docs_param(project, docs))

    # --- correzioni ---------------------------------------------------------------------------
    def corrections_view(project: Project) -> dict[str, Any]:
        corr = correzioni.load(project)
        base = app.project_rules(project)
        status: dict[str, int] = {}
        titles = {}
        for doc in app.project_documents(project):
            titles[doc.id] = doc.info.title
            spec, _ = app.document_rules(project, doc, base)
            if not (doc.extraction_dir(spec.name) / "manifest.json").exists():
                continue
            applied = correzioni.apply(corr, doc.id, load_page_results(doc, spec.name))
            for cid, n in applied.status.items():
                status[cid] = status.get(cid, 0) + n
        return {
            "rules": [{**r.model_dump(), "changed": status.get(r.id, 0),
                       "doc_title": titles.get(r.doc) if r.doc else None} for r in corr.rules],
            "edits": [{**e.model_dump(), "applicable": bool(status.get(e.id)), "doc_title": titles.get(e.doc, e.doc)}
                      for e in corr.edits],
            "deletions": [{**d.model_dump(), "applicable": bool(status.get(d.id)),
                           "doc_title": titles.get(d.doc, d.doc)} for d in corr.deletions],
        }

    def raw_results(project: Project, doc: Document) -> dict[int, dict[str, Any]]:
        spec, _ = app.document_rules(project, doc)
        return load_page_results(doc, spec.name)

    @api.get("/api/projects/{pid}/correzioni")
    def corrections_get(pid: str):
        return corrections_view(project_or_404(pid))

    @api.post("/api/projects/{pid}/correzioni/regola")
    def corrections_rule(pid: str, body: dict = Body(...)):
        """Sostituisci tutte: ``find`` → ``replace`` in una colonna (o tutte) di un PDF (o tutti)."""
        project = project_or_404(pid)
        find = str(body.get("find") or "")
        if not find:
            raise ProjectError("Scrivi il testo da sostituire.")
        column = body.get("column") or None
        correzioni.check_column(project, column)
        doc = doc_of(project, str(body["doc"])).id if body.get("doc") else None
        corr = correzioni.load(project)
        corr.rules.append(correzioni.Rule(find=find, replace=str(body.get("replace") or ""), column=column, doc=doc))
        correzioni.save(project, corr)
        return corrections_view(project)

    @api.post("/api/projects/{pid}/correzioni/cella")
    def corrections_cell(pid: str, body: dict = Body(...)):
        """Il valore di una cella scritto a mano (tornare al valore estratto toglie la correzione)."""
        project = project_or_404(pid)
        doc = doc_of(project, str(body.get("doc")))
        page, position, column = int(body["page"]), int(body["position"]), str(body.get("column") or "")
        correzioni.check_column(project, column)
        row = correzioni.raw_row(raw_results(project, doc), page, position)
        if row is None:
            raise ProjectError("Questa riga non esiste più: ricarica la pagina.")
        original, value = row.get(column, ""), str(body.get("value") or "")
        corr = correzioni.load(project)
        corr.edits = [e for e in corr.edits
                      if not (e.doc == doc.id and e.page == page and e.position == position and e.column == column)]
        if value != original:
            corr.edits.append(correzioni.CellEdit(doc=doc.id, page=page, position=position, column=column,
                                                  original=original, value=value))
        correzioni.save(project, corr)
        return corrections_view(project)

    @api.post("/api/projects/{pid}/correzioni/riga")
    def corrections_delete_row(pid: str, body: dict = Body(...)):
        project = project_or_404(pid)
        doc = doc_of(project, str(body.get("doc")))
        page, position = int(body["page"]), int(body["position"])
        row = correzioni.raw_row(raw_results(project, doc), page, position)
        if row is None:
            raise ProjectError("Questa riga non esiste più: ricarica la pagina.")
        corr = correzioni.load(project)
        corr.deletions.append(correzioni.RowDeletion(doc=doc.id, page=page, position=position, original=row))
        correzioni.save(project, corr)
        return corrections_view(project)

    @api.delete("/api/projects/{pid}/correzioni/{cid}")
    def corrections_remove(pid: str, cid: str):
        project = project_or_404(pid)
        corr = correzioni.load(project)
        if not corr.remove(cid):
            raise HTTPException(404, "Correzione non trovata.")
        correzioni.save(project, corr)
        return corrections_view(project)

    @api.get("/api/projects/{pid}/righe")
    def rows_view(pid: str, docs: str | None = None, q: str = "", page: int | None = None,
                  offset: int = 0, limit: int = 100):
        """Le righe corrette del progetto (con provenienza e celle corrette), filtrabili."""
        project = project_or_404(pid)
        base = app.project_rules(project)
        ids = docs_param(project, docs)
        corr = correzioni.load(project)
        needle = verifiche.norm(q)
        out: list[dict[str, Any]] = []
        for doc in app.project_documents(project):
            if ids is not None and doc.id not in ids:
                continue
            spec, _ = app.document_rules(project, doc, base)
            if not (doc.extraction_dir(spec.name) / "manifest.json").exists():
                continue
            corrected, _ = app.document_index(doc, spec, corr)
            original, _ = app.document_index(doc, spec, None)
            before = {tuple(r[SOURCE_KEY]): r for r in original.rows}
            for r in corrected.rows:
                p, position = r[SOURCE_KEY]
                if page is not None and p != page:
                    continue
                values = {c: r.get(c, "") for c in base.output_columns}
                if needle and needle not in verifiche.norm(" ".join(values.values())):
                    continue
                old = before.get((p, position), {})
                out.append({"doc": doc.id, "title": doc.info.title, "page": p, "position": position,
                            "values": values, "changed": [c for c in base.output_columns
                                                          if old.get(c, "") != values.get(c, "")]})
        return {"columns": base.output_columns, "data_columns": [c.name for c in base.columns],
                "page_column": base.output.page_column, "total": len(out),
                "rows": out[max(0, offset): max(0, offset) + max(1, min(limit, 500))]}

    # ------------------------------------------------------------------ ⑤ risultati
    @api.get("/api/projects/{pid}/results")
    def results(pid: str):
        project = project_or_404(pid)
        base = app.project_rules(project)
        result = app.export_project(project)
        if not result.documents:
            return {"available": False}
        level_order = {"errore": 0, "avviso": 1}
        anomalies = []
        for doc, r in result.documents:
            for a in r.index.anomalies:
                anomalies.append({"document": doc.id, "file": doc.info.source_filename, "level": a.level,
                                  "page": a.page, "row": a.csv_row, "column": a.column, "value": a.value,
                                  "problem": a.problem})
        anomalies.sort(key=lambda a: (level_order.get(a["level"], 2), a["file"], a["page"] or 0, a["row"] or 0))
        levels = {lvl: sum(1 for a in anomalies if a["level"] == lvl) for lvl in ("errore", "avviso", "info")}
        corr = correzioni.load(project)
        return {
            "available": True,
            "corrections": len(corr.rules) + len(corr.edits) + len(corr.deletions),
            "stats": result.index.stats,
            "documents": [{"id": d.id, "title": d.info.title, "file": d.info.source_filename,
                           "rows": r.index.stats.get("righe_finali", 0), "errors": r.index.stats.get("errori", 0),
                           "warnings": r.index.stats.get("avvisi", 0), "stale": r.stale,
                           "csv": r.csv_path.name} for d, r in result.documents],
            "not_indexed": [d.id for d in result.not_indexed],
            "stale": [d.id for d in result.stale],
            "columns": result.index.columns,
            "page_column": base.output.page_column,
            "source_column": base.output.source_column,
            "rows": result.index.rows[:MAX_ROWS_IN_VIEW],
            "anomalies": anomalies[:MAX_ROWS_IN_VIEW],
            "anomalies_total": len(anomalies),
            "anomalies_by_level": levels,
            "csv": result.csv_path.name,
        }

    @api.get("/api/projects/{pid}/download/{kind}")
    def download(pid: str, kind: str, doc: str | None = None):
        project = project_or_404(pid)
        out_dir = app.project_export_dir(project)
        if kind == "csv":
            path = out_dir / f"{project.id}.csv"
        elif kind == "anomalie":
            path = out_dir / f"{project.id}_anomalie.csv"
        elif kind == "documento" and doc:
            path = out_dir / "documenti" / f"{doc_of(project, doc).id}.csv"
        else:
            raise HTTPException(404, "File sconosciuto.")
        corrections = correzioni.corrections_path(project)
        if path.exists() and corrections.exists() and corrections.stat().st_mtime_ns > path.stat().st_mtime_ns:
            app.export_project(project)                     # correzioni più recenti del CSV: lo rigenero
        if not path.exists():
            raise HTTPException(404, "File non ancora prodotto: esegui l'indicizzazione o apri i risultati.")
        return FileResponse(path, filename=path.name, media_type="text/csv")

    @api.get("/api/projects/{pid}/search", response_class=HTMLResponse)
    def search_page(pid: str):
        from docanalyzer.indexing.search_page import build_search_page

        project = project_or_404(pid)
        result = app.export_project(project)
        path = build_search_page(app, project, result, pdf_link="/api/documents/{doc}/pdf#page={page}")
        return HTMLResponse(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ biblioteca
    def upload_to_temp(file: UploadFile, tmp: str) -> Path:
        name = Path(file.filename or "documento.pdf").name
        if not name.lower().endswith(".pdf"):
            raise HTTPException(400, f"{name}: il file deve essere un PDF.")
        target = Path(tmp) / name
        with open(target, "wb") as out:
            shutil.copyfileobj(file.file, out)
        return target

    def catalog_summary(doc: Document, card: LibraryCard, projects: list[Project]) -> dict[str, Any]:
        return {
            "id": doc.id, "title": doc.info.title, "source_filename": doc.info.source_filename,
            "page_count": doc.info.page_count, "added_at": doc.info.added_at,
            "folder": card.folder, "tags": card.tags, "description": card.description,
            "fields": len(card.fields), "collections": len(card.collections),
            "to_index": len(card.pages_with_tag("dati")), "has_guide": bool(card.guide.strip()),
            "analyzed": card.analyzed,
            "proposals": sum(1 for a in list_analyses(doc) if a.status == "nuova"),
            "projects": [{"id": p.id, "name": p.info.name} for p in projects if doc.id in p.info.documents],
        }

    def docs_from_body(body: dict) -> list[Document]:
        ids = body.get("ids") or []
        if not isinstance(ids, list) or not ids:
            raise ValueError("Seleziona almeno un catalogo.")
        return [app.documents.get(str(i)) for i in ids]

    @api.get("/api/library/catalogs")
    def library_overview():
        """Tutta la biblioteca in una risposta: filtri e ricerca li fa il browser."""
        projects = app.projects.list()
        docs = app.documents.list()
        cards = [app.library.card(d) for d in docs]
        tags: dict[str, int] = {}
        for card in cards:
            for t in card.tags:
                key = next((k for k in tags if k.casefold() == t.casefold()), t)
                tags[key] = tags.get(key, 0) + 1
        return {
            "folders": app.library.folders(cards),
            "tags": [{"name": k, "count": v} for k, v in sorted(tags.items(), key=lambda x: x[0].casefold())],
            "page_tags": [{"id": k, "label": v[0], "help": v[1]} for k, v in PAGE_TAGS.items()],
            "catalogs": [catalog_summary(d, c, projects) for d, c in zip(docs, cards, strict=True)],
        }

    @api.post("/api/library/catalogs")
    def library_upload(file: UploadFile = File(...), folder: str = Form("")):
        with tempfile.TemporaryDirectory() as tmp:
            target = upload_to_temp(file, tmp)
            try:
                doc = app.add_to_library(target, folder=folder)
                already = False
            except DuplicateDocumentError as e:
                doc = app.documents.get(e.existing.id)
                already = True
        card = app.library.card(doc)
        result = catalog_summary(doc, card, app.projects.list())
        result.update(already_present=already, scanned=not already and not has_text_layer(doc.pdf_path))
        return result

    @api.get("/api/library/catalogs/{doc_id}")
    def library_catalog(doc_id: str):
        doc = app.documents.get(doc_id)
        card = app.library.card(doc)
        return {**catalog_summary(doc, card, app.projects.list()), **card.model_dump(),
                "key_pages": card.key_pages(),
                "scanned": not has_text_layer(doc.pdf_path), "size_mb": round(doc.pdf_path.stat().st_size / 2**20, 1)}

    @api.put("/api/library/catalogs/{doc_id}")
    def library_update_card(doc_id: str, body: dict = Body(...)):
        """Aggiorna titolo, descrizione, tag, dati presenti, cartella e guida (solo le voci presenti)."""
        doc = app.documents.get(doc_id)
        card = app.library.card(doc)
        if "title" in body:
            title = " ".join(str(body["title"] or "").split())
            if not title:
                raise ValueError("Il titolo non può essere vuoto.")
            doc.info.title = title
            doc.save()
        if "description" in body:
            card.description = str(body["description"] or "").strip()
        if "tags" in body:
            card.tags = [str(t) for t in body["tags"] or []]
        if "folder" in body:
            card.folder = str(body["folder"] or "")
        if "guide" in body:
            text = str(body["guide"] or "").strip()
            card.guide = text + "\n" if text else ""
        if "fields" in body:
            fields = [FieldDef.model_validate(f) for f in body["fields"] or [] if str(f.get("name", "")).strip()]
            names = [f.name.casefold() for f in fields]
            if len(names) != len(set(names)):
                raise ValueError("Ci sono due campi con lo stesso nome.")
            card.fields = fields
        app.library.save_card(doc, card)
        return library_catalog(doc_id)

    @api.delete("/api/library/catalogs/{doc_id}")
    def library_delete(doc_id: str):
        doc = app.documents.get(doc_id)
        app.delete_document(doc)
        return {"deleted": doc.id}

    @api.post("/api/library/catalogs/{doc_id}/collections")
    def collection_add(doc_id: str, body: dict = Body(...)):
        doc = app.documents.get(doc_id)
        app.library.add_collection(doc, int(body["start"]), int(body["end"]), str(body.get("tag", "")),
                                   str(body.get("comment") or ""))
        return library_catalog(doc_id)

    @api.put("/api/library/catalogs/{doc_id}/collections/{coll_id}")
    def collection_update(doc_id: str, coll_id: str, body: dict = Body(...)):
        doc = app.documents.get(doc_id)
        app.library.update_collection(doc, coll_id, int(body["start"]), int(body["end"]),
                                      str(body.get("tag", "")), str(body.get("comment") or ""))
        return library_catalog(doc_id)

    @api.delete("/api/library/catalogs/{doc_id}/collections/{coll_id}")
    def collection_delete(doc_id: str, coll_id: str):
        app.library.remove_collection(app.documents.get(doc_id), coll_id)
        return library_catalog(doc_id)

    @api.post("/api/library/move")
    def library_move(body: dict = Body(...)):
        return {"folder": app.library.move(docs_from_body(body), str(body.get("folder") or ""))}

    @api.post("/api/library/tags")
    def library_tags(body: dict = Body(...)):
        app.library.retag(docs_from_body(body), add=body.get("add") or [], remove=body.get("remove") or [])
        return {"ok": True}

    @api.post("/api/library/folders")
    def folder_create(body: dict = Body(...)):
        return {"folder": app.library.create_folder(str(body.get("path") or ""))}

    @api.put("/api/library/folders")
    def folder_rename(body: dict = Body(...)):
        return {"folder": app.library.rename_folder(str(body.get("path") or ""), str(body.get("new_path") or ""))}

    @api.delete("/api/library/folders")
    def folder_delete(path: str):
        app.library.delete_folder(path)
        return {"deleted": path}

    # ------------------------------------------------------------------ analisi con Gemini
    prompts = PromptStore(app.workspace)
    guide_prompts = PromptStore(app.workspace, prompt="library_guide", filename="guide_prompt.md")

    def analysis_job_key(doc: Document) -> str:
        return f"lib:{doc.id}"

    def analysis_request(doc: Document, body: dict) -> tuple[list[int] | None, str, bool, str]:
        if body.get("whole"):
            pages = None
        else:   # attenzione: per parse_page_ranges il testo vuoto vuol dire "tutte le pagine"
            pages = parse_page_ranges(str(body.get("pages") or ""), doc.info.page_count) or []
        return (check_pages(doc, pages), str(body.get("instructions") or ""), bool(body.get("include_card", True)),
                str(body.get("guide_instructions") or ""))

    def analysis_view(a) -> dict[str, Any]:
        return {**a.model_dump(), "pages_text": a.pages_text, "guide_pages_text": a.guide_pages_text}

    def prompt_info(store: PromptStore) -> dict[str, Any]:
        return {"factory": store.factory(), "custom": store.custom(), "effective": store.effective()}

    def size_info(doc: Document, pages: list[int] | None) -> dict[str, Any]:
        size = attachment_size(doc, pages)
        count = doc.info.page_count if pages is None else len(pages)
        return {"pages": count, "pages_text": "PDF intero" if pages is None else format_pages(pages),
                "size_mb": round(size / 2**20, 1), "heavy": size > HEAVY_PDF_BYTES,
                "estimate_seconds": estimate_seconds(count)}

    @api.get("/api/library/analysis-prompt")
    def analysis_prompt():
        return prompt_info(prompts)

    @api.put("/api/library/analysis-prompt")
    def analysis_prompt_save(body: dict = Body(...)):
        prompts.save(str(body.get("text") or ""))
        return analysis_prompt()

    @api.get("/api/library/guide-prompt")
    def guide_prompt():
        return prompt_info(guide_prompts)

    @api.put("/api/library/guide-prompt")
    def guide_prompt_save(body: dict = Body(...)):
        guide_prompts.save(str(body.get("text") or ""))
        return guide_prompt()

    @api.get("/api/library/catalogs/{doc_id}/quick-pages")
    def analysis_quick_pages(doc_id: str):
        doc = app.documents.get(doc_id)
        return {"pages": format_pages(quick_pages(doc.info.page_count))}

    @api.post("/api/library/catalogs/{doc_id}/analysis/preview")
    def analysis_preview(doc_id: str, body: dict = Body(...)):
        """Prompt esatto della scheda e dimensione degli allegati, senza chiamare Gemini."""
        doc = app.documents.get(doc_id)
        pages, instructions, include_card, _ = analysis_request(doc, body)
        card = app.library.card(doc)
        guide = size_info(doc, guide_pages(doc, card, pages))
        return {
            "prompt": build_prompt(doc, card, instructions, pages, include_card),
            **size_info(doc, pages),
            "guide": guide,     # stima: le pagine chiave le deciderà la scheda proposta
        }

    @api.post("/api/library/catalogs/{doc_id}/analysis")
    def analysis_start(doc_id: str, body: dict = Body(...)):
        doc = app.documents.get(doc_id)
        pages, instructions, include_card, guide_instructions = analysis_request(doc, body)
        client = app.client()   # errore subito se mancano le chiavi

        def work(job):
            def progress(message: str) -> None:
                job.control.progress(0, 0, message)
            analysis = run_analysis(doc, app.library, client, instructions, pages, include_card, progress,
                                    guide_instructions=guide_instructions,
                                    cancelled=lambda: job.control.cancel.is_set())
            return {"analysis_id": analysis.id, "problems": analysis.problems, "guide_error": analysis.guide_error}

        label = f"Gemini analizza '{doc.info.title}' (scheda e guida)"
        return jobs.submit(analysis_job_key(doc), "analysis", label, work).to_dict()

    def guide_request(doc: Document, body: dict) -> tuple[list[int] | None, str]:
        if body.get("whole"):
            return None, str(body.get("instructions") or "")
        text = str(body.get("pages") or "").strip()
        pages = parse_page_ranges(text, doc.info.page_count) if text else []
        return pages, str(body.get("instructions") or "")

    @api.post("/api/library/catalogs/{doc_id}/guide/preview")
    def guide_preview(doc_id: str, body: dict = Body(...)):
        """Prompt della guida dalla scheda attuale e pagine inviate (scelte + pagine chiave)."""
        doc = app.documents.get(doc_id)
        extra, instructions = guide_request(doc, body)
        card = app.library.card(doc)
        pages = guide_pages(doc, card, extra)
        if pages is not None and not pages:
            raise ValueError("La scheda non ha pagine chiave (indice, legenda, esempi, dati): scegli le pagine "
                             "da mostrare a Gemini, oppure tutto il PDF.")
        return {"prompt": build_guide_prompt(doc, card, instructions, pages), **size_info(doc, pages)}

    @api.post("/api/library/catalogs/{doc_id}/guide")
    def guide_start(doc_id: str, body: dict = Body(...)):
        """Rigenera la guida dalla scheda attuale (solo la richiesta B): diventa una proposta."""
        doc = app.documents.get(doc_id)
        extra, instructions = guide_request(doc, body)
        client = app.client()

        def work(job):
            analysis = run_guide(doc, app.library, client, instructions, extra,
                                 lambda message: job.control.progress(0, 0, message))
            return {"analysis_id": analysis.id}

        return jobs.submit(analysis_job_key(doc), "guide", f"Gemini scrive la guida di '{doc.info.title}'",
                           work).to_dict()

    @api.get("/api/library/catalogs/{doc_id}/job")
    def analysis_job(doc_id: str):
        job = jobs.active_for(analysis_job_key(app.documents.get(doc_id)))
        return job.to_dict() if job else None

    @api.get("/api/library/catalogs/{doc_id}/analyses")
    def analyses(doc_id: str):
        return [analysis_view(a) for a in list_analyses(app.documents.get(doc_id))]

    @api.post("/api/library/catalogs/{doc_id}/analyses/{analysis_id}/apply")
    def analysis_apply(doc_id: str, analysis_id: str, body: dict = Body(...)):
        doc = app.documents.get(doc_id)
        apply_analysis(doc, app.library, get_analysis(doc, analysis_id), Selection.model_validate(body))
        return library_catalog(doc_id)

    @api.post("/api/library/catalogs/{doc_id}/analyses/{analysis_id}/dismiss")
    def analysis_dismiss(doc_id: str, analysis_id: str):
        doc = app.documents.get(doc_id)
        analysis = get_analysis(doc, analysis_id)
        analysis.status = "scartata"
        save_analysis(doc, analysis)
        return analysis_view(analysis)

    # ------------------------------------------------------------------ progetto guidato
    guided_prompts = PromptStore(app.workspace, prompt="library_guided", filename="guided_prompt.md")

    def guided_job_key(doc: Document) -> str:
        return f"guided:{doc.id}"

    def run_view(run: GuidedRun) -> dict[str, Any]:
        names = {p.id: p.info.name for p in app.projects.list()}
        data = run.model_dump()
        ids = [run.seed] + [c.document for c in run.result.candidates]
        data["catalogs"] = {}
        for doc_id in ids:
            try:
                doc = app.documents.get(doc_id)
            except DocumentError:
                data["catalogs"][doc_id] = {"id": doc_id, "title": doc_id, "missing": True, "collections": []}
                continue
            card = app.library.card(doc)
            data["catalogs"][doc_id] = {
                "id": doc.id, "title": doc.info.title, "folder": card.folder, "page_count": doc.info.page_count,
                "data": [f.name for f in card.fields], "missing": False, "has_guide": bool(card.guide.strip()),
                "collections": collections_view(card),
            }
        data["project"] = ({"id": run.project_id, "name": names[run.project_id]}
                           if run.project_id in names else None)
        return data

    @api.get("/api/library/guided-prompt")
    def guided_prompt():
        return prompt_info(guided_prompts)

    @api.put("/api/library/guided-prompt")
    def guided_prompt_save(body: dict = Body(...)):
        guided_prompts.save(str(body.get("text") or ""))
        return guided_prompt()

    @api.post("/api/library/catalogs/{doc_id}/guided/preview")
    def guided_preview(doc_id: str, body: dict = Body(...)):
        """Prompt esatto e cataloghi che verrebbero confrontati, senza chiamare Gemini."""
        doc = app.documents.get(doc_id)
        prepared = prepare_guided(app, doc, make_request(body), str(body.get("gemini_instructions") or ""))
        return {"prompt": prepared.prompt, "candidates": len(prepared.candidates),
                "not_elaborated": prepared.not_elaborated, "chars": len(prepared.prompt)}

    @api.post("/api/library/catalogs/{doc_id}/guided")
    def guided_start(doc_id: str, body: dict = Body(...)):
        doc = app.documents.get(doc_id)
        request, instructions = make_request(body), str(body.get("gemini_instructions") or "")
        prepare_guided(app, doc, request, instructions)          # errori leggibili prima di partire
        client = app.client()

        def work(job):
            run = run_guided(app, client, doc, request, instructions,
                             lambda message: job.control.progress(0, 0, message))
            return {"run_id": run.id, "problems": run.problems}

        return jobs.submit(guided_job_key(doc), "guided", f"Gemini cerca i cataloghi simili a '{doc.info.title}'",
                           work).to_dict()

    @api.post("/api/library/catalogs/{doc_id}/guided/direct")
    def guided_direct(doc_id: str, body: dict = Body(...)):
        """Crea il progetto con il solo catalogo di partenza, senza Gemini."""
        project = create_direct(app, app.documents.get(doc_id), make_request(body))
        return {"project": project_summary(project)}

    @api.get("/api/library/catalogs/{doc_id}/guided-job")
    def guided_job(doc_id: str):
        job = jobs.active_for(guided_job_key(app.documents.get(doc_id)))
        return job.to_dict() if job else None

    @api.get("/api/library/catalogs/{doc_id}/guided")
    def guided_runs(doc_id: str):
        names = {p.id: p.info.name for p in app.projects.list()}
        return [{"id": r.id, "created_at": r.created_at, "status": r.status, "name": r.request.name,
                 "candidates": len(r.result.candidates), "project": (
                     {"id": r.project_id, "name": names[r.project_id]} if r.project_id in names else None)}
                for r in list_runs(app.workspace, seed=app.documents.get(doc_id).id)]

    @api.get("/api/library/guided/{run_id}")
    def guided_get(run_id: str):
        return run_view(get_run(app.workspace, run_id))

    @api.post("/api/library/guided/{run_id}/project")
    def guided_project(run_id: str, body: dict = Body(...)):
        run = get_run(app.workspace, run_id)
        project = create_guided_project(
            app, run, name=str(body.get("name") or ""),
            documents=body.get("documents") if isinstance(body.get("documents"), list) else [])
        return {"project": project_summary(project), "run": run_view(run)}

    @api.get("/api/library/catalogs/{doc_id}/projects")
    def catalog_projects(doc_id: str):
        """I progetti che usano il PDF e lo stato della sua indicizzazione in ciascuno."""
        doc = app.documents.get(doc_id)
        items = app.document_in_projects(doc)
        for item in items:
            job = jobs.active_for(item["id"])
            item["job"] = job.label if job else None
        return items

    # ------------------------------------------------------------------ pagine dei PDF
    @api.get("/api/documents/{doc_id}/thumb/{page}")
    def thumbnail(doc_id: str, page: int):
        doc = app.documents.get(doc_id)
        path = render_thumbnail(doc.pdf_path, page, doc.folder / "thumbs" / f"page-{page:04d}.png")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=86400"})

    @api.get("/api/documents/{doc_id}/page/{page}")
    def page_image(doc_id: str, page: int):
        doc = app.documents.get(doc_id)
        if not 1 <= page <= doc.info.page_count:
            raise HTTPException(404, "Pagina inesistente.")
        images = render_pages(doc.pdf_path, doc.pages_dir, app.config.render.dpi, [page], show_progress=False)
        return FileResponse(images[page], media_type="image/png")

    @api.get("/api/documents/{doc_id}/pdf")
    def document_pdf(doc_id: str):
        doc = app.documents.get(doc_id)
        return FileResponse(doc.pdf_path, media_type="application/pdf",
                            headers={"Content-Disposition": f'inline; filename="{doc.info.source_filename}"'})

    # ------------------------------------------------------------------ lavori
    @api.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Operazione non trovata.")
        data = job.to_dict()
        data["usage"] = usage()
        # messaggi di servizio arrivati durante il lavoro (sovraccarico, quote, ...)
        data["events"] = [{"time": time.strftime("%H:%M:%S", time.localtime(e["ts"])), "text": e["text"]}
                          for e in app.events_since(job.started_ts)]
        return data

    @api.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        job = jobs.cancel(job_id)
        if job is None:
            raise HTTPException(404, "Operazione non trovata.")
        return job.to_dict()

    @api.get("/api/projects/{pid}/job")
    def project_job(pid: str):
        job = jobs.latest_for(pid)
        return job.to_dict() if job else None

    # ------------------------------------------------------------------ pagina
    @api.get("/")
    def index_html():
        page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        page = page.replace("{{stylesheets}}", stylesheet_links(app.config.ui.theme))
        return HTMLResponse(page, headers=NO_CACHE)

    @api.get("/api/theme")
    def theme_info():
        return {"theme": app.config.ui.theme, "available": available_themes()}

    api.mount("/static", _UiFiles(directory=STATIC_DIR), name="static")
    return api


def serve(app: App, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import threading
    import webbrowser

    import uvicorn

    url = f"http://{host}:{port}/"
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"Interfaccia disponibile su {url}  (chiudi con Ctrl+C)")
    uvicorn.run(create_app(app), host=host, port=port, log_level="warning")
