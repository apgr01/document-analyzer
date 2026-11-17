"""Progetto guidato: dalla scheda di un catalogo a un progetto, con l'aiuto di Gemini.

È l'unico modo di creare un progetto. L'utente parte da un catalogo e compila a mano la
**Tabella** che vuole ottenere (nome, descrizione, cosa rappresenta una riga, colonne con
descrizione e *dato di intestazione*, altre indicazioni). Gemini **non riscrive la tabella**:
riceve la tabella, la scheda del catalogo di partenza e le schede di **tutti i cataloghi
analizzati** della biblioteca (con descrizione o dati presenti), e risponde con:

- per il catalogo di partenza: quali colonne copre e quali sezioni contengono i dati;
- i **candidati** (*compatibile* / *parziale*) con motivo, colonne coperte e sezioni con i dati.

Come per l'analisi, il prompt ha le **indicazioni** modificabili e una **cornice** fissa con il
formato della risposta, che prevale. Cataloghi e sezioni hanno codici brevi (``C3``, ``C3/2``,
``P/1``) che nello schema sono degli ``enum``; la risposta è poi convalidata in modo rigoroso.
Il risultato è un **report** in ``data/library/guided/<id>.json``: l'utente sceglie i
cataloghi e le sezioni e crea il progetto (vedi ``App.create_project``). Nessun limite sul
numero di cataloghi inviati: si avvisa solo della quantità.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from docanalyzer.core.documents import Document
from docanalyzer.core.fileio import utc_now, write_json
from docanalyzer.core.gemini import LLMClient
from docanalyzer.core.library import PAGE_TAGS, LibraryCard, LibraryError
from docanalyzer.core.projects import Project, clean_columns
from docanalyzer.core.prompts import load_prompt, render_prompt
from docanalyzer.core.workspace import Workspace
from docanalyzer.library_analysis import InvalidAnswerError, _describe_errors, clean_instructions

if TYPE_CHECKING:  # solo per i tipi: app.py non importa questo modulo
    from docanalyzer.app import App

VERDICTS = ("compatibile", "parziale")
SKIPPED_TAGS = {"copertina", "vuota"}   # sezioni inutili per cercare i dati


class GuidedError(LibraryError):
    """Richiesta o azione non valida sul progetto guidato, con messaggio per l'utente."""


# ---------------------------------------------------------------------------------- richiesta
class GuidedRequest(BaseModel):
    """La Tabella che l'utente vuole, compilata a mano."""

    name: str = ""
    description: str = ""
    row: str = ""                                                  # cosa rappresenta una riga
    columns: list[dict] = Field(default_factory=list)              # name, description, header
    instructions: str = ""                                         # altre indicazioni

    def check(self) -> None:
        if not " ".join(self.row.split()) or not self.columns:
            raise GuidedError("Compila la tabella: cosa rappresenta una riga e almeno una colonna.")


def make_request(body: dict) -> GuidedRequest:
    """La richiesta dai dati del modulo, con le colonne ripulite (nomi unici)."""
    columns = body.get("columns") if isinstance(body.get("columns"), list) else []
    return GuidedRequest(name=" ".join(str(body.get("name") or "").split()),
                         description=str(body.get("description") or "").strip(),
                         row=" ".join(str(body.get("row") or "").split()),
                         columns=clean_columns(columns), instructions=str(body.get("instructions") or "").strip())


def describe_request(request: GuidedRequest) -> str:
    parts = []
    if request.description:
        parts.append(f"- A cosa serve: {request.description}")
    parts.append(f"- Ogni riga rappresenta: {request.row}")
    parts.append("- Colonne:\n" + "\n".join(
        f"  {i}. {c['name']}" + (f": {c['description']}" if c.get("description") else "")
        + (" (dato di intestazione: di solito vale per tutta la pagina o la sezione)" if c.get("header") else "")
        for i, c in enumerate(request.columns, 1)))
    if request.instructions:
        parts.append(f"- Altre indicazioni: {request.instructions}")
    return "\n".join(parts)


def _collections(card: LibraryCard) -> list[Any]:
    return [c for c in card.collections if c.tag not in SKIPPED_TAGS]


def describe_catalog(code: str, doc: Document, card: LibraryCard) -> str:
    lines = [f"### {code} — {doc.info.title} ({doc.info.page_count} pagine)"]
    if card.description.strip():
        lines.append(f"- Descrizione: {card.description.strip()}")
    if card.fields:
        lines.append("- Dati presenti: " + "; ".join(f.name + (f" ({f.description})" if f.description else "")
                                                     for f in card.fields))
    for n, c in enumerate(_collections(card), 1):
        pages = f"pagina {c.start}" if c.start == c.end else f"pagine {c.start}-{c.end}"
        lines.append(f"- Sezione {code}/{n}: {pages}, {PAGE_TAGS[c.tag][0]}" + (f" — {c.comment}" if c.comment else ""))
    return "\n".join(lines)


class Prepared(BaseModel):
    """Ciò che verrebbe inviato, senza chiamare Gemini."""

    prompt: str
    codes: dict[str, str]                       # "C1" -> id del documento ("P" = partenza)
    sections: dict[str, tuple[str, str]]        # "C1/2" -> (id del documento, id della collezione)
    candidates: list[str]                       # id dei cataloghi candidati
    not_elaborated: int                         # cataloghi esclusi perché non analizzati


def prepare(app: App, seed: Document, request: GuidedRequest, instructions: str) -> Prepared:
    request.check()
    others, excluded = [], 0
    for doc in app.documents.list():
        if doc.id == seed.id:
            continue
        card = app.library.card(doc)
        if card.analyzed:
            others.append((doc, card))
        else:
            excluded += 1
    codes = {"P": seed.id}
    sections: dict[str, tuple[str, str]] = {}
    seed_card = app.library.card(seed)
    for n, c in enumerate(_collections(seed_card), 1):
        sections[f"P/{n}"] = (seed.id, c.id)
    blocks = []
    for i, (doc, card) in enumerate(others, 1):
        code = f"C{i}"
        codes[code] = doc.id
        for n, c in enumerate(_collections(card), 1):
            sections[f"{code}/{n}"] = (doc.id, c.id)
        blocks.append(describe_catalog(code, doc, card))
    prompt = render_prompt(
        load_prompt("library_guided_frame"),
        instructions=clean_instructions(instructions) or load_prompt("library_guided").strip(),
        request=describe_request(request),
        seed=describe_catalog("P", seed, seed_card),
        count=len(others),
        catalogs="\n\n".join(blocks) if blocks
        else "(nessun altro catalogo analizzato: valuta solo quello di partenza)",
    ).strip() + "\n"
    return Prepared(prompt=prompt, codes=codes, sections=sections, candidates=[d.id for d, _ in others],
                    not_elaborated=excluded)


def guided_schema(prepared: Prepared) -> dict[str, Any]:
    def enum(values: list[str]) -> dict[str, Any]:
        return {"type": "string", "enum": values} if values else {"type": "string"}

    candidate_codes = [c for c in prepared.codes if c != "P"]
    seed_sections = [s for s in prepared.sections if s.startswith("P/")]
    other_sections = [s for s in prepared.sections if not s.startswith("P/")]
    strings = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "object",
        "properties": {
            "seed": {"type": "object", "properties": {
                "covered": strings, "missing": strings,
                "collections": {"type": "array", "items": enum(seed_sections)}, "notes": {"type": "string"}},
                "required": ["covered", "missing", "collections", "notes"]},
            "candidates": {"type": "array", "items": {"type": "object", "properties": {
                "catalog": enum(candidate_codes), "verdict": {"type": "string", "enum": list(VERDICTS)},
                "reason": {"type": "string"}, "covered": strings,
                "collections": {"type": "array", "items": enum(other_sections)}},
                "required": ["catalog", "verdict", "reason", "covered", "collections"]}},
            "notes": {"type": "string"},
        },
        "required": ["seed", "candidates", "notes"],
    }


# ---------------------------------------------------------------------------------- risposta
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Seed(_Strict):
    covered: list[str]
    missing: list[str]
    collections: list[str]
    notes: str


class _Candidate(_Strict):
    catalog: str
    verdict: str
    reason: str
    covered: list[str]
    collections: list[str]


class _Answer(_Strict):
    seed: _Seed
    candidates: list[_Candidate]
    notes: str


class CandidateResult(BaseModel):
    document: str
    verdict: str
    reason: str = ""
    covered: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)      # id delle collezioni della scheda


class GuidedResult(BaseModel):
    seed_covered: list[str] = Field(default_factory=list)
    seed_missing: list[str] = Field(default_factory=list)
    seed_collections: list[str] = Field(default_factory=list)
    seed_notes: str = ""
    candidates: list[CandidateResult] = Field(default_factory=list)
    notes: str = ""


def validate(raw: Any, prepared: Prepared, columns: list[str]) -> tuple[GuidedResult, list[str]]:
    """Struttura rigorosa (altrimenti :class:`InvalidAnswerError`), poi pulizia del contenuto.

    Non valida se: manca o avanza un campo, un tipo è sbagliato, un codice di catalogo o di sezione
    non esiste, un verdetto è diverso da compatibile/parziale, un candidato compare due volte o è il
    catalogo di partenza. Corretti e segnalati: nomi di colonna che non sono della tabella nelle
    coperture, sezioni attribuite al catalogo sbagliato.
    """
    if not isinstance(raw, dict):
        raise InvalidAnswerError([f"atteso un oggetto JSON, ricevuto {type(raw).__name__}"])
    try:
        answer = _Answer.model_validate(raw)
    except ValidationError as e:
        raise InvalidAnswerError(_describe_errors(e)) from e

    errors, seen = [], set()
    for i, c in enumerate(answer.candidates):
        if c.catalog == "P":
            errors.append(f"candidates.{i}: il catalogo di partenza non va tra i candidati")
        elif c.catalog not in prepared.codes:
            errors.append(f"candidates.{i}: codice di catalogo sconosciuto '{c.catalog}'")
        elif c.catalog in seen:
            errors.append(f"candidates.{i}: il catalogo {c.catalog} compare due volte")
        seen.add(c.catalog)
        if c.verdict not in VERDICTS:
            errors.append(f"candidates.{i}.verdict: '{c.verdict}' non è compatibile o parziale")
        errors += [f"candidates.{i}.collections: sezione sconosciuta '{s}'" for s in c.collections
                   if s not in prepared.sections]
    errors += [f"seed.collections: sezione sconosciuta '{s}'" for s in answer.seed.collections
               if s not in prepared.sections]
    if errors:
        raise InvalidAnswerError(errors)

    problems: list[str] = []
    by_norm = {" ".join(c.split()).casefold(): c for c in columns}

    def known(names: list[str], where: str) -> list[str]:
        out = []
        for n in names:
            key = " ".join(n.split()).casefold()
            if key in by_norm:
                out.append(by_norm[key])
            else:
                problems.append(f"{where}: '{n}' non è una colonna della tabella, ignorata")
        return out

    def sections_of(codes: list[str], doc_id: str, where: str) -> list[str]:
        out = []
        for code in codes:
            owner, coll_id = prepared.sections[code]
            if owner != doc_id:
                problems.append(f"{where}: la sezione {code} è di un altro catalogo, ignorata")
            elif coll_id not in out:
                out.append(coll_id)
        return out

    seed_id = prepared.codes["P"]
    result = GuidedResult(
        seed_covered=known(answer.seed.covered, "catalogo di partenza"),
        seed_missing=known(answer.seed.missing, "catalogo di partenza"),
        seed_collections=sections_of(answer.seed.collections, seed_id, "catalogo di partenza"),
        seed_notes=answer.seed.notes.strip(),
        candidates=[CandidateResult(document=prepared.codes[c.catalog], verdict=c.verdict, reason=c.reason.strip(),
                                    covered=known(c.covered, c.catalog),
                                    collections=sections_of(c.collections, prepared.codes[c.catalog], c.catalog))
                    for c in answer.candidates],
        notes=answer.notes.strip(),
    )
    return result, problems


# ---------------------------------------------------------------------------------- archivio
class GuidedRun(BaseModel):
    id: str
    created_at: str = Field(default_factory=utc_now)
    seed: str
    request: GuidedRequest
    instructions: str = ""
    candidates: list[str] = Field(default_factory=list)       # cataloghi inviati come candidati
    result: GuidedResult = Field(default_factory=GuidedResult)
    problems: list[str] = Field(default_factory=list)
    status: str = "valida"                                     # valida | non_valida
    raw: Any = None
    project_id: str | None = None


def runs_dir(workspace: Workspace) -> Path:
    return workspace.root / "library" / "guided"


def list_runs(workspace: Workspace, seed: str | None = None) -> list[GuidedRun]:
    folder = runs_dir(workspace)
    if not folder.exists():
        return []
    runs = [GuidedRun.model_validate(json.loads(p.read_text(encoding="utf-8"))) for p in folder.glob("*.json")]
    return sorted([r for r in runs if seed is None or r.seed == seed], key=lambda r: r.id, reverse=True)


def get_run(workspace: Workspace, run_id: str) -> GuidedRun:
    path = runs_dir(workspace) / f"{Path(run_id).name}.json"
    if not path.exists():
        raise GuidedError("Proposta non trovata.")
    return GuidedRun.model_validate(json.loads(path.read_text(encoding="utf-8")))


def save_run(workspace: Workspace, run: GuidedRun) -> None:
    write_json(runs_dir(workspace) / f"{run.id}.json", run.model_dump())


def run_guided(app: App, client: LLMClient, seed: Document, request: GuidedRequest, instructions: str,
               progress: Callable[[str], None] | None = None) -> GuidedRun:
    prepared = prepare(app, seed, request, instructions)
    stamp = utc_now().replace(":", "").replace("-", "").replace("+0000", "")
    existing = {r.id for r in list_runs(app.workspace)}
    run_id, n = stamp, 2
    while run_id in existing:
        run_id, n = f"{stamp}-{n}", n + 1
    base = {"id": run_id, "seed": seed.id, "request": request, "instructions": instructions,
            "candidates": prepared.candidates}
    if progress:
        progress(f"Gemini confronta la richiesta con {len(prepared.candidates)} cataloghi…")
    raw = client.generate_json(prepared.prompt, guided_schema(prepared))
    try:
        result, problems = validate(raw, prepared, [c["name"] for c in request.columns])
    except InvalidAnswerError as e:
        save_run(app.workspace, GuidedRun(**base, status="non_valida", problems=e.errors, raw=raw))
        raise
    run = GuidedRun(**base, result=result, problems=problems)
    save_run(app.workspace, run)
    return run


# ---------------------------------------------------------------------------------- creazione del progetto
def create_project(app: App, run: GuidedRun, name: str, documents: list[dict]) -> Project:
    """Crea il progetto dal report: la Tabella della richiesta, i PDF e le sezioni scelte.

    ``documents``: ``[{"id": ..., "collections": [...]}, ...]``, il catalogo di partenza compreso.
    """
    if run.status != "valida":
        raise GuidedError("Questa proposta non è valida (la risposta non rispettava il formato).")
    if run.project_id and app.projects.find(run.project_id):
        raise GuidedError(f"Il progetto di questa proposta esiste già ('{run.project_id}').")
    chosen = [d for d in documents if d.get("id")]
    if not any(d["id"] == run.seed for d in chosen):
        raise GuidedError("Il catalogo di partenza deve far parte del progetto.")
    docs = [app.documents.get(str(d["id"])) for d in chosen]
    request = run.request
    project = app.create_project(
        name or request.name, docs, row=request.row, columns=request.columns, description=request.description,
        instructions=request.instructions,
        sections={str(d["id"]): [str(c) for c in d.get("collections") or []] for d in chosen})
    run.project_id = project.id
    save_run(app.workspace, run)
    return project


def create_direct(app: App, seed: Document, request: GuidedRequest) -> Project:
    """Crea il progetto con il solo catalogo di partenza, senza chiedere a Gemini."""
    request.check()
    return app.create_project(request.name, [seed], row=request.row, columns=request.columns,
                              description=request.description, instructions=request.instructions)
