"""⑤ Verifiche/Elaborazione: controlli sui risultati dell'indicizzazione.

Tutte le verifiche lavorano sulle righe **corrette** (vedi ``correzioni.py``) e, tranne l'elenco
di riferimento, **senza Gemini**:

- ``copertura``  — ogni pagina inviata ha almeno una riga (o esattamente una); pagine fallite o
  mai elaborate;
- ``testo``      — i valori delle colonne scelte compaiono nel testo nativo della pagina della
  riga (su tutte le righe); se no, su quale altra pagina si trovano;
- ``riferimento``— un elenco che riporta tutte le entità (indice, sommario...) letto da Gemini
  sulle pagine di riferimento (1 richiesta per PDF), confrontato con il CSV: voci mancanti,
  voci solo nel CSV, pagine che non tornano (scarto costante tra pagina stampata e pagina del PDF);
- ``caratteri``  — caratteri "rotti" e simboli rari in una colonna;
- ``vuoti``      — righe con le colonne chiave o da controllare vuote;
- ``doppioni``   — la stessa chiave su più righe (nello stesso PDF o in PDF diversi).

I risultati stanno in ``data/projects/<id>/verifiche/``: ``risultati.json`` (per verifica e per
PDF, con una *firma* dei dati: se i risultati del PDF, le correzioni o le impostazioni cambiano,
la verifica risulta *superata*), ``accettate.json`` (le segnalazioni marcate "va bene così") e
``riferimento/<pdf>.json`` (l'elenco letto da Gemini, modificabile).
"""

from __future__ import annotations

import difflib
import hashlib
import json
import tempfile
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from docanalyzer import correzioni
from docanalyzer.core.documents import Document
from docanalyzer.core.fileio import read_json, utc_now, write_json
from docanalyzer.core.gemini import LLMClient
from docanalyzer.core.pdf_tools import all_page_texts, build_subset_pdf, page_mapping_text
from docanalyzer.core.projects import Project, ProjectError
from docanalyzer.core.prompts import load_prompt, render_prompt
from docanalyzer.core.render import format_pages, parse_page_ranges
from docanalyzer.indexing.assemble import SOURCE_KEY, AssembledIndex
from docanalyzer.indexing.extractor import load_page_results, selected_pages
from docanalyzer.indexing.spec import IndexingSpec
from docanalyzer.library_analysis import InvalidAnswerError, _describe_errors

if TYPE_CHECKING:
    from docanalyzer.app import App

CHECKS: dict[str, str] = {
    "copertura": "Copertura delle pagine",
    "testo": "Contenuto sulla pagina",
    "riferimento": "Elenco di riferimento",
    "caratteri": "Caratteri sospetti",
    "vuoti": "Valori vuoti",
    "doppioni": "Doppioni",
}
PAID_CHECKS = {"riferimento"}           # le altre non chiamano Gemini
CROSS_DOC_CHECKS = {"caratteri", "doppioni"}   # confrontano i PDF scelti tra loro
COVERAGE_MODES = ("almeno", "esattamente", "nessuno")
RARE_SHARE = 0.05       # "raro": compare al massimo nel 5% dei valori della colonna (o in uno solo)
SIMILARITY = 0.8
# simboli non ASCII comuni nei cataloghi: non sono sospetti
COMMON_SYMBOLS = set("°×±²³µØøÆæÅåßÄÖÜäöüÀÈÉÌÒÙàèéìòùÇç½¼¾€®™©–—’‘“”·…")


# ---------------------------------------------------------------------------------- utilità
def norm(text: Any) -> str:
    """Testo per il confronto: solo lettere e cifre, minuscole (``MX 260/C`` -> ``mx260c``)."""
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return "".join(ch for ch in text if ch.isalnum())


def item_id(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


def verifiche_dir(project: Project) -> Path:
    return project.folder / "verifiche"


def page_texts(doc: Document) -> dict[int, str]:
    """Testo nativo di tutte le pagine, estratto una volta e conservato su disco."""
    cache = doc.folder / "text" / "pagine.json"
    if cache.exists():
        data = read_json(cache)
        if len(data) == doc.info.page_count:
            return {int(k): v for k, v in data.items()}
    texts = all_page_texts(doc.pdf_path)
    write_json(cache, {str(k): v for k, v in texts.items()})
    return texts


def suspicious_char(ch: str) -> bool:
    """Caratteri "rotti" per natura: uso privato, sostitutivo, quadratini, controllo."""
    if ch in "�▯□■◻◼":
        return True
    code = ord(ch)
    if 0x2500 <= code <= 0x25FF:                        # disegno di riquadri e forme geometriche
        return True
    return unicodedata.category(ch) in ("Co", "Cn", "Cs", "Cc") and ch not in "\t\n\r"


def unusual_char(ch: str) -> bool:
    """Simboli non ASCII fuori dai comuni: sospetti solo se rari nella colonna."""
    return (not ch.isalnum() and not ch.isspace() and ord(ch) > 127 and ch not in COMMON_SYMBOLS)


# ---------------------------------------------------------------------------------- archivio
def _path(project: Project, name: str) -> Path:
    return verifiche_dir(project) / name


def load_results(project: Project) -> dict[str, dict[str, Any]]:
    path = _path(project, "risultati.json")
    return read_json(path) if path.exists() else {}


def save_results(project: Project, data: dict[str, dict[str, Any]]) -> None:
    write_json(_path(project, "risultati.json"), data)


def load_accepted(project: Project) -> set[str]:
    path = _path(project, "accettate.json")
    return set(read_json(path).get("ids", [])) if path.exists() else set()


def set_accepted(project: Project, ids: list[str], accepted: bool = True) -> set[str]:
    current = load_accepted(project)
    current = current | set(ids) if accepted else current - set(ids)
    write_json(_path(project, "accettate.json"), {"ids": sorted(current)})
    return current


def reference_path(project: Project, doc_id: str) -> Path:
    return verifiche_dir(project) / "riferimento" / f"{doc_id}.json"


def load_reference(project: Project, doc_id: str) -> dict[str, Any] | None:
    path = reference_path(project, doc_id)
    return read_json(path) if path.exists() else None


def save_reference(project: Project, doc_id: str, data: dict[str, Any]) -> None:
    write_json(reference_path(project, doc_id), data)


# ---------------------------------------------------------------------------------- dati di un PDF
@dataclass
class DocData:
    doc: Document
    spec: IndexingSpec
    index: AssembledIndex                    # righe corrette, con la provenienza
    results: dict[int, dict[str, Any]]       # risultati delle pagine (originali)
    expected: list[int]                      # pagine da indicizzare
    failed: dict[int, str]
    _texts: dict[int, str] | None = field(default=None, repr=False)

    @property
    def texts(self) -> dict[int, str]:
        if self._texts is None:
            self._texts = page_texts(self.doc)
        return self._texts


def indexed_spec(app: App, project: Project, doc: Document, base: IndexingSpec | None = None) -> IndexingSpec | None:
    """Le regole del PDF se ha già dei risultati (``None`` se non è ancora indicizzato)."""
    spec, _ = app.document_rules(project, doc, base)
    return spec if (doc.extraction_dir(spec.name) / "manifest.json").exists() else None


def doc_data(app: App, project: Project, doc: Document, base: IndexingSpec | None = None,
             corrections: correzioni.Corrections | None = None) -> DocData | None:
    """I dati di un PDF per le verifiche (``None`` se non è ancora indicizzato)."""
    spec = indexed_spec(app, project, doc, base)
    if spec is None:
        return None
    index, manifest = app.document_index(doc, spec, corrections if corrections is not None
                                         else correzioni.load(project))
    return DocData(doc, spec, index, load_page_results(doc, spec.name), selected_pages(doc, spec),
                   manifest.failed_pages())


def _corrections_for(corrections: correzioni.Corrections, doc_id: str | None) -> list[dict[str, Any]]:
    """Le correzioni che toccano un PDF (tutte con ``None``), per la firma delle verifiche."""
    return ([r.model_dump() for r in corrections.rules if doc_id is None or r.doc in (None, doc_id)]
            + [e.model_dump() for e in corrections.edits if doc_id is None or e.doc == doc_id]
            + [d.model_dump() for d in corrections.deletions if doc_id is None or d.doc == doc_id])


def signature(project: Project, doc: Document, spec: IndexingSpec, check: str,
              corrections: correzioni.Corrections | None = None) -> str:
    """Impronta di ciò che determina l'esito di una verifica su un PDF (senza rileggere le righe).

    Contano solo le correzioni di quel PDF; per caratteri e doppioni, che confrontano i PDF tra
    loro, tutte.
    """
    corrections = corrections if corrections is not None else correzioni.load(project)
    folder = doc.extraction_dir(spec.name)
    files = sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size)
                   for p in folder.glob("*.json"))
    info = project.info
    extra: dict[str, Any] = {"pages": spec.pages}
    if check == "copertura":
        extra["coverage"] = info.coverage
    if check in ("testo", "vuoti"):
        extra["columns"] = info.columns_to_check + info.key_columns
    if check in ("riferimento", "doppioni"):
        extra["keys"] = info.key_columns
    if check == "riferimento":
        ref = reference_path(project, doc.id)
        extra["reference"] = ref.stat().st_mtime_ns if ref.exists() else None
    corr = _corrections_for(corrections, None if check in CROSS_DOC_CHECKS else doc.id)
    blob = json.dumps([files, extra, corr], default=str, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def _row_ref(data: DocData, row: dict[str, Any]) -> dict[str, Any]:
    page, position = row[SOURCE_KEY]
    return {"doc": data.doc.id, "page": page, "position": position,
            "values": {c: row.get(c, "") for c in data.spec.output_columns}}


# ---------------------------------------------------------------------------------- V1 copertura
def check_coverage(project: Project, data: DocData) -> tuple[list[dict], dict]:
    mode = project.info.coverage
    per_page = Counter(row[SOURCE_KEY][0] for row in data.index.rows)
    items = []
    for page in data.expected:
        result = data.results.get(page) or {}
        n = per_page.get(page, 0)
        if page in data.failed:
            problem, detail = "fallita", data.failed[page]
        elif page not in data.results:
            problem, detail = "non elaborata", ""
        elif mode in ("almeno", "esattamente") and n == 0:
            problem, detail = "nessuna riga", ""
        elif mode == "esattamente" and n > 1:
            problem, detail = f"{n} righe", ""
        else:
            continue
        items.append({"id": item_id("copertura", data.doc.id, page, problem), "doc": data.doc.id, "page": page,
                      "problem": problem, "detail": detail, "rows": n, "summary": result.get("page_summary", "")})
    return items, {"pagine": len(data.expected), "problemi": len(items), "modo": mode}


# ---------------------------------------------------------------------------------- V2 testo
def check_text(project: Project, data: DocData) -> tuple[list[dict], dict]:
    columns = [c for c in project.info.columns_to_check if c in data.spec.output_columns]
    if not columns:
        raise ProjectError("Scegli le colonne da cercare nel testo (o segna una colonna chiave nella Tabella).")
    pages = {n: norm(t) for n, t in data.texts.items()}
    counts: Counter[str] = Counter()
    items = []
    for row in data.index.rows:
        page = row[SOURCE_KEY][0]
        values = {c: norm(row.get(c, "")) for c in columns if norm(row.get(c, ""))}
        if not values:
            counts["senza valori"] += 1
            continue
        text = pages.get(page, "")
        if not text:
            status, found, elsewhere = "non verificabile", {}, []
        else:
            found = {c: v in text for c, v in values.items()}
            elsewhere = []
            if all(found.values()):
                counts["confermata"] += 1
                continue
            elsewhere = sorted((n for n, t in pages.items() if n != page and all(v in t for v in values.values())),
                               key=lambda n: (abs(n - page), n))[:5]
            status = "altra pagina" if elsewhere else "parziale" if any(found.values()) else "non trovata"
        counts[status] += 1
        ref = _row_ref(data, row)
        items.append({"id": item_id("testo", data.doc.id, ref["page"], ref["position"], *values.values()),
                      **ref, "status": status, "columns": columns,
                      "missing": [c for c, ok in found.items() if not ok], "elsewhere": elsewhere})
    total = sum(counts.values())
    return items, {"righe": total, **counts, "problemi": len(items)}


# ---------------------------------------------------------------------------------- V3 riferimento
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def reference_pages(app: App, project: Project, doc: Document) -> list[int]:
    """Le pagine dell'elenco di riferimento: quelle scelte, altrimenti le collezioni *Indice*."""
    chosen = project.settings_for(doc.id).reference_pages
    if chosen:
        return parse_page_ranges(chosen, doc.info.page_count)
    return app.library.card(doc).pages_with_tag("indice")


def _reference_schema(keys: dict[str, str]) -> dict[str, Any]:
    values = {"type": "object", "properties": {k: {"type": "string"} for k in keys.values()},
              "required": list(keys.values())}
    item = {"type": "object", "properties": {"values": values, "page": {"type": "string"}},
            "required": ["values", "page"]}
    return {"type": "object", "properties": {"items": {"type": "array", "items": item}, "notes": {"type": "string"}},
            "required": ["items", "notes"]}


def extract_reference(app: App, project: Project, doc: Document, client: LLMClient,
                      progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Una richiesta: Gemini trascrive l'elenco delle entità dalle pagine di riferimento."""
    keys_cols = project.info.key_columns
    if not keys_cols:
        raise ProjectError("Segna almeno una colonna come Chiave nella Tabella (passo ①).")
    pages = reference_pages(app, project, doc)
    if not pages:
        raise ProjectError(f"'{doc.info.title}': nessuna pagina di riferimento. Scegline nelle impostazioni "
                           "della verifica, o segna l'indice nella scheda del catalogo.")
    spec, guide = app.document_rules(project, doc)
    json_keys = {c: k for c, k in spec.json_keys().items() if c in keys_cols}
    described = {c.name: c.description for c in spec.columns}
    prompt = render_prompt(
        load_prompt("verify_reference"), row=spec.row,
        columns="\n".join(f"- `{json_keys[c]}` → {c}" + (f": {described[c]}" if described.get(c) else "")
                          for c in keys_cols),
        guide=guide.strip() or "(nessuna guida)", pages_note=page_mapping_text(pages, doc.info.page_count),
    )
    if progress:
        progress(f"Gemini legge l'elenco di riferimento di {doc.info.title} ({len(pages)} pagine)")
    with tempfile.TemporaryDirectory() as tmp:
        pdf = build_subset_pdf(doc.pdf_path, pages, Path(tmp) / "elenco.pdf")
        raw = client.generate_json(prompt, _reference_schema(json_keys), pdf=pdf)

    values_model = create_model("Valori", __base__=_Strict, **{k: (str, ...) for k in json_keys.values()})
    item_model = create_model("Voce", __base__=_Strict, values=(values_model, ...), page=(str, ...))
    answer_model = create_model("Elenco", __base__=_Strict, items=(list[item_model], ...), notes=(str, ...))
    if not isinstance(raw, dict):
        raise InvalidAnswerError([f"atteso un oggetto JSON, ricevuto {type(raw).__name__}"])
    try:
        answer = answer_model.model_validate(raw)
    except ValidationError as e:
        raise InvalidAnswerError(_describe_errors(e)) from e
    back = {k: c for c, k in json_keys.items()}
    items = [{"values": {back[k]: " ".join(str(v).split()) for k, v in it.values.model_dump().items()},
              "page": it.page.strip()} for it in answer.items]
    data = {"pages": format_pages(pages), "items": [i for i in items if any(norm(v) for v in i["values"].values())],
            "notes": answer.notes.strip(), "created_at": utc_now(), "edited": False}
    save_reference(project, doc.id, data)
    return data


def _key(values: dict[str, Any], columns: list[str]) -> tuple[str, ...]:
    return tuple(norm(values.get(c, "")) for c in columns)


def _similar(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    ja, jb = "|".join(a), "|".join(b)
    if min(len(ja), len(jb)) >= 3 and (ja in jb or jb in ja):
        return True
    return difflib.SequenceMatcher(None, ja, jb).ratio() >= SIMILARITY


def check_reference(project: Project, data: DocData) -> tuple[list[dict], dict]:
    columns = project.info.key_columns
    if not columns:
        raise ProjectError("Segna almeno una colonna come Chiave nella Tabella (passo ①).")
    reference = load_reference(project, data.doc.id)
    if reference is None:
        raise ProjectError(f"'{data.doc.info.title}': manca l'elenco di riferimento (va letto con Gemini).")
    # si confrontano solo le colonne chiave che l'elenco riporta: un indice dei motori non ha i
    # codici, anche se la chiave della riga è motore + codice
    listed = [c for c in columns if any(norm(it["values"].get(c, "")) for it in reference.get("items", []))]
    columns = listed or columns
    csv_rows: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for row in data.index.rows:
        key = _key(row, columns)
        if any(key):
            csv_rows[key].append(row)
    ref_items: dict[tuple[str, ...], dict] = {}
    for it in reference.get("items", []):
        key = _key(it["values"], columns)
        if any(key):
            ref_items.setdefault(key, it)

    items = []
    matched = [k for k in ref_items if k in csv_rows]
    # scarto tra pagina stampata nell'elenco e pagina del PDF: il più frequente tra le voci trovate
    diffs = {}
    for k in matched:
        printed = "".join(ch for ch in str(ref_items[k].get("page", "")) if ch.isdigit())
        if printed:
            diffs[k] = min(int(r[SOURCE_KEY][0]) for r in csv_rows[k]) - int(printed)
    offset = None
    if len(diffs) >= 3:
        value, count = Counter(diffs.values()).most_common(1)[0]
        if count >= max(3, len(diffs) // 2):
            offset = value
    for k, it in ref_items.items():
        if k in csv_rows:
            if offset is not None and k in diffs and diffs[k] != offset:
                pages = sorted({int(r[SOURCE_KEY][0]) for r in csv_rows[k]})
                expected = int("".join(ch for ch in str(it["page"]) if ch.isdigit())) + offset
                items.append({"id": item_id("riferimento", data.doc.id, "pagina", *k), "doc": data.doc.id,
                              "kind": "pagina", "values": it["values"], "printed": it["page"],
                              "pages": pages, "expected": expected})
            continue
        similar = [{"values": {c: csv_rows[s][0].get(c, "") for c in columns},
                    "pages": sorted({int(r[SOURCE_KEY][0]) for r in csv_rows[s]})}
                   for s in csv_rows if _similar(k, s)][:3]
        items.append({"id": item_id("riferimento", data.doc.id, "mancante", *k), "doc": data.doc.id,
                      "kind": "mancante", "values": it["values"], "printed": it.get("page", ""), "similar": similar})
    for k, rows in csv_rows.items():
        if k in ref_items or any(_similar(k, r) for r in ref_items):
            continue
        items.append({"id": item_id("riferimento", data.doc.id, "solo_csv", *k), "doc": data.doc.id,
                      "kind": "solo nel CSV", "values": {c: rows[0].get(c, "") for c in columns},
                      "pages": sorted({int(r[SOURCE_KEY][0]) for r in rows})})
    summary = {"voci": len(ref_items), "trovate": len(matched),
               "mancanti": sum(i["kind"] == "mancante" for i in items),
               "solo_csv": sum(i["kind"] == "solo nel CSV" for i in items),
               "pagine_sbagliate": sum(i["kind"] == "pagina" for i in items),
               "scarto": offset, "problemi": len(items)}
    return items, summary


# ---------------------------------------------------------------------------------- V4 caratteri
def check_characters(project: Project, datas: list[DocData]) -> dict[str, tuple[list[dict], dict]]:
    """Su tutti i PDF scelti insieme: un simbolo è raro rispetto ai valori della sua colonna."""
    columns = [c.name for c in datas[0].spec.columns] if datas else []
    share: dict[str, Counter[str]] = {c: Counter() for c in columns}
    totals: Counter[str] = Counter()
    for data in datas:
        for row in data.index.rows:
            for c in columns:
                value = str(row.get(c, "") or "")
                if value:
                    totals[c] += 1
                    share[c].update(set(value))
    out = {}
    for data in datas:
        items = []
        for row in data.index.rows:
            for c in columns:
                value = str(row.get(c, "") or "")
                bad = sorted({ch for ch in value if suspicious_char(ch)
                              or (unusual_char(ch) and share[c][ch] <= max(1.0, RARE_SHARE * totals[c]))})
                if bad:
                    ref = _row_ref(data, row)
                    items.append({"id": item_id("caratteri", data.doc.id, ref["page"], ref["position"], c, value),
                                  **ref, "column": c, "value": value, "chars": bad})
        chars = Counter(ch for it in items for ch in it["chars"])
        out[data.doc.id] = (items, {"occorrenze": len(items), "caratteri": dict(chars), "problemi": len(items)})
    return out


# ---------------------------------------------------------------------------------- V5 vuoti
def check_empty(project: Project, data: DocData) -> tuple[list[dict], dict]:
    columns = list(dict.fromkeys(project.info.key_columns + project.info.columns_to_check))
    if not columns:
        raise ProjectError("Segna almeno una colonna come Chiave nella Tabella o scegli le colonne da controllare.")
    items = []
    for row in data.index.rows:
        empty = [c for c in columns if not str(row.get(c, "") or "").strip()]
        if empty:
            ref = _row_ref(data, row)
            items.append({"id": item_id("vuoti", data.doc.id, ref["page"], ref["position"], *empty), **ref,
                          "empty": empty})
    return items, {"righe": len(data.index.rows), "problemi": len(items), "colonne": columns}


# ---------------------------------------------------------------------------------- V6 doppioni
def check_duplicates(project: Project, datas: list[DocData]) -> dict[str, tuple[list[dict], dict]]:
    columns = project.info.key_columns
    if not columns:
        raise ProjectError("Segna almeno una colonna come Chiave nella Tabella (passo ①).")
    groups: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for data in datas:
        for row in data.index.rows:
            key = _key(row, columns)
            if any(key):
                groups[key].append(_row_ref(data, row))
    out: dict[str, tuple[list[dict], dict]] = {d.doc.id: ([], {}) for d in datas}
    for key, refs in groups.items():
        if len(refs) < 2:
            continue
        docs = sorted({r["doc"] for r in refs})
        item = {"id": item_id("doppioni", *key), "key": {c: refs[0]["values"].get(c, "") for c in columns},
                "occurrences": [{"doc": r["doc"], "page": r["page"], "position": r["position"]} for r in refs],
                "same_pdf": len(docs) == 1}
        for doc_id in docs:
            out[doc_id][0].append({**item, "doc": doc_id})
    return {doc_id: (items, {"gruppi": len(items), "problemi": len(items)}) for doc_id, (items, _) in out.items()}


def references_to_read(app: App, project: Project, doc_ids: list[str] | None = None,
                       reread: bool = False) -> list[Document]:
    """I PDF indicizzati (tra quelli scelti) il cui elenco di riferimento va letto con Gemini.

    Controlla subito colonne chiave e pagine di riferimento, così l'errore arriva prima di avviare il lavoro.
    """
    base = app.project_rules(project)
    docs = [d for d in app.project_documents(project) if (doc_ids is None or d.id in doc_ids)
            and indexed_spec(app, project, d, base) is not None
            and (reread or load_reference(project, d.id) is None)]
    if docs and not project.info.key_columns:
        raise ProjectError("Segna almeno una colonna come Chiave nella Tabella (passo ①).")
    for doc in docs:
        if not reference_pages(app, project, doc):
            raise ProjectError(f"'{doc.info.title}': nessuna pagina di riferimento. Scegline nelle impostazioni "
                               "delle verifiche, o segna l'indice nella scheda del catalogo.")
    return docs


# ---------------------------------------------------------------------------------- esecuzione
def run_check(app: App, project: Project, check: str, doc_ids: list[str] | None = None,
              client: LLMClient | None = None, reread: bool = False,
              progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Esegue una verifica sui PDF indicati (tutti quelli indicizzati se ``None``) e salva l'esito."""
    if check not in CHECKS:
        raise ProjectError(f"Verifica sconosciuta: '{check}'.")
    base = app.project_rules(project)
    corrections = correzioni.load(project)
    datas = []
    for doc in app.project_documents(project):
        if doc_ids is not None and doc.id not in doc_ids:
            continue
        data = doc_data(app, project, doc, base, corrections)
        if data is not None:
            datas.append(data)
    if not datas:
        raise ProjectError("Nessun PDF indicizzato tra quelli scelti.")
    if check == "riferimento":
        for data in datas:
            if reread or load_reference(project, data.doc.id) is None:
                if client is None:
                    raise ProjectError("Per leggere l'elenco di riferimento serve Gemini.")
                extract_reference(app, project, data.doc, client, progress)
    if progress:
        progress(f"Verifica: {CHECKS[check].lower()}")
    if check == "caratteri":
        outcome = check_characters(project, datas)
    elif check == "doppioni":
        outcome = check_duplicates(project, datas)
    else:
        fn = {"copertura": check_coverage, "testo": check_text, "riferimento": check_reference,
              "vuoti": check_empty}[check]
        outcome = {data.doc.id: fn(project, data) for data in datas}
    stored = load_results(project)
    entry = stored.setdefault(check, {})
    by_id = {d.doc.id: d for d in datas}
    for doc_id, (items, summary) in outcome.items():
        data = by_id[doc_id]
        entry[doc_id] = {"run_at": utc_now(), "signature": signature(project, data.doc, data.spec, check, corrections),
                         "summary": summary, "items": items}
    save_results(project, stored)
    return {doc_id: summary for doc_id, (_, summary) in outcome.items()}


def overview(app: App, project: Project) -> dict[str, Any]:
    """La matrice PDF × verifiche: stato, problemi aperti (non accettati), data."""
    stored = load_results(project)
    accepted = load_accepted(project)
    base = app.project_rules(project) if project.info.has_table else None
    corrections = correzioni.load(project)
    docs = []
    for doc in app.project_documents(project):
        spec = indexed_spec(app, project, doc, base) if base is not None else None
        cells = {}
        for check in CHECKS:
            entry = (stored.get(check) or {}).get(doc.id)
            if spec is None:
                cells[check] = {"state": "non indicizzato"}
            elif entry is None:
                cells[check] = {"state": "non eseguita"}
            else:
                open_items = [i for i in entry["items"] if i["id"] not in accepted]
                stale = entry["signature"] != signature(project, doc, spec, check, corrections)
                cells[check] = {"state": "superata" if stale else "ok" if not open_items else "problemi",
                                "problems": len(open_items), "accepted": len(entry["items"]) - len(open_items),
                                "run_at": entry["run_at"], "summary": entry["summary"]}
        reference = load_reference(project, doc.id)
        docs.append({"id": doc.id, "title": doc.info.title, "indexed": spec is not None, "checks": cells,
                     "reference_pages": format_pages(reference_pages(app, project, doc)),
                     "reference_chosen": project.settings_for(doc.id).reference_pages,
                     "reference": {"items": len(reference["items"]), "created_at": reference["created_at"],
                                   "edited": reference.get("edited", False)} if reference else None})
    return {"checks": [{"id": k, "label": v, "paid": k in PAID_CHECKS} for k, v in CHECKS.items()],
            "corrections": len(corrections.rules) + len(corrections.edits) + len(corrections.deletions),
            "documents": docs, "coverage": project.info.coverage,
            "check_columns": project.info.columns_to_check, "key_columns": project.info.key_columns,
            "columns": project.info.column_names}


def details(project: Project, check: str, doc_ids: list[str] | None = None) -> dict[str, Any]:
    """Le segnalazioni di una verifica per i PDF scelti, con quelle accettate marcate."""
    if check not in CHECKS:
        raise ProjectError(f"Verifica sconosciuta: '{check}'.")
    stored = (load_results(project).get(check) or {})
    accepted = load_accepted(project)
    items, summaries, seen = [], {}, set()
    for doc_id, entry in stored.items():
        if doc_ids is not None and doc_id not in doc_ids:
            continue
        summaries[doc_id] = {"summary": entry["summary"], "run_at": entry["run_at"]}
        for it in entry["items"]:
            if check == "doppioni" and it["id"] in seen:       # un gruppo su più PDF si mostra una volta
                continue
            seen.add(it["id"])
            items.append({**it, "accepted": it["id"] in accepted})
    return {"check": check, "label": CHECKS[check], "items": items, "summaries": summaries}
