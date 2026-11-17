"""Interfaccia a riga di comando: ``docanalyzer <comando>``.

Il programma si usa soprattutto dall'interfaccia grafica (``docanalyzer ui``): biblioteca,
analisi dei cataloghi, progetti e indicizzazione. Dalla riga di comando restano::

    docanalyzer ui                                # interfaccia grafica nel browser (consigliata)
    docanalyzer doctor                            # verifica che sia tutto pronto
    docanalyzer add Catalogo.pdf --folder Motori  # aggiunge PDF alla biblioteca
    docanalyzer list                              # cataloghi della biblioteca
    docanalyzer project list                      # progetti (si creano dall'interfaccia)
    docanalyzer project index <progetto>          # indicizza i PDF di un progetto
    docanalyzer project export <progetto>         # rigenera i CSV senza chiamare Gemini
    docanalyzer rag describe/build/ask            # domande sui cataloghi (RAG)

Ogni comando ha il suo aiuto: ``docanalyzer <comando> --help``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from docanalyzer import __version__, ui
from docanalyzer.app import App
from docanalyzer.core.config import ConfigError
from docanalyzer.core.documents import Document, DocumentError, DuplicateDocumentError
from docanalyzer.core.gemini import GeminiError, load_api_keys
from docanalyzer.core.page_runner import RunReport
from docanalyzer.core.paths import ENV_FILE, PROJECT_ROOT
from docanalyzer.core.projects import ProjectError
from docanalyzer.core.render import parse_page_ranges
from docanalyzer.indexing.extractor import SpecChangedError, selected_pages
from docanalyzer.indexing.spec import SpecError


# =====================================================================================
# Utility comuni
# =====================================================================================
def _print_report(report: RunReport, what: str) -> None:
    if report.requested == 0:
        ui.ok(f"{what}: nessuna pagina da elaborare (già tutte completate).")
        return
    ui.info(
        f"{what}: {report.succeeded} pagine completate, {len(report.failed)} fallite, "
        f"{report.not_attempted} non tentate (su {report.requested})."
    )
    if report.stopped_reason:
        ui.warn(f"Elaborazione interrotta: {report.stopped_reason}")
    if report.stopped_reason or report.failed or report.not_attempted:
        ui.hint("Rilancia lo stesso comando per riprendere: le pagine già fatte non vengono ripetute.")


def _resolve_docs(app: App, refs: list[str], use_all: bool) -> list[Document]:
    if use_all:
        docs = app.documents.list()
        if not docs:
            raise DocumentError("Il workspace non contiene documenti. Aggiungine uno con 'docanalyzer add'.")
        return docs
    if not refs:
        raise DocumentError("Indica almeno un documento (oppure --all per tutti).")
    return [app.documents.get(r) for r in refs]


# =====================================================================================
# Comandi
# =====================================================================================
def cmd_doctor(app: App, args: argparse.Namespace) -> int:
    ui.title("Verifica dell'ambiente")
    problems = 0

    ui.info(f"Versione docanalyzer: {__version__}   Python: {sys.version.split()[0]}")
    ui.info(f"Cartella del progetto: {PROJECT_ROOT}")
    ui.info(f"Workspace dati:        {app.workspace.root}")

    if app.simulated:
        ui.warn("Modalità SIMULATA attiva (DOCANALYZER_FAKE_GEMINI): Gemini non verrà chiamato.")
    keys = load_api_keys()
    if keys:
        parallel = app.config.indexing.max_workers or len(keys)
        ui.ok(f"Chiavi API Gemini trovate: {len(keys)} (richieste parallele: {parallel})")
    elif not app.simulated:
        if ENV_FILE.exists():
            ui.error(f"Il file {ENV_FILE} esiste ma non contiene chiavi API Gemini.")
            ui.hint("Aprilo e completa la riga  GEMINI_API_KEY_01=la-tua-chiave")
        else:
            ui.error(f"Nessuna chiave API Gemini: manca il file {ENV_FILE}.")
            ui.hint("Crealo copiando .env.example (Windows: copy .env.example .env) e inserisci la chiave.")
        ui.hint("Le chiavi si ottengono gratuitamente su https://aistudio.google.com/apikey")
        problems += 1

    ui.info(f"Modello: {app.config.gemini.model}   DPI rendering: {app.config.render.dpi}   "
            f"richieste/minuto per chiave: {app.config.gemini.requests_per_minute_per_key:g}")

    docs = app.documents.list()
    cards = [app.library.card(d) for d in docs]
    ui.info(f"Cataloghi nella biblioteca: {len(docs)} (analizzati: {sum(c.analyzed for c in cards)}, "
            f"con guida: {sum(bool(c.guide.strip()) for c in cards)})   Progetti: {len(app.projects.list())}")

    if args.online and keys and not app.simulated:
        ui.info("Provo una richiesta a Gemini...")
        try:
            reply = app.client().generate_text("Rispondi solo con la parola: pronto")
            ui.ok(f"Gemini risponde: {reply[:40]!r}")
        except GeminiError as e:
            ui.error(str(e))
            problems += 1

    if problems:
        ui.error("Trovato 1 problema da risolvere." if problems == 1 else f"Trovati {problems} problemi da risolvere.")
        return 1
    ui.ok("Tutto pronto.")
    if not args.online:
        ui.hint("Per provare anche una richiesta reale a Gemini: docanalyzer doctor --online")
    return 0


def cmd_add(app: App, args: argparse.Namespace) -> int:
    added = 0
    for pdf in args.pdf:
        try:
            doc = app.add_to_library(Path(pdf), folder=args.folder or "")
        except DuplicateDocumentError as e:
            ui.warn(str(e))
            continue
        ui.ok(f"Aggiunto '{doc.id}' ({doc.info.page_count} pagine) nella biblioteca"
              + (f", cartella {args.folder}." if args.folder else "."))
        _warn_if_scanned(doc)
        added += 1
    if added:
        ui.hint("Analizza i cataloghi e crea i progetti dall'interfaccia grafica: docanalyzer ui")
    return 0 if added or not args.pdf else 1


def _warn_if_scanned(doc: Document) -> None:
    from docanalyzer.core.pdf_tools import has_text_layer

    try:
        if not has_text_layer(doc.pdf_path):
            ui.info("  Il PDF non contiene testo selezionabile (probabilmente è una scansione):")
            ui.info("  Gemini leggerà solo le immagini delle pagine. Se il testo è piccolo, aumenta il DPI.")
    except Exception:
        pass


def cmd_list(app: App, args: argparse.Namespace) -> int:
    docs = app.documents.list()
    if not docs:
        ui.info("La biblioteca è vuota.")
        ui.hint('Aggiungi un PDF con: docanalyzer add "percorso/del/file.pdf"')
        return 0
    rows = []
    for d in docs:
        card = app.library.card(d)
        projects = ", ".join(p.id for p in app.projects.containing(d.id))
        rows.append([d.id, d.info.page_count, card.folder or "-", "sì" if card.analyzed else "-",
                     "sì" if card.guide.strip() else "-", projects or "-"])
    ui.table(["documento", "pagine", "cartella", "analizzato", "guida", "progetti"], rows)
    return 0


def cmd_remove(app: App, args: argparse.Namespace) -> int:
    doc = app.documents.get(args.doc)
    if not ui.ask_yes_no(f"Eliminare '{doc.id}' e tutti i suoi risultati?", default=False, assume_yes=args.yes):
        ui.info("Nessuna modifica.")
        return 0
    app.delete_document(doc)   # rifiuta se un progetto lo usa
    ui.ok(f"Documento '{doc.id}' eliminato.")
    return 0


def _print_usage(app: App) -> None:
    client = app._client
    usage = getattr(client, "usage", None)
    if usage is not None and usage.requests:
        ui.info(f"Consumo: {usage.describe()}.")


# --- RAG -----------------------------------------------------------------------------
def cmd_rag_describe(app: App, args: argparse.Namespace) -> int:
    from docanalyzer.rag.pipeline import describe_document

    exit_code = 0
    for doc in _resolve_docs(app, args.docs, args.all):
        ui.title(f"Descrizione delle pagine di '{doc.id}'")
        guide = app.guide_text(doc)
        if not guide.strip():
            ui.warn("Il catalogo non ha una guida all'indicizzazione: Gemini descriverà ogni pagina "
                    "senza sapere com'è fatto il resto del documento.")
            ui.hint("Per scriverla: analizza il catalogo nella biblioteca (docanalyzer ui).")
        pages = parse_page_ranges(args.pages, doc.info.page_count) if args.pages else None
        report = describe_document(doc, guide, app.client(), app.config, pages=pages, force=args.force)
        _print_report(report, "Descrizione")
        if report.stopped_reason or report.failed:
            exit_code = 1
    ui.hint("Poi aggiorna l'indice di ricerca con: docanalyzer rag build")
    return exit_code


def cmd_rag_build(app: App, args: argparse.Namespace) -> int:
    from docanalyzer.rag.pipeline import build_index
    from docanalyzer.rag.vector_index import VectorIndex

    index = VectorIndex(app.workspace.vector_index_dir, app.config.rag.collection_name)
    n = build_index(app.documents.list(), index)
    ui.ok(f"Indice aggiornato: {n} pagine ({index.count()} in totale).")
    return 0


def cmd_rag_ask(app: App, args: argparse.Namespace) -> int:
    from docanalyzer.rag.pipeline import QueryEngine
    from docanalyzer.rag.vector_index import VectorIndex

    index = VectorIndex(app.workspace.vector_index_dir, app.config.rag.collection_name)
    if index.count() == 0:
        ui.error("L'indice di ricerca è vuoto.")
        ui.hint("Prima: docanalyzer rag describe <documento>  e poi  docanalyzer rag build")
        return 1
    doc_id = app.documents.get(args.doc).id if args.doc else None
    answer = QueryEngine(index, app.client(), app.config).ask(args.question, doc_id)
    ui.title("Risposta")
    print(answer.text)
    if answer.sources:
        ui.info("\nFonti:")
        for s in answer.sources:
            ui.info(f"  - {s['source']}, pagina {s['page']}")
    return 0


def cmd_ui(app: App, args: argparse.Namespace) -> int:
    from docanalyzer.web.server import serve

    serve(app, port=args.port, open_browser=not args.no_browser)
    return 0


# --- progetti -------------------------------------------------------------------------
def cmd_project_list(app: App, args: argparse.Namespace) -> int:
    projects = app.projects.list()
    if not projects:
        ui.info("Nessun progetto. Si creano dall'interfaccia grafica (docanalyzer ui), dalla scheda di un catalogo.")
        return 0
    rows = []
    for p in projects:
        docs = app.project_documents(p)
        progress = app.project_progress(p)
        rows.append([p.id, p.info.name, len(docs), len(p.info.fields) or "-",
                     f"{progress['done']}/{progress['to_index']}" if progress else "tabella da completare"])
    ui.table(["progetto", "nome", "PDF", "colonne", "pagine indicizzate"], rows)
    return 0


def cmd_project_index(app: App, args: argparse.Namespace) -> int:
    from docanalyzer.prova import seed_index

    project = app.projects.get(args.project)
    base = app.project_rules(project)
    extractor = app.extractor()
    docs = app.project_documents(project)
    plans = []
    for doc in docs:
        spec, guide = app.document_rules(project, doc, base)
        try:
            manifest = extractor.open_manifest(doc, spec, guide, force=args.force)
        except SpecChangedError as e:
            ui.warn(f"{doc.id}: {e}")
            question = f"Rifare '{doc.id}' da capo con le regole attuali?"
            if not ui.ask_yes_no(question, default=False, assume_yes=args.yes):
                continue
            manifest = extractor.open_manifest(doc, spec, guide, force=True)
        if seed_index(app, project, doc, spec, guide, extractor):
            manifest = extractor.open_manifest(doc, spec, guide)
        todo = manifest.pages_to_process(app.config.indexing.max_page_attempts, only=selected_pages(doc, spec))
        if not guide.strip():
            ui.warn(f"{doc.id}: nessuna guida all'indicizzazione (analizza il catalogo nella biblioteca).")
        plans.append((doc, spec, guide, len(todo)))
    total = sum(n for *_, n in plans)
    ui.title(f"Indicizzazione del progetto '{project.info.name}' ({len(docs)} PDF)")
    send = app.send_options(project)
    if send["send"] == "insieme":
        limit = f", al massimo {send['max_pages']} pagine per richiesta" if send["max_pages"] else ""
        ui.info(f"Invio: le pagine di ogni PDF insieme (estratto ritagliato dal PDF){limit}.")
    else:
        ui.info("Invio: una pagina per richiesta.")
    for doc, _, _, n in plans:
        ui.info(f"  {doc.id}: {n} pagine da elaborare")
    if total and not ui.ask_yes_no(f"Avviare l'elaborazione di {total} pagine?", default=True, assume_yes=args.yes):
        return 1
    exit_code = 0
    for doc, spec, guide, n in plans:
        if not n:
            continue
        ui.info(f"\n{doc.id}:")
        report = extractor.run(doc, spec, guide, **send)
        _print_report(report, doc.id)
        if report.stopped_reason or report.failed:
            exit_code = 1
        if report.stopped_reason:
            break
    _print_usage(app)
    return _print_project_export(app, project) or exit_code


def _print_project_export(app: App, project) -> int:
    result = app.export_project(project)
    s = result.index.stats
    ui.ok(f"CSV unico del progetto: {result.csv_path}")
    ui.info(f"  righe: {s.get('righe_finali', 0)}   PDF indicizzati: {s.get('documenti_indicizzati', 0)}"
            f"/{s.get('documenti_totali', 0)}")
    for doc, r in result.documents:
        ui.info(f"  - {doc.id}: {r.index.stats.get('righe_finali', 0)} righe -> {r.csv_path.name}")
    for doc in result.not_indexed:
        ui.warn(f"{doc.id} non è ancora indicizzato.")
    for doc in result.stale:
        ui.warn(f"{doc.id}: le regole sono cambiate dopo l'indicizzazione; rilancia 'docanalyzer project index'.")
    if result.anomalies_path:
        ui.info(f"  anomalie: {result.anomalies_path}")
    if result.search_page:
        ui.info(f"  pagina di ricerca: {result.search_page}   (docanalyzer project search {project.id})")
    return 0


def cmd_project_search(app: App, args: argparse.Namespace) -> int:
    project = app.projects.get(args.project)
    result = app.export_project(project)
    if not result.search_page:
        ui.error("Il progetto non ha ancora risultati: indicizzalo prima.")
        return 1
    ui.ok(f"Pagina di ricerca: {result.search_page}")
    if not args.no_open and not ui.open_file(result.search_page):
        ui.info("Aprila con il browser.")
    return 0


def cmd_project_export(app: App, args: argparse.Namespace) -> int:
    return _print_project_export(app, app.projects.get(args.project))


# =====================================================================================
# Parser
# =====================================================================================
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docanalyzer",
        description="Elaborazione di cataloghi PDF con Gemini: biblioteca, indicizzazione in CSV e domande (RAG).",
        epilog="Aiuto su un comando: docanalyzer <comando> --help",
    )
    parser.add_argument("--version", action="version", version=f"docanalyzer {__version__}")
    parser.add_argument("--config", help="file di configurazione alternativo (default: configs/default.yaml)")
    sub = parser.add_subparsers(dest="command", metavar="<comando>")

    p = sub.add_parser("ui", help="INTERFACCIA GRAFICA nel browser (consigliata)")
    p.add_argument("--port", type=int, default=8765, help="porta del server locale (default 8765)")
    p.add_argument("--no-browser", action="store_true", help="non aprire il browser automaticamente")
    p.set_defaults(func=cmd_ui)

    p = sub.add_parser("doctor", help="verifica che sia tutto pronto (chiavi, cartelle, biblioteca)")
    p.add_argument("--online", action="store_true", help="prova anche una richiesta reale a Gemini")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("add", help="aggiunge uno o più PDF alla biblioteca")
    p.add_argument("pdf", nargs="+", help="percorso del file PDF (anche più di uno)")
    p.add_argument("--folder", help="cartella della biblioteca (es. Motori/Diesel; default: principale)")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="elenca i cataloghi della biblioteca")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("remove", help="elimina un catalogo dalla biblioteca, con i suoi risultati")
    p.add_argument("doc")
    p.add_argument("-y", "--yes", action="store_true", help="non chiedere conferma")
    p.set_defaults(func=cmd_remove)

    pp = sub.add_parser("project", help="progetti: indicizzazione e CSV (si creano dall'interfaccia grafica)")
    psub = pp.add_subparsers(dest="project_command", metavar="<azione>", required=True)
    p = psub.add_parser("list", help="elenca i progetti")
    p.set_defaults(func=cmd_project_list)
    p = psub.add_parser("index", help="indicizza tutti i PDF del progetto e produce il CSV unico")
    p.add_argument("project")
    p.add_argument("--force", action="store_true", help="rifai da capo anche le pagine già elaborate")
    p.add_argument("-y", "--yes", action="store_true", help="non chiedere conferme")
    p.set_defaults(func=cmd_project_index)
    p = psub.add_parser("export", help="rigenera il CSV unico e quelli per PDF (senza Gemini)")
    p.add_argument("project")
    p.set_defaults(func=cmd_project_export)
    p = psub.add_parser("search", help="genera e apre la pagina di ricerca HTML sul CSV unico")
    p.add_argument("project")
    p.add_argument("--no-open", action="store_true", help="non aprire il browser")
    p.set_defaults(func=cmd_project_search)

    # RAG
    rp = sub.add_parser("rag", help="domande in linguaggio naturale sui cataloghi (RAG)")
    rsub = rp.add_subparsers(dest="rag_command", metavar="<azione>", required=True)
    p = rsub.add_parser("describe", help="descrive le pagine dei cataloghi con Gemini (con la loro guida)")
    p.add_argument("docs", nargs="*", help="cataloghi da descrivere")
    p.add_argument("--all", action="store_true", help="tutti i cataloghi della biblioteca")
    p.add_argument("--pages", help="solo queste pagine, es. 1-20, 35 (default: tutte)")
    p.add_argument("--force", action="store_true", help="rifà anche le pagine già descritte")
    p.set_defaults(func=cmd_rag_describe)
    p = rsub.add_parser("build", help="aggiorna l'indice di ricerca con le descrizioni (senza Gemini)")
    p.set_defaults(func=cmd_rag_build)
    p = rsub.add_parser("ask", help="fa una domanda sui documenti")
    p.add_argument("question")
    p.add_argument("--doc", help="limita la ricerca a un documento")
    p.set_defaults(func=cmd_rag_ask)

    return parser


def main(argv: list[str] | None = None) -> int:
    ui.setup_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0

    try:
        from docanalyzer.core.config import load_config

        app = App(load_config(args.config))
        return args.func(app, args) or 0
    except (ConfigError, DocumentError, SpecError, GeminiError, FileNotFoundError, ValueError,
            ImportError, ProjectError) as e:
        ui.error(str(e))
        return 1
    except KeyboardInterrupt:
        ui.warn("Interrotto dall'utente. Il lavoro fatto finora è salvato.")
        return 130
    except Exception as e:  # errore imprevisto: messaggio breve, dettagli su richiesta
        if os.getenv("DOCANALYZER_DEBUG"):
            raise
        ui.error(f"Errore imprevisto: {type(e).__name__}: {e}")
        ui.hint("Per vedere i dettagli tecnici rilancia con la variabile d'ambiente DOCANALYZER_DEBUG=1")
        return 2


if __name__ == "__main__":
    sys.exit(main())
