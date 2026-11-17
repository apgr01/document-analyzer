"""Creazione del progetto dalla scheda di un catalogo (Gemini simulato): la Tabella è dell'utente,
Gemini cerca solo i cataloghi simili; convalida rigorosa, report e progetto."""

import copy

import pytest
from conftest import TABLE
from fastapi.testclient import TestClient

from docanalyzer.app import App
from docanalyzer.core.fake_gemini import FakeGeminiClient
from docanalyzer.core.library import FieldDef
from docanalyzer.guided_project import (
    GuidedError,
    GuidedRequest,
    create_direct,
    create_project,
    guided_schema,
    list_runs,
    make_request,
    prepare,
    run_guided,
    validate,
)
from docanalyzer.library_analysis import InvalidAnswerError
from docanalyzer.web.jobs import ERROR, JobManager
from docanalyzer.web.server import create_app

ANSWER = {
    "seed": {"covered": ["motore", "codice"], "missing": [], "collections": ["P/1"], "notes": ""},
    "candidates": [
        {"catalog": "C1", "verdict": "compatibile", "reason": "stesse tabelle", "covered": ["MOTORE", "prezzo"],
         "collections": ["C1/1", "P/2"]},
        {"catalog": "C2", "verdict": "parziale", "reason": "manca il codice", "covered": ["MOTORE"],
         "collections": []},
    ],
    "notes": "",
}
REQUEST = GuidedRequest(name="Ricambi", description="Codici per motore", **TABLE, instructions="niente spazi")


class Responder:
    def __init__(self, answer=ANSWER):
        self.answer, self.requests = answer, []

    def __call__(self, request):
        self.requests.append(request)
        return self.answer


@pytest.fixture
def setup(config, pdf_factory):
    responder = Responder()
    app = App(config, client=FakeGeminiClient(responder))
    lib = app.library
    names = ("Alfa", "Beta", "Gamma", "Delta")
    docs = {n: app.add_to_library(pdf_factory(f"{n}.pdf", pages=8, prefix=n)) for n in names}
    card = lib.card(docs["Alfa"])
    card.description, card.guide = "Motori diesel, tabelle di codici.", "# Guida Alfa\n"
    lib.save_card(docs["Alfa"], card)
    lib.add_collection(docs["Alfa"], 1, 1, "copertina")             # non elencata: inutile per i dati
    p1 = lib.add_collection(docs["Alfa"], 2, 4, "dati", "tabelle")
    lib.add_collection(docs["Alfa"], 3, 3, "esempio")
    card = lib.card(docs["Beta"])
    card.description, card.guide = "Altro catalogo motori.", "# Guida Beta\n"
    card.folder = "Altra cartella"
    lib.save_card(docs["Beta"], card)
    c1 = lib.add_collection(docs["Beta"], 5, 6, "dati", "tabelle")
    card = lib.card(docs["Gamma"])
    card.fields = [FieldDef(name="motore")]                       # solo dati presenti: è analizzato
    lib.save_card(docs["Gamma"], card)
    return app, docs, responder, p1, c1


def test_request_is_the_table():
    request = make_request({"name": " Ricambi  ", "row": " una  riga ", "columns": [
        {"name": "A", "header": 1}, {"name": " "}, {"name": "B"}], "instructions": " x "})
    assert request.name == "Ricambi" and request.row == "una riga" and request.instructions == "x"
    assert request.columns == [{"name": "A", "description": "", "header": True, "key": False},
                               {"name": "B", "description": "", "header": False, "key": False}]
    with pytest.raises(GuidedError, match="Compila la tabella"):
        GuidedRequest(row="x").check()
    with pytest.raises(GuidedError, match="Compila la tabella"):
        GuidedRequest(columns=[{"name": "A"}]).check()


def test_prepare(setup):
    app, docs, *_ = setup
    prepared = prepare(app, docs["Alfa"], REQUEST, "MIE")
    # tutti i cataloghi analizzati, di ogni cartella; Delta non è analizzato: escluso
    assert prepared.codes == {"P": "alfa", "C1": "beta", "C2": "gamma"} and prepared.not_elaborated == 1
    assert list(prepared.sections) == ["P/1", "P/2", "C1/1"]
    p = prepared.prompt
    assert "««« INIZIO INDICAZIONI »»»\nMIE\n««« FINE INDICAZIONI »»»" in p
    assert p.index("# Formato della risposta") > p.index("FINE INDICAZIONI »»»\n")
    assert "decisa da lui: non va modificata" in p and "- A cosa serve: Codici per motore" in p
    assert "- Ogni riga rappresenta: una riga per ogni codice" in p
    assert "  1. MOTORE: modello (dato di intestazione" in p and "  2. CODICE: codice articolo\n" in p
    assert "- Altre indicazioni: niente spazi" in p and "`table`" not in p and "project_name" not in p
    assert "### P — Alfa" in p and "- Sezione P/1: pagine 2-4, Dati — tabelle" in p and "Copertina" not in p
    assert "### C1 — Beta" in p and "- Sezione C1/1: pagine 5-6, Dati" in p and "### C2 — Gamma" in p
    schema = guided_schema(prepared)
    assert set(schema["properties"]) == {"seed", "candidates", "notes"}
    assert schema["properties"]["candidates"]["items"]["properties"]["catalog"]["enum"] == ["C1", "C2"]
    assert schema["properties"]["seed"]["properties"]["collections"]["items"]["enum"] == ["P/1", "P/2"]
    with pytest.raises(GuidedError, match="Compila"):
        prepare(app, docs["Alfa"], GuidedRequest(), "")


def test_no_limit_on_candidates(setup, pdf_factory):
    app, docs, *_ = setup
    long = "lunga descrizione " * 200
    for i in range(12):
        doc = app.add_to_library(pdf_factory(f"Altro {i}.pdf", pages=1))
        app.library.save_card(doc, app.library.card(doc).model_copy(update={"description": long}))
    prepared = prepare(app, docs["Alfa"], REQUEST, "")
    assert len(prepared.candidates) == 14 and prepared.prompt.count(long.strip()) == 12   # niente tagli


def test_validate(setup):
    app, docs, _, p1, c1 = setup
    prepared = prepare(app, docs["Alfa"], REQUEST, "")
    result, problems = validate(ANSWER, prepared, ["MOTORE", "CODICE"])
    assert result.seed_covered == ["MOTORE", "CODICE"] and result.seed_collections == [p1.id]
    beta, gamma = result.candidates
    assert (beta.document, beta.verdict, beta.covered, beta.collections) == ("beta", "compatibile", ["MOTORE"], [c1.id])
    assert (gamma.document, gamma.covered) == ("gamma", ["MOTORE"])
    assert any("prezzo" in p for p in problems) and any("P/2" in p for p in problems)

    def broken(change):
        answer = copy.deepcopy(ANSWER)
        change(answer)
        return answer

    cases = [
        (broken(lambda a: a.pop("notes")), "notes: campo mancante"),
        (broken(lambda a: a.update(table={})), "campo non previsto"),             # la tabella non si riscrive
        (broken(lambda a: a["seed"].update(extra=1)), "campo non previsto"),
        (broken(lambda a: a["candidates"][0].update(catalog="C9")), "sconosciuto 'C9'"),
        (broken(lambda a: a["candidates"][0].update(catalog="P")), "partenza"),
        (broken(lambda a: a["candidates"][1].update(catalog="C1")), "due volte"),
        (broken(lambda a: a["candidates"][0].update(verdict="forse")), "non è compatibile o parziale"),
        (broken(lambda a: a["candidates"][0].update(collections=["C7/1"])), "sezione sconosciuta 'C7/1'"),
        (broken(lambda a: a["seed"].update(collections=["P/9"])), "sezione sconosciuta 'P/9'"),
        (broken(lambda a: a["seed"].update(covered="MOTORE")), "deve essere un elenco"),
        ("testo", "oggetto JSON"),
    ]
    for answer, expected in cases:
        with pytest.raises(InvalidAnswerError, match=expected):
            validate(answer, prepared, ["MOTORE", "CODICE"])


def test_run_and_create(setup):
    app, docs, responder, p1, c1 = setup
    run = run_guided(app, app.client(), docs["Alfa"], REQUEST, "")
    assert responder.requests[0].kind == "json" and responder.requests[0].pdf is None      # solo testo
    assert list_runs(app.workspace, seed="alfa")[0].id == run.id and run.candidates == ["beta", "gamma"]

    with pytest.raises(GuidedError, match="partenza"):
        create_project(app, run, "X", [{"id": "beta", "collections": []}])
    project = create_project(app, run, name="", documents=[{"id": "alfa", "collections": []},
                                                           {"id": "beta", "collections": [c1.id]}])
    info = project.info
    # la Tabella è quella della richiesta, il nome di default anche
    assert info.name == "Ricambi" and info.documents == ["alfa", "beta"] and info.row == "una riga per ogni codice"
    assert info.description == "Codici per motore" and info.instructions == "niente spazi"
    assert [(f["name"], f["header"]) for f in info.fields] == [("MOTORE", True), ("CODICE", False)]
    # partenza senza sezioni scelte: le sue collezioni "dati" di default; Beta: la sezione scelta
    assert project.settings_for("alfa").pages == "2-4" and project.settings_for("alfa").collections == [p1.id]
    assert project.settings_for("beta").pages == "5-6"
    # le guide dei cataloghi vengono copiate nel progetto
    assert project.settings_for("alfa").guide == "# Guida Alfa\n"
    assert project.settings_for("beta").guide == "# Guida Beta\n"
    assert list_runs(app.workspace)[0].project_id == project.id
    with pytest.raises(GuidedError, match="esiste già"):
        create_project(app, run, "Altro", [{"id": "alfa"}])


def test_create_direct(setup):
    app, docs, responder, p1, _ = setup
    project = create_direct(app, docs["Alfa"], REQUEST)
    assert project.info.documents == ["alfa"] and project.settings_for("alfa").pages == "2-4"
    assert project.settings_for("alfa").guide == "# Guida Alfa\n" and responder.requests == []
    with pytest.raises(GuidedError, match="Compila"):
        create_direct(app, docs["Alfa"], GuidedRequest(name="X"))


def test_api_flow(setup):
    app, docs, responder, p1, c1 = setup
    client = TestClient(create_app(app, JobManager(run_inline=True)))
    body = {"name": "Ricambi", **TABLE, "gemini_instructions": "X"}
    prev = client.post("/api/library/catalogs/alfa/guided/preview", json=body).json()
    assert prev["candidates"] == 2 and prev["not_elaborated"] == 1 and "»»»\nX\n«««" in prev["prompt"]
    assert prev["chars"] == len(prev["prompt"])
    assert responder.requests == []                       # l'anteprima non chiama Gemini
    assert client.post("/api/library/catalogs/alfa/guided/preview", json={}).status_code == 400
    assert client.post("/api/references", files={"file": ("a.csv", b"A\n1\n", "text/csv")}).status_code in (404, 405)

    job = client.post("/api/library/catalogs/alfa/guided", json=body).json()
    assert job["status"] == "completato" and job["kind"] == "guided"
    run_id = job["result"]["run_id"]
    listed = client.get("/api/library/catalogs/alfa/guided").json()
    assert listed[0]["id"] == run_id and listed[0]["name"] == "Ricambi"
    view = client.get(f"/api/library/guided/{run_id}").json()
    assert view["catalogs"]["beta"]["collections"][0]["label"] == "Dati" and view["catalogs"]["beta"]["has_guide"]
    assert view["request"]["columns"][0] == {"name": "MOTORE", "description": "modello", "header": True, "key": False}

    r = client.post(f"/api/library/guided/{run_id}/project", json={
        "name": "Ricambi motori",
        "documents": [{"id": "alfa", "collections": [p1.id]}, {"id": "beta", "collections": [c1.id]}]}).json()
    assert r["run"]["project"]["name"] == "Ricambi motori" and r["project"]["has_table"] is True
    assert r["project"]["next"]["tab"] == "test"            # tabella e PDF pronti: si prova

    direct = client.post("/api/library/catalogs/gamma/guided/direct", json={"name": "Solo Gamma", **TABLE}).json()
    assert direct["project"]["documents"][0]["id"] == "gamma"
    assert client.post("/api/library/catalogs/gamma/guided/direct", json={"name": "X"}).status_code == 400

    responder.answer = {"table": {}}
    job = client.post("/api/library/catalogs/alfa/guided", json=body).json()
    assert job["status"] == ERROR and "non rispetta il formato" in job["error"]
    assert client.get("/api/library/catalogs/alfa/guided").json()[0]["status"] == "non_valida"
