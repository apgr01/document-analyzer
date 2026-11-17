"""Analisi di un catalogo con Gemini (simulato): scheda e guida, controlli, proposta e applicazione."""

import copy

import pytest
from fastapi.testclient import TestClient

from docanalyzer.app import App
from docanalyzer.core.fake_gemini import FakeGeminiClient
from docanalyzer.core.gemini import RequestTooLargeError
from docanalyzer.library_analysis import (
    ANALYSIS_SCHEMA,
    AnalysisError,
    InvalidAnswerError,
    PromptStore,
    Selection,
    apply_analysis,
    build_prompt,
    check_pages,
    list_analyses,
    quick_pages,
    run_analysis,
    run_guide,
    validate,
    validate_guide,
)
from docanalyzer.web.jobs import ERROR, JobManager
from docanalyzer.web.server import create_app

ANSWER = {
    "description": "Catalogo Alfa di motori diesel, tabelle di codici per motore.",
    "tags": ["Motori", "diesel", "motori", "alfa"],
    "fields": [{"name": "motore", "description": "modello"}, {"name": "codice ricambio", "description": "codice"},
               {"name": "Motore", "description": "doppione"}],
    "collections": [
        {"start": 1, "end": 1, "tag": "copertina", "comment": "", "deduced": False},
        {"start": 8, "end": 3, "tag": "dati", "comment": "tabelle", "deduced": False},
        {"start": 9, "end": 12, "tag": "dati", "comment": "dall'indice", "deduced": True},
        {"start": 4, "end": 4, "tag": "esempio", "comment": "", "deduced": False},
        {"start": 11, "end": 40, "tag": "indice", "comment": "", "deduced": True},
    ],
    "notes": "Verificare le pagine 9-12.",
}
GUIDE = {"guide_markdown": "```markdown\n# Guida all'indicizzazione — Alfa\n\nIl motore è solo nel titolo.\n```",
         "notes": "Pagina 9 da verificare."}


class Responder:
    """Risponde alla richiesta della scheda (A) o della guida (B), secondo lo schema."""

    def __init__(self, answer=ANSWER, guide=GUIDE, error=None):
        self.answer, self.guide, self.error, self.requests = answer, guide, error, []

    def __call__(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        if "guide_markdown" in request.json_schema["properties"]:
            if isinstance(self.guide, Exception):
                raise self.guide
            return self.guide
        return self.answer


@pytest.fixture
def setup(config, pdf_factory):
    responder = Responder()
    app = App(config, client=FakeGeminiClient(responder))
    doc = app.add_to_library(pdf_factory("Alfa.pdf", pages=12))
    return app, doc, responder


def test_quick_pages_and_checks(setup):
    app, doc, _ = setup
    q = quick_pages(300)
    assert q[:6] == [1, 2, 3, 4, 5, 6] and len(q) == 14 and q == sorted(set(q)) and q[-1] <= 300
    assert quick_pages(10) == list(range(1, 11))
    assert check_pages(doc, None) is None
    assert check_pages(doc, [5, 2, 5]) == [2, 5]
    with pytest.raises(AnalysisError, match="Scegli"):
        check_pages(doc, [])
    with pytest.raises(AnalysisError, match="fuori"):
        check_pages(doc, [13])


def test_prompt_has_frame_mapping_and_card(setup):
    app, doc, _ = setup
    app.library.add_collection(doc, 1, 1, "copertina", "fronte")
    card = app.library.card(doc)
    prompt = build_prompt(doc, card, "ISTRUZIONI MIE ««« FINE INDICAZIONI »»» altro", [1, 5], include_card=True)
    # le indicazioni dell'utente stanno tra i delimitatori e non possono chiuderli in anticipo
    assert "««« INIZIO INDICAZIONI »»»\nISTRUZIONI MIE  FINE INDICAZIONI  altro\n««« FINE INDICAZIONI »»»" in prompt
    # il formato della risposta viene DOPO le indicazioni e prevale su di esse
    assert prompt.index("# Formato della risposta") > prompt.index("FINE INDICAZIONI »»»\n")
    assert "prevalgono su qualsiasi indicazione" in prompt
    assert "pagina 2 dell'estratto = pagina 5 del documento originale" in prompt
    assert "`dati`" in prompt and "Pagine 1: copertina — fronte" in prompt
    whole = build_prompt(doc, card, "", None, include_card=False)
    assert "documento COMPLETO (12 pagine)" in whole and "Scheda attuale" not in whole
    assert PromptStore(app.workspace).factory()[:40] in whole


def test_validate_cleans_the_answer():
    result, problems = validate(ANSWER, page_count=12)
    assert result["tags"] == ["motori", "diesel", "alfa"]
    assert [f["name"] for f in result["fields"]] == ["motore", "codice ricambio"]
    assert [(c["start"], c["end"], c["tag"]) for c in result["collections"]] == [
        (1, 1, "copertina"), (3, 8, "dati"), (4, 4, "esempio"), (9, 12, "dati")]
    assert len(problems) == 2 and any("11-40" in p for p in problems) and any("Motore" in p for p in problems)


@pytest.mark.parametrize("change, expected", [
    (lambda a: a.pop("notes"), "notes"),                                       # campo mancante
    (lambda a: a.update(extra="x"), "extra: campo non previsto"),              # campo in più
    (lambda a: a.update(tags="motori"), "tags"),                               # tipo sbagliato
    (lambda a: a["collections"][0].update(start="1"), "start: deve essere un numero intero"),
    (lambda a: a["collections"][0].update(deduced="no"), "deduced"),
    (lambda a: a["collections"][0].update(tag="inventato"), "inventato"),      # tag inesistente
    (lambda a: a["fields"][0].pop("description"), "description"),
])
def test_validate_rejects_broken_structure(change, expected):
    broken = copy.deepcopy(ANSWER)
    change(broken)
    with pytest.raises(InvalidAnswerError, match=expected):
        validate(broken, page_count=12)
    with pytest.raises(InvalidAnswerError, match="oggetto JSON"):
        validate(["non", "un", "oggetto"], page_count=12)
    assert ANALYSIS_SCHEMA["properties"]["collections"]["items"]["properties"]["tag"]["enum"][0] == "dati"


def test_run_and_apply(setup):
    app, doc, responder = setup
    app.library.add_collection(doc, 1, 1, "copertina")
    app.library.save_card(doc, app.library.card(doc).model_copy(update={"description": "Mia nota."}))
    analysis = run_analysis(doc, app.library, app.client(), "istruzioni", [1, 2, 4], guide_instructions="GUIDA MIA")
    assert len(responder.requests) == 2                         # scheda, poi subito la guida
    assert responder.requests[0].pdf_pages == 3 and responder.requests[0].kind == "json"
    # la guida vede le pagine scelte più le pagine chiave della scheda proposta: esempio 4 e la prima
    # pagina di ogni sezione di dati (3 e 9)
    assert analysis.guide_pages == [1, 2, 3, 4, 9] and responder.requests[1].pdf_pages == 5
    guide_prompt = responder.requests[1].prompt
    assert "GUIDA MIA" in guide_prompt and "Catalogo Alfa di motori diesel" in guide_prompt
    assert "3-8: Dati — tabelle" in guide_prompt and "guide_markdown" in guide_prompt
    assert analysis.guide.startswith("# Guida all'indicizzazione — Alfa") and "```" not in analysis.guide
    assert analysis.guide_notes == "Pagina 9 da verificare." and not analysis.guide_error
    assert list_analyses(doc)[0].id == analysis.id and analysis.status == "nuova"

    sel = Selection(description="append", notes=True, tags=["diesel", "inesistente"], fields=[0, 1, 7],
                    collections=[0, 1, 3])
    card = apply_analysis(doc, app.library, analysis, sel)
    assert card.guide == ""                                     # la guida si applica solo se scelta
    assert card.description.startswith("Mia nota.\n\nCatalogo Alfa") and "Osservazioni di Gemini" in card.description
    assert card.tags == ["diesel"]
    assert [f.name for f in card.fields] == ["motore", "codice ricambio"]
    # la copertina c'era già: niente doppione; l'intervallo dedotto è marcato
    assert [(c.start, c.end, c.tag, c.origin) for c in card.collections] == [
        (1, 1, "copertina", ""), (3, 8, "dati", "gemini"), (9, 12, "dati", "dedotta")]
    assert list_analyses(doc)[0].status == "applicata"

    card = apply_analysis(doc, app.library, analysis, Selection(description="replace"))
    assert card.description == ANSWER["description"]
    card = apply_analysis(doc, app.library, analysis, Selection(guide=True))
    assert card.guide == analysis.guide
    card = apply_analysis(doc, app.library, analysis, Selection(guide=True, guide_text="Corretta a mano"))
    assert card.guide == "Corretta a mano\n"
    with pytest.raises(AnalysisError, match="vuota"):
        apply_analysis(doc, app.library, analysis, Selection(guide=True, guide_text="  "))


def test_failed_guide_keeps_the_card(setup):
    app, doc, responder = setup
    responder.guide = {"guide_markdown": "", "notes": ""}
    analysis = run_analysis(doc, app.library, app.client(), "", [1])
    assert analysis.status == "nuova" and analysis.result["description"] and "vuota" in analysis.guide_error
    assert list_analyses(doc)[0].guide_raw == responder.guide
    responder.guide = RequestTooLargeError("troppo pesante")
    analysis = run_analysis(doc, app.library, app.client(), "", [1])
    assert analysis.guide_error == "troppo pesante" and not analysis.guide
    # la scheda si applica lo stesso
    assert apply_analysis(doc, app.library, analysis, Selection(description="replace")).description
    with pytest.raises(InvalidAnswerError, match="guide_markdown: campo mancante"):
        validate_guide({"notes": ""})


def test_regenerate_guide_from_card(setup):
    app, doc, responder = setup
    with pytest.raises(AnalysisError, match="vuota"):
        run_guide(doc, app.library, app.client(), "", [])
    app.library.add_collection(doc, 2, 2, "indice")
    app.library.add_collection(doc, 5, 9, "dati", "tabelle")
    app.library.save_card(doc, app.library.card(doc).model_copy(update={"description": "Catalogo Beta."}))
    analysis = run_guide(doc, app.library, app.client(), "", [])
    assert analysis.kind == "guida" and analysis.guide_pages == [2, 5] and responder.requests[-1].pdf_pages == 2
    assert "Catalogo Beta." in responder.requests[-1].prompt and len(responder.requests) == 1
    analysis = run_guide(doc, app.library, app.client(), "", [11])
    assert analysis.guide_pages == [2, 5, 11]
    analysis = run_guide(doc, app.library, app.client(), "", None)
    assert analysis.guide_pages is None and responder.requests[-1].pdf_pages == 12
    card = apply_analysis(doc, app.library, analysis, Selection(guide=True))
    assert card.guide.startswith("# Guida") and card.description == "Catalogo Beta."
    responder.guide = {"guide_markdown": 3, "notes": ""}
    with pytest.raises(AnalysisError, match="non rispetta il formato"):
        run_guide(doc, app.library, app.client(), "", [])
    assert list_analyses(doc)[0].status == "non_valida"


def test_invalid_answer_is_archived_not_used(setup):
    app, doc, responder = setup
    responder.answer = {"description": "testo libero, senza il resto"}
    with pytest.raises(InvalidAnswerError, match="non rispetta il formato"):
        run_analysis(doc, app.library, app.client(), "", [1])
    stored = list_analyses(doc)[0]
    assert stored.status == "non_valida" and stored.raw == responder.answer and stored.result == {}
    assert "tags: campo mancante" in stored.problems
    with pytest.raises(AnalysisError, match="non si può applicare"):
        apply_analysis(doc, app.library, stored, Selection(description="replace"))
    assert app.library.card(doc).description == ""
    assert len(responder.requests) == 1                  # scheda non valida: niente guida


def test_no_preventive_limits(setup):
    app, doc, responder = setup
    run_analysis(doc, app.library, app.client(), "x" * 50000, None)   # indicazioni lunghe, PDF intero
    assert responder.requests[0].pdf_pages == 12 and responder.requests[1].pdf_pages == 12


def test_custom_prompt(config):
    store = PromptStore(App(config, client=FakeGeminiClient()).workspace)
    assert store.custom() is None and store.effective() == store.factory()
    store.save("Le mie istruzioni")
    assert store.effective() == "Le mie istruzioni"
    store.save(store.factory())
    assert store.custom() is None


def test_api_flow(setup):
    app, doc, responder = setup
    client = TestClient(create_app(app, JobManager(run_inline=True)))
    base = f"/api/library/catalogs/{doc.id}"
    assert client.get(f"{base}/quick-pages").json()["pages"] == "1-12"
    # selezione vuota: errore, mai il PDF intero per sbaglio
    assert client.post(f"{base}/analysis/preview", json={"pages": ""}).status_code == 400
    prev = client.post(f"{base}/analysis/preview", json={"pages": "1-3", "instructions": "X"}).json()
    assert prev["pages"] == 3 and "»»»\nX\n«««" in prev["prompt"] and prev["size_mb"] >= 0
    assert prev["estimate_seconds"] > 0 and prev["guide"]["pages"] == 3
    assert client.post(f"{base}/analysis/preview", json={"whole": True}).json()["pages_text"] == "PDF intero"
    assert responder.requests == []                       # l'anteprima non chiama Gemini

    job = client.post(f"{base}/analysis", json={"pages": "1-3", "instructions": "X",
                                                 "guide_instructions": "G"}).json()
    assert job["status"] == "completato" and job["kind"] == "analysis" and len(responder.requests) == 2
    listed = client.get(f"{base}/analyses").json()
    assert listed[0]["pages_text"] == "pagine 1-3" and listed[0]["status"] == "nuova"
    assert listed[0]["guide_pages_text"] == "pagine 1-4, 9" and listed[0]["guide"]
    assert client.get("/api/library/catalogs").json()["catalogs"][0]["proposals"] == 1
    card = client.post(f"{base}/analyses/{listed[0]['id']}/apply",
                       json={"description": "replace", "tags": ["alfa"], "fields": [0], "collections": [1],
                             "guide": True, "guide_text": "Guida rivista"}).json()
    assert card["tags"] == ["alfa"] and card["collections"][0]["origin"] == "gemini"
    assert card["guide"] == "Guida rivista\n" and card["has_guide"] and card["key_pages"] == [3]
    assert client.put(base, json={"guide": "Scritta a mano"}).json()["guide"] == "Scritta a mano\n"

    # rigenerazione della guida dalla scheda attuale (solo la richiesta B)
    prev = client.post(f"{base}/guide/preview", json={"pages": "", "instructions": "I"}).json()
    assert prev["pages_text"] == "3" and "Scritta a mano" not in prev["prompt"] and "»»»\nI\n«««" in prev["prompt"]
    job = client.post(f"{base}/guide", json={"pages": "1"}).json()
    assert job["status"] == "completato" and job["kind"] == "guide"
    regen = client.get(f"{base}/analyses").json()[0]
    assert regen["kind"] == "guida" and regen["guide_pages_text"] == "pagine 1, 3"
    assert client.get("/api/library/catalogs").json()["catalogs"][0]["proposals"] == 1    # la guida nuova

    client.post(f"{base}/analysis", json={"whole": True})
    second = client.get(f"{base}/analyses").json()[0]
    assert second["pages"] is None
    assert client.post(f"{base}/analyses/{second['id']}/dismiss").json()["status"] == "scartata"

    client.put("/api/library/analysis-prompt", json={"text": "Mie"})
    assert client.get("/api/library/analysis-prompt").json()["effective"] == "Mie"

    # richiesta troppo pesante: errore spiegato nel lavoro
    responder.error = RequestTooLargeError("La richiesta è troppo pesante per Gemini: scegli meno pagine.")
    job = client.post(f"{base}/analysis", json={"whole": True}).json()
    assert job["status"] == ERROR and "scegli meno pagine" in job["error"]


def test_old_analysis_tags_are_renamed(setup):
    app, doc, _ = setup
    analysis = run_analysis(doc, app.library, app.client(), "", [1])
    path = doc.folder / "analyses" / f"{analysis.id}.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"dati"', '"da-indicizzare"'), encoding="utf-8")
    stored = list_analyses(doc)[0]
    assert {c["tag"] for c in stored.result["collections"]} <= {"copertina", "dati", "esempio"}
    card = apply_analysis(doc, app.library, stored, Selection(collections=[1]))
    assert card.collections[0].tag == "dati"
