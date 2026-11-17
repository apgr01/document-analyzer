"""Indicizzazione completa con Gemini simulato."""

import re

import pytest

from docanalyzer.app import App
from docanalyzer.core.fake_gemini import FakeGeminiClient
from docanalyzer.core.gemini import IncompleteResponseError, QuotaExhaustedError
from docanalyzer.indexing.extractor import SpecChangedError
from docanalyzer.indexing.spec import IndexingSpec

SPEC = IndexingSpec.model_validate(
    {
        "name": "ricambi",
        "row": "un codice articolo",
        "columns": [
            {"name": "MOTORE", "context": True},
            {"name": "CODICE", "required": True},
        ],
    }
)


def page_of(prompt: str) -> int:
    return int(re.search(r"pagina (\d+) di", prompt).group(1))


def catalog_responder(request):
    """Simula un catalogo: pagina 1 copertina, poi due codici per pagina.
    L'intestazione MOTORE compare solo sulle pagine dispari."""
    n = page_of(request.prompt)
    if n == 1:
        return {"page_summary": "copertina", "page_context": {"motore": ""}, "rows": [], "notes": ""}
    context = {"motore": f"MOT-{n}"} if n % 2 else {"motore": ""}
    rows = [{"motore": "", "codice": f"C{n}-{i}"} for i in (1, 2)]
    return {"page_summary": "tabella", "page_context": context, "rows": rows, "notes": ""}


@pytest.fixture
def app(config):
    return App(config, client=FakeGeminiClient(catalog_responder, parallelism=3))


def test_full_indexing_and_export(app, pdf_factory):
    doc = app.documents.add(pdf_factory(pages=4))
    report = app.extractor().run(doc, SPEC, "guida", show_progress=False)
    assert report.succeeded == 4 and report.completed

    result = app.export(doc, SPEC, "guida", doc.folder / "out")
    text = result.csv_path.read_text(encoding="utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0] == "MOTORE,CODICE,PAGINA_PDF,FILE_ORIGINE"
    assert lines[1] == "MOT-3,C2-1,2,Catalogo Prova.pdf" or lines[1].startswith(",C2-1")
    # pagina 2 non ha intestazione e nessuna pagina precedente con motore: cella vuota
    # pagina 4 eredita il motore della pagina 3
    assert "MOT-3,C4-1,4,Catalogo Prova.pdf" in lines
    assert result.index.stats["righe_finali"] == 6
    # MOTORE vuoto non è un errore (non obbligatorio): nessuna anomalia
    assert result.anomalies_path is None

    # rilancio: niente da fare, nessuna nuova richiesta
    before = len(app.client().requests)
    assert app.extractor().run(doc, SPEC, "guida", show_progress=False).requested == 0
    assert len(app.client().requests) == before


def test_prompt_contains_guide_and_image(app, pdf_factory):
    doc = app.documents.add(pdf_factory(pages=2))
    app.extractor().run(doc, SPEC, "LA MIA GUIDA", pages="2", show_progress=False)
    (req,) = app.client().requests
    assert "LA MIA GUIDA" in req.prompt and req.kind == "json"
    assert req.images[0].name == "page-0002.png"


def test_failed_pages_are_retried_on_next_run(app, pdf_factory):
    doc = app.documents.add(pdf_factory(pages=3))
    flaky = {"fail": True}

    def responder(request):
        if page_of(request.prompt) == 2 and flaky["fail"]:
            raise RuntimeError("risposta illeggibile")
        return catalog_responder(request)

    app.client().responder = responder
    report = app.extractor().run(doc, SPEC, "p", show_progress=False)
    assert list(report.failed) == [2]
    anomalies = app.export(doc, SPEC, "p", doc.folder / "out").index.anomalies
    assert any(a.page == 2 and a.level == "errore" for a in anomalies)

    flaky["fail"] = False
    report = app.extractor().run(doc, SPEC, "p", show_progress=False)
    assert report.succeeded == 1 and report.completed


def test_quota_exhausted_stops_cleanly(app, pdf_factory):
    doc = app.documents.add(pdf_factory(pages=5))

    def responder(request):
        if page_of(request.prompt) >= 3:
            raise QuotaExhaustedError("quote finite")
        return catalog_responder(request)

    app.client().responder = responder
    report = app.extractor().run(doc, SPEC, "p", pages="1-2", show_progress=False)
    assert report.completed
    report = app.extractor().run(doc, SPEC, "p", show_progress=False)
    assert report.stopped_reason == "quote finite"
    assert not report.failed  # la quota non è colpa delle pagine: restano da fare


def test_spec_change_is_detected(app, pdf_factory):
    doc = app.documents.add(pdf_factory(pages=2))
    app.extractor().run(doc, SPEC, "guida", show_progress=False)
    changed = SPEC.model_copy(update={"instructions": "nuova regola"})
    with pytest.raises(SpecChangedError):
        app.extractor().run(doc, changed, "guida", show_progress=False)
    with pytest.raises(SpecChangedError):
        app.extractor().run(doc, SPEC, "guida modificata", show_progress=False)
    report = app.extractor().run(doc, changed, "guida", force=True, show_progress=False)
    assert report.succeeded == 2


def test_malformed_model_output_is_tolerated(app, pdf_factory):
    doc = app.documents.add(pdf_factory(pages=1))
    app.client().responder = lambda r: {"rows": [{"codice": 123}, "spazzatura", {"motore": None, "codice": "X"}]}
    app.extractor().run(doc, SPEC, "", show_progress=False)
    rows = app.export(doc, SPEC, "", doc.folder / "out").index.rows
    assert [r["CODICE"] for r in rows] == ["123", "X"]


def test_export_flags_stale_results(app, pdf_factory):
    doc = app.documents.add(pdf_factory(pages=1))
    app.extractor().run(doc, SPEC, "", show_progress=False)
    assert not app.export(doc, SPEC, "", doc.folder / "out").stale
    changed = SPEC.model_copy(update={"instructions": "nuova regola"})
    assert app.export(doc, changed, "", doc.folder / "out").stale


@pytest.mark.parametrize("mode", ["image+text", "image", "pdf"])
def test_input_modes(config, pdf_factory, mode):
    config.indexing.input = mode
    client = FakeGeminiClient(catalog_responder)
    app = App(config, client=client)
    doc = app.documents.add(pdf_factory(pages=2, prefix="CODICE RC777"))
    app.extractor().run(doc, SPEC, "p", pages="2", show_progress=False)
    (req,) = client.requests
    has_text = "TESTO ESTRATTO DAL PDF" in req.prompt and "CODICE RC777 2" in req.prompt
    assert has_text == (mode == "image+text")
    assert bool(req.images) == (mode != "pdf")
    assert (req.pdf_pages == 1) == (mode == "pdf")


def test_changing_input_mode_changes_fingerprint(config, pdf_factory):
    app = App(config, client=FakeGeminiClient(catalog_responder))
    doc = app.documents.add(pdf_factory(pages=1))
    app.extractor().run(doc, SPEC, "p", show_progress=False)
    config.indexing.input = "pdf"
    with pytest.raises(SpecChangedError):
        app.extractor().run(doc, SPEC, "p", show_progress=False)


def test_preview_does_not_touch_real_results(app, pdf_factory, tmp_path):
    doc = app.documents.add(pdf_factory(pages=4))
    out = tmp_path / "anteprima"
    report, results = app.extractor().preview(doc, SPEC, "p", [3, 2], out, show_progress=False)
    assert report.succeeded == 2 and sorted(results) == [2, 3]
    assert not doc.extraction_dir(SPEC.name).exists()
    report, results = app.extractor().preview(doc, SPEC, "p", [4], out, show_progress=False)
    assert sorted(results) == [4]   # ogni anteprima riparte da zero


def test_seed_reuses_preview_results(app, pdf_factory, tmp_path):
    doc = app.documents.add(pdf_factory(pages=4))
    out = tmp_path / "anteprima"
    app.extractor().preview(doc, SPEC, "p", [2, 3], out, show_progress=False)
    before = len(app.client().requests)
    assert app.extractor().seed(doc, SPEC, "p", out) == 2
    report = app.extractor().run(doc, SPEC, "p", show_progress=False)
    assert report.requested == 2                                  # solo le pagine 1 e 4
    assert len(app.client().requests) - before == 2
    assert app.extractor().seed(doc, SPEC, "p", out) == 0         # già fatte


def test_seed_only_selected_pages(app, pdf_factory, tmp_path):
    doc = app.documents.add(pdf_factory(pages=4))
    out = tmp_path / "prova"
    app.extractor().preview(doc, SPEC, "p", [1, 3], out, show_progress=False)
    assert app.extractor().seed(doc, SPEC, "p", out, only={3, 4}) == 1


# ------------------------------------------------------------------ più pagine per richiesta
def mapped_pages(prompt: str) -> list[int]:
    """Le pagine originali dell'estratto, dalla corrispondenza scritta nel prompt."""
    return [int(p) for p in re.findall(r"dell'estratto = pagina (\d+) del documento originale", prompt)]


def together_responder(skip=(), too_long_over=None):
    def respond(request):
        pages = mapped_pages(request.prompt)
        if too_long_over is not None and len(pages) > too_long_over:
            raise IncompleteResponseError("la risposta ha superato la lunghezza massima", reason="MAX_TOKENS")
        return {"pages": [{"page": n, "page_summary": "tabella", "page_context": {"motore": f"MOT-{n}"},
                           "rows": [{"motore": "", "codice": f"C{n}"}], "notes": ""}
                          for n in pages if n not in skip]}
    return respond


def test_together_sends_one_cut_pdf_per_document(app, pdf_factory):
    doc = app.documents.add(pdf_factory(pages=8))
    spec = SPEC.model_copy(update={"pages": "2-3, 5-7"})
    app.client().responder = together_responder()
    report = app.extractor().run(doc, spec, "LA GUIDA", show_progress=False, send="insieme")
    assert report.succeeded == 5 and report.completed
    (req,) = app.client().requests                       # una sola richiesta per tutto il PDF
    assert req.pdf_pages == 5 and not req.images          # estratto ritagliato: solo le pagine da indicizzare
    assert mapped_pages(req.prompt) == [2, 3, 5, 6, 7] and "LA GUIDA" in req.prompt
    assert "un elemento per OGNI pagina" in req.prompt and "{{" not in req.prompt
    assert req.json_schema["properties"]["pages"]["items"]["properties"]["page"]["minimum"] == 2
    rows = app.export(doc, spec, "LA GUIDA", doc.folder / "out").index.rows
    assert [(r["CODICE"], r["MOTORE"], r["PAGINA_PDF"]) for r in rows] == [
        (f"C{n}", f"MOT-{n}", str(n)) for n in (2, 3, 5, 6, 7)]


def test_together_max_pages_and_automatic_split(app, pdf_factory):
    doc = app.documents.add(pdf_factory(pages=6))
    app.client().responder = together_responder()
    app.extractor().run(doc, SPEC, "p", show_progress=False, send="insieme", max_pages=4)
    assert sorted(r.pdf_pages for r in app.client().requests) == [2, 4]       # in parallelo
    # risposta troppo lunga oltre 2 pagine: il gruppo si divide a metà finché basta
    other = app.documents.add(pdf_factory("Altro.pdf", pages=6, prefix="X"))
    app.client().requests.clear()
    app.client().responder = together_responder(too_long_over=2)
    report = app.extractor().run(other, SPEC, "p", show_progress=False, send="insieme")
    assert report.succeeded == 6 and report.completed
    assert [r.pdf_pages for r in app.client().requests] == [6, 3, 1, 2, 3, 1, 2]


def test_together_missing_pages_fail_and_can_be_redone_one_by_one(app, pdf_factory):
    doc = app.documents.add(pdf_factory(pages=4))
    app.client().responder = together_responder(skip={3})
    report = app.extractor().run(doc, SPEC, "p", show_progress=False, send="insieme")
    assert report.succeeded == 3 and "non ha restituito" in report.failed[3]
    # stessa impronta: si rifà solo la pagina mancante, anche una pagina per richiesta
    app.client().responder = catalog_responder
    app.client().requests.clear()
    report = app.extractor().run(doc, SPEC, "p", show_progress=False, send="pagina")
    assert report.succeeded == 1 and [page_of(r.prompt) for r in app.client().requests] == [3]


def test_together_errors(app, pdf_factory):
    doc = app.documents.add(pdf_factory(pages=3))
    # una sola pagina con una risposta comunque troppo lunga: fallisce con la spiegazione
    app.client().responder = together_responder(too_long_over=0)
    report = app.extractor().run(doc, SPEC, "p", show_progress=False, send="insieme")
    assert set(report.failed) == {1, 2, 3} and "lunghezza massima" in report.failed[1]
    # quota esaurita: niente pagine fallite, restano da fare
    other = app.documents.add(pdf_factory("Altro.pdf", pages=3, prefix="X"))

    def quota(request):
        raise QuotaExhaustedError("quote finite")

    app.client().responder = quota
    report = app.extractor().run(other, SPEC, "p", show_progress=False, send="insieme")
    assert report.stopped_reason == "quote finite" and not report.failed and report.not_attempted == 3


def test_together_preview_and_simulated_client(config, pdf_factory, tmp_path):
    app = App(config, client=FakeGeminiClient())                   # risposte segnaposto del client simulato
    doc = app.documents.add(pdf_factory(pages=5))
    report, results = app.extractor().preview(doc, SPEC, "p", [4, 2], tmp_path / "prova", show_progress=False,
                                              send="insieme")
    assert report.succeeded == 2 and sorted(results) == [2, 4] and results[2]["sent_with"] == 2
    assert len(app.client().requests) == 1
