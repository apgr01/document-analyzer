"""Prova di indicizzazione (passo ③ del progetto): poche pagine per catalogo, prima di tutto.

La prova usa esattamente le regole dell'indicizzazione vera (Tabella del progetto, guida del
catalogo, note del PDF), ma solo su un piccolo campione delle **pagine da indicizzare** di
ciascun PDF scelto. Serve a vedere subito se la tabella e la guida funzionano.

- **Campione** (``sample_pages``): di default 4 pagine per catalogo; prima le pagine
  d'esempio della biblioteca che sono anche da indicizzare, poi pagine distribuite nel resto.
  *Altre pagine* sceglie pagine non ancora provate.
- **Risultati** in ``data/projects/<id>/prova/<documento>/page-NNNN.json``; lo stato in
  ``prova/prova.json`` con l'*impronta* delle regole di ogni PDF: se tabella, guida o note
  cambiano dopo la prova, la prova di quel PDF risulta *superata*.
- **Riuso**: se l'impronta coincide ancora, le pagine provate contano come già fatte
  nell'indicizzazione vera (``seed_index``), così la prova non si paga due volte.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from docanalyzer.core.documents import Document
from docanalyzer.core.fileio import read_json, utc_now, write_json
from docanalyzer.core.page_runner import RunControl
from docanalyzer.core.projects import Project, ProjectError
from docanalyzer.core.render import parse_page_ranges
from docanalyzer.indexing.assemble import assemble, merge
from docanalyzer.indexing.export import write_index
from docanalyzer.indexing.extractor import Extractor, selected_pages
from docanalyzer.indexing.spec import IndexingSpec

if TYPE_CHECKING:
    from docanalyzer.app import App

DEFAULT_PAGES = 4


def prova_dir(project: Project) -> Path:
    return project.folder / "prova"


def state_path(project: Project) -> Path:
    return prova_dir(project) / "prova.json"


def load_state(project: Project) -> dict[str, Any]:
    path = state_path(project)
    if not path.exists():
        return {"documents": {}, "history": {}}
    data = read_json(path)
    data.setdefault("documents", {})
    data.setdefault("history", {})
    return data


def save_state(project: Project, state: dict[str, Any]) -> None:
    write_json(state_path(project), state)


def _spread(pool: list[int], count: int) -> list[int]:
    """``count`` pagine distribuite uniformemente in ``pool`` (tutte, se sono poche)."""
    if count >= len(pool):
        return list(pool)
    return [pool[int((i + 0.5) * len(pool) / count)] for i in range(count)]


def sample_pages(app: App, project: Project, doc: Document, count: int = DEFAULT_PAGES,
                 exclude: set[int] | None = None) -> list[int]:
    """Il campione di un PDF: prima le pagine d'esempio da indicizzare, poi distribuite nel resto."""
    if count < 1:
        return []
    total = doc.info.page_count
    pages = parse_page_ranges(project.settings_for(doc.id).pages, total) or list(range(1, total + 1))
    pool = [p for p in pages if p not in (exclude or set())]
    examples = set(app.library.card(doc).pages_with_tag("esempio"))
    first = [p for p in pool if p in examples][:count]
    rest = [p for p in pool if p not in first]
    return sorted(first + _spread(rest, count - len(first)))


def default_plan(app: App, project: Project, count: int = DEFAULT_PAGES, doc_ids: list[str] | None = None,
                 more: bool = False) -> dict[str, list[int]]:
    """Le pagine proposte per ogni PDF; con ``more`` evita le pagine già provate."""
    history = load_state(project)["history"] if more else {}
    plan = {}
    for doc in app.project_documents(project):
        if doc_ids is not None and doc.id not in doc_ids:
            continue
        plan[doc.id] = sample_pages(app, project, doc, count, set(history.get(doc.id, [])))
    return plan


def run_prova(app: App, project: Project, plan: dict[str, list[int]], control: RunControl | None = None) -> dict:
    """Esegue la prova sulle pagine indicate (solo estrazione, niente indicizzazione vera)."""
    base = app.project_rules(project)
    docs = {d.id: d for d in app.project_documents(project)}
    plan = {doc_id: sorted(set(pages)) for doc_id, pages in plan.items() if pages}
    if not plan:
        raise ProjectError("Scegli almeno un PDF e almeno una pagina per la prova.")
    for doc_id, pages in plan.items():
        if doc_id not in docs:
            raise ProjectError(f"Il documento '{doc_id}' non fa parte del progetto.")
        if pages[0] < 1 or pages[-1] > docs[doc_id].info.page_count:
            raise ProjectError(f"'{docs[doc_id].info.title}': pagine fuori dal documento.")
    extractor = app.extractor()
    control = control or RunControl()
    total = sum(len(p) for p in plan.values())
    done_before = 0
    state = load_state(project)
    summary = {"pages": 0, "failed": 0, "rows": 0}
    for doc_id, pages in plan.items():
        if control.cancel.is_set():
            break
        doc = docs[doc_id]
        spec, guide = app.document_rules(project, doc, base)

        def progress(done: int, _total: int, msg: str, offset=done_before, title=doc.info.title) -> None:
            control.report(offset + done, total, f"Prova su {title}" + (f" — {msg}" if "richiest" in msg else ""))

        report, results = extractor.preview(doc, spec, guide, pages, prova_dir(project) / doc.id,
                                            show_progress=False, control=RunControl(progress, control.cancel),
                                            **app.send_options(project))
        done_before += len(pages)
        state["documents"][doc.id] = {
            "pages": pages, "fingerprint": extractor.fingerprint(spec, guide), "tested_at": utc_now(),
            "failed": {str(k): v for k, v in report.failed.items()},
        }
        history = set(state["history"].get(doc.id, [])) | set(pages)
        state["history"][doc.id] = sorted(history)
        save_state(project, state)
        summary["pages"] += len(results)
        summary["failed"] += len(report.failed)
        summary["rows"] += sum(len(r.get("rows") or []) for r in results.values())
    state["created_at"] = utc_now()
    save_state(project, state)
    return summary


def prova_view(app: App, project: Project) -> dict[str, Any]:
    """La prova da mostrare: per ogni PDF provato, righe, riassunto delle pagine e anomalie."""
    state = load_state(project)
    if not project.info.has_table:
        return {"available": False, "documents": [], "history": state["history"]}
    base = app.project_rules(project)
    fingerprint = Extractor(None, app.config)  # type: ignore[arg-type]  (solo impronte)
    out: list[dict[str, Any]] = []
    parts = []
    for doc in app.project_documents(project):
        entry = state["documents"].get(doc.id)
        if not entry:
            continue
        spec, guide = app.document_rules(project, doc, base)
        folder = prova_dir(project) / doc.id
        results = {int(p.stem.split("-")[1]): read_json(p) for p in sorted(folder.glob("page-*.json"))}
        failed = {int(k): v for k, v in entry.get("failed", {}).items()}
        index = assemble(spec, results, doc.info.source_filename, entry["pages"], failed)
        parts.append(index)
        out.append({
            "id": doc.id, "title": doc.info.title, "pages": entry["pages"], "tested_at": entry.get("tested_at"),
            "stale": entry.get("fingerprint") != fingerprint.fingerprint(spec, guide),
            "failed": {str(k): v for k, v in failed.items()},
            "summaries": {str(n): r.get("page_summary", "") for n, r in results.items()},
            "notes": {str(n): r.get("notes", "") for n, r in results.items() if r.get("notes")},
            "rows": index.rows, "columns": index.columns,
            "anomalies": [{"level": a.level, "page": a.page, "row": a.csv_row, "column": a.column,
                           "value": a.value, "problem": a.problem} for a in index.anomalies],
        })
    csv = None
    if parts:
        merged = merge(base, parts, deduplicate=False)
        csv = prova_dir(project) / f"{project.id}_prova.csv"
        write_index(merged, base, csv)
    return {"available": bool(out), "documents": out, "history": state["history"],
            "page_column": base.output.page_column, "source_column": base.output.source_column,
            "csv": csv.name if csv else None,
            "created_at": state.get("created_at")}


def is_stale(app: App, project: Project) -> bool | None:
    """``None`` se non c'è una prova; ``True`` se le regole di qualche PDF provato sono cambiate."""
    state = load_state(project)
    if not state["documents"] or not project.info.has_table:
        return None
    base = app.project_rules(project)
    extractor = Extractor(None, app.config)  # type: ignore[arg-type]
    docs = {d.id: d for d in app.project_documents(project)}
    tested = [(docs[k], v) for k, v in state["documents"].items() if k in docs]
    if not tested:
        return None
    return any(v.get("fingerprint") != extractor.fingerprint(*app.document_rules(project, d, base))
               for d, v in tested)


def seed_index(app: App, project: Project, doc: Document, spec: IndexingSpec, guide: str,
               extractor: Extractor) -> int:
    """Riusa le pagine della prova nell'indicizzazione vera, se le regole sono le stesse."""
    entry = load_state(project)["documents"].get(doc.id)
    if not entry or entry.get("fingerprint") != extractor.fingerprint(spec, guide):
        return 0
    return extractor.seed(doc, spec, guide, prova_dir(project) / doc.id, only=set(selected_pages(doc, spec)))
