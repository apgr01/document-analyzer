"""API dell'interfaccia grafica: la pipeline dalla biblioteca al CSV (Gemini simulato, lavori subito)."""

import re
import threading
import time

import pytest
from conftest import TABLE
from fastapi.testclient import TestClient

from docanalyzer.app import App
from docanalyzer.core.fake_gemini import FakeGeminiClient
from docanalyzer.core.page_runner import RunControl, run_pages
from docanalyzer.core.projects import AUTO_COLUMNS
from docanalyzer.web.jobs import CANCELLED, DONE, JobConflictError, JobManager
from docanalyzer.web.server import create_app


class FakeCatalog:
    """Gemini simulato: analisi del catalogo, guida e lettura delle pagine (una riga per pagina)."""

    def __init__(self):
        self.prompts = []

    def __call__(self, request):
        self.prompts.append(request.prompt)
        props = request.json_schema["properties"]
        if "guide_markdown" in props:
            return {"guide_markdown": "# Guida simulata\n\nIl motore è nel titolo.", "notes": ""}
        if "collections" in props:
            return {"description": "Catalogo di motori.", "tags": ["motori"],
                    "fields": [{"name": "motore", "description": "modello"}],
                    "collections": [{"start": 2, "end": 5, "tag": "dati", "comment": "tabelle", "deduced": False},
                                    {"start": 3, "end": 3, "tag": "esempio", "comment": "", "deduced": False}],
                    "notes": ""}
        if "pages" in props:                       # più pagine insieme: un elemento per pagina
            pages = [int(p) for p in re.findall(r"dell'estratto = pagina (\d+) del", request.prompt)]
            return {"pages": [{"page": n, "page_summary": f"tabella {n}", "page_context": {"motore": f"M{n}"},
                               "rows": [{"motore": "", "codice": f"C{n}"}], "notes": ""} for n in pages]}
        n = int(re.search(r"pagina (\d+) di", request.prompt).group(1))
        return {"page_summary": f"tabella {n}", "page_context": {"motore": f"M{n}"},
                "rows": [{"motore": "", "codice": f"C{n}"}], "notes": ""}


@pytest.fixture
def web(config):
    fake = FakeCatalog()
    app = App(config, client=FakeGeminiClient(fake, parallelism=2))
    client = TestClient(create_app(app, JobManager(run_inline=True)))
    return client, fake, app


def upload(client, pdf, folder=""):
    with open(pdf, "rb") as f:
        r = client.post("/api/library/catalogs", files={"file": (pdf.name, f, "application/pdf")},
                        data={"folder": folder})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def direct_project(client, doc_id, name="Progetto", **table):
    r = client.post(f"/api/library/catalogs/{doc_id}/guided/direct", json={"name": name, **TABLE, **table})
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


def test_page_and_status(web):
    client, _, _ = web
    assert "Document Analyzer" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert "GeminiSnake" in client.get("/static/snake.js").text
    assert "renderLibrary" in client.get("/static/library.js").text
    assert "renderGuidedNew" in client.get("/static/guided.js").text
    assert "columnsEditor" in client.get("/static/settings.js").text
    assert "renderTest" in client.get("/static/app.js").text
    assert "renderVerify" in client.get("/static/verifiche.js").text
    assert "/static/verifiche.js" in client.get("/").text
    # la Tabella mostra le colonne che il programma aggiunge, con gli stessi nomi del CSV
    settings_js = client.get("/static/settings.js").text
    assert all(f'["{name}", "{desc}"]' in settings_js for name, desc in AUTO_COLUMNS.items())
    page = client.get("/")
    assert "/static/snake.js" in page.text
    # il browser deve ricontrollare l'interfaccia, per non mescolare versioni vecchie e nuove
    assert page.headers["cache-control"] == "no-cache"
    assert client.get("/static/app.js").headers["cache-control"] == "no-cache"
    assert client.get("/api/status").json()["model"]
    # niente più configurazione guidata, CSV d'esempio, progetti vuoti o caricati da qui
    assert client.post("/api/projects", json={"name": "x"}).status_code == 405
    assert client.get("/api/projects/x/setup").status_code == 404
    assert client.post("/api/references").status_code in (404, 405)


def test_documents_pages_and_settings(web, pdf_factory):
    client, _, app = web
    upload(client, pdf_factory("Alfa.pdf", pages=4, prefix="A"))
    upload(client, pdf_factory("Beta.pdf", pages=3, prefix="B"))
    pid = direct_project(client, "alfa", name="Motori Diesel")
    assert pid == "motori-diesel"
    assert client.post(f"/api/projects/{pid}/documents", files={"file": ("x.pdf", b"x")}).status_code in (404, 405)
    added = client.post(f"/api/projects/{pid}/documents/from-library", json={"ids": ["beta"]}).json()
    assert added["added"] == ["beta"]
    project = client.get(f"/api/projects/{pid}").json()
    assert [d["id"] for d in project["documents"]] == ["alfa", "beta"] and project["page_count"] == 7
    assert project["documents"][0]["to_index"] == 4 and project["documents"][0]["library"]["has_guide"] is False
    assert client.get("/api/documents/alfa/thumb/2").headers["content-type"] == "image/png"
    assert client.get("/api/documents/alfa/page/9").status_code == 404
    assert client.get("/api/documents/alfa/pdf").headers["content-type"] == "application/pdf"
    assert client.get("/api/projects/nessuno").status_code == 404

    # impostazioni per PDF: note e pagine; la guida resta quella copiata
    project_obj = app.projects.get(pid)
    project_obj.set_settings("beta", project_obj.settings_for("beta").model_copy(update={"guide": "# G"}))
    project_obj.save()
    url = f"/api/projects/{pid}/documents/beta/settings"
    s = client.put(url, json={"notes": "nota B", "pages": "2-", "guide": "ignorata"}).json()
    assert s["settings"] == {"notes": "nota B", "pages": "2-", "collections": [], "guide": "# G",
                             "reference_pages": None} and s["to_index"] == 2
    assert client.put(url, json={"pages": "9"}).status_code == 400
    assert client.get(f"/api/projects/{pid}/documents/beta/guide").json()["guide"] == "# G"

    # la Tabella si modifica, ma resta completa
    settings = f"/api/projects/{pid}/settings"
    assert client.put(settings, json={"row": " "}).status_code == 400
    assert client.put(settings, json={"columns": []}).status_code == 400
    reserved = client.put(settings, json={"columns": [{"name": "MOTORE"}, {"name": "FILE_ORIGINE"}]})
    assert reserved.status_code == 400 and "la aggiunge già il programma" in reserved.json()["detail"]
    r = client.put(settings, json={"name": "Motori", "columns": [{"name": "CODICE", "header": False}]}).json()
    assert r["name"] == "Motori"
    assert r["fields"] == [{"name": "CODICE", "description": "", "header": False, "key": False}]

    # togliere dal progetto o eliminare il progetto: i PDF restano nella biblioteca
    assert client.delete(f"/api/projects/{pid}/documents/alfa").json()["removed"] == "alfa"
    assert client.delete(f"/api/projects/{pid}/documents/beta").status_code == 400          # l'ultimo
    assert client.delete(f"/api/projects/{pid}").json()["deleted"] == pid
    ids = {c["id"] for c in client.get("/api/library/catalogs").json()["catalogs"]}
    assert ids == {"alfa", "beta"}


def test_full_pipeline(web, pdf_factory):
    client, fake, app = web
    upload(client, pdf_factory("Alfa.pdf", pages=8, prefix="A"), folder="Motori")
    upload(client, pdf_factory("Beta.pdf", pages=4, prefix="B"))
    lib = "/api/library/catalogs/alfa"

    # 1-2. analisi del catalogo: scheda e guida in due richieste, poi applicate
    job = client.post(f"{lib}/analysis", json={"pages": "1-3"}).json()
    assert job["status"] == DONE and len(fake.prompts) == 2
    analysis = client.get(f"{lib}/analyses").json()[0]
    card = client.post(f"{lib}/analyses/{analysis['id']}/apply", json={
        "description": "replace", "fields": [0], "collections": [0, 1], "guide": True}).json()
    assert card["guide"].startswith("# Guida simulata") and card["analyzed"] and card["to_index"] == 4

    # 3. progetto dal catalogo: la Tabella è dell'utente
    pid = direct_project(client, "alfa", name="Flusso")
    base = f"/api/projects/{pid}"
    client.post(f"{base}/documents/from-library", json={"ids": ["beta"]})
    project = client.get(base).json()
    assert project["documents"][0]["settings"]["pages"] == "2-5"
    assert project["documents"][0]["settings"]["guide"].startswith("# Guida simulata")
    steps = {k: v["state"] for k, v in project["steps"].items()}
    assert steps == {"settings": "fatto", "docs": "da rivedere", "test": "da fare", "index": "da fare",
                     "verify": "da fare", "results": "da fare"}                                  # Beta è senza guida
    assert project["next"]["tab"] == "test"

    # 4. prova: di default 4 pagine per catalogo, prima gli esempi
    prova = client.get(f"{base}/prova").json()
    assert not prova["available"] and prova["default_count"] == 4
    assert prova["plan"] == {"alfa": "2-5", "beta": "1-4"}
    assert client.post(f"{base}/prova/plan", json={"count": 2, "docs": ["alfa"]}).json()["plan"] == {"alfa": "3-4"}
    before = len(fake.prompts)
    job = client.post(f"{base}/prova", json={"plan": {"alfa": "3-4", "beta": [1]}}).json()
    assert job["status"] == DONE and job["kind"] == "test" and len(fake.prompts) - before == 3
    assert "# Guida simulata" in fake.prompts[-3] or "# Guida simulata" in fake.prompts[-2]
    prova = client.get(f"{base}/prova").json()
    assert prova["available"] and [len(d["rows"]) for d in prova["documents"]] == [2, 1]
    assert client.get(f"{base}/prova.csv").status_code == 200
    assert client.post(f"{base}/prova", json={"plan": {}}).status_code == 400
    project = client.get(base).json()
    assert project["steps"]["test"]["state"] == "fatto" and project["next"]["tab"] == "index"

    # 5. indicizzazione: le pagine della prova non si rifanno
    plan = client.get(f"{base}/index/plan").json()
    assert plan["pages"] == 8 and plan["from_prova"] == 3 and plan["todo"] == 5 and not plan["spec_changed"]
    before = len(fake.prompts)
    job = client.post(f"{base}/index", json={}).json()
    assert job["status"] == DONE and len(fake.prompts) - before == 5
    assert job["result"]["documents"]["alfa"]["succeeded"] == 2
    res = client.get(f"{base}/results").json()
    assert res["available"] and res["stats"]["righe_finali"] == 8 and res["stats"]["documenti_indicizzati"] == 2
    assert res["columns"] == ["MOTORE", "CODICE", "PAGINA_PDF", "FILE_ORIGINE"]
    csv = client.get(f"{base}/download/csv").content.decode("utf-8-sig")
    assert "Alfa.pdf" in csv and "Beta.pdf" in csv and "M3,C3,3,Alfa.pdf" in csv
    assert client.get(f"{base}/download/documento?doc=beta").status_code == 200
    search = client.get(f"{base}/search")
    assert search.status_code == 200 and "/api/documents/{doc}/pdf#page={page}" in search.text
    project = client.get(base).json()
    assert project["next"]["tab"] == "verify" and project["steps"]["index"]["state"] == "fatto"

    # nella scheda del catalogo: il progetto e lo stato
    item = client.get(f"{lib}/projects").json()[0]
    assert item["done"] == 4 and item["csv"] and item["has_guide"] and not item["guide_changed"]

    # note cambiate per un PDF: solo quello va rifatto, e la prova risulta superata
    client.put(f"{base}/documents/beta/settings", json={"notes": "nuova nota"})
    plan = client.get(f"{base}/index/plan").json()
    assert plan["spec_changed"] == ["beta"] and plan["todo"] == 4
    project = client.get(base).json()
    assert project["steps"]["test"]["state"] == "da rivedere" and project["steps"]["index"]["state"] == "da rivedere"
    assert client.post(f"{base}/index", json={}).status_code == 409
    job = client.post(f"{base}/index", json={"force": True}).json()
    assert job["result"]["documents"]["beta"]["succeeded"] == 4
    assert job["result"]["documents"]["alfa"]["succeeded"] == 0                  # alfa non rifatto

    # la guida cambia nella biblioteca: il progetto lo segnala e si aggiorna su richiesta
    client.put(lib, json={"guide": "# Guida corretta"})
    project = client.get(base).json()
    assert [c["doc_id"] for c in project["library_changes"]] == ["alfa"] and project["next"]["tab"] == "docs"
    r = client.post(f"{base}/library-update", json={"docs": ["alfa"]}).json()
    assert r["updated"] == ["alfa"] and r["project"]["documents"][0]["settings"]["guide"] == "# Guida corretta\n"
    assert client.get(f"{base}/index/plan").json()["spec_changed"] == ["alfa"]


def test_index_only_from_prova(web, pdf_factory):
    """Tutte le pagine da indicizzare sono già state provate: l'indicizzazione le riusa e basta."""
    client, fake, _ = web
    upload(client, pdf_factory("Piccolo.pdf", pages=2))
    pid = direct_project(client, "piccolo")
    base = f"/api/projects/{pid}"
    client.post(f"{base}/prova", json={"plan": {"piccolo": "1-2"}})
    plan = client.get(f"{base}/index/plan").json()
    assert plan["todo"] == 0 and plan["from_prova"] == 2 and plan["estimate_minutes"] == 0
    before = len(fake.prompts)
    assert client.post(f"{base}/index", json={}).json()["status"] == DONE and len(fake.prompts) == before
    assert client.get(f"{base}/results").json()["stats"]["righe_finali"] == 2
    assert client.get(base).json()["steps"]["index"]["state"] == "fatto"


def test_send_pages_together(web, pdf_factory):
    """Invio "insieme": una richiesta per PDF (estratto ritagliato), nella prova e nell'indicizzazione."""
    client, fake, app = web
    upload(client, pdf_factory("Alfa.pdf", pages=6, prefix="A"))
    upload(client, pdf_factory("Beta.pdf", pages=5, prefix="B"))
    pid = direct_project(client, "alfa")
    base = f"/api/projects/{pid}"
    client.post(f"{base}/documents/from-library", json={"ids": ["beta"]})
    plan = client.get(f"{base}/index/plan").json()
    assert plan["send_mode"] == "pagina" and plan["requests"] == 11 and plan["biggest_request"] is None

    assert client.put(f"{base}/send", json={"mode": "a caso"}).status_code == 400
    assert client.put(f"{base}/send", json={"mode": "insieme", "pages_per_request": 0}).status_code == 400
    summary = client.put(f"{base}/send", json={"mode": "insieme", "pages_per_request": ""}).json()
    assert summary["send_mode"] == "insieme" and summary["pages_per_request"] is None
    plan = client.get(f"{base}/index/plan").json()
    assert plan["requests"] == 2 and [d["requests"] for d in plan["documents"]] == [1, 1]
    assert plan["biggest_request"]["pages"] == 6 and plan["biggest_request"]["tokens"] > 6000

    # prova: una richiesta per PDF con le pagine scelte
    before = len(fake.prompts)
    job = client.post(f"{base}/prova", json={"plan": {"alfa": "1-2", "beta": "3"}}).json()
    assert job["status"] == "completato" and len(fake.prompts) - before == 2
    prova = client.get(f"{base}/prova").json()
    assert [len(d["rows"]) for d in prova["documents"]] == [2, 1]

    # indicizzazione: le pagine della prova si riusano, il resto in una richiesta per PDF
    plan = client.get(f"{base}/index/plan").json()
    assert plan["todo"] == 8 and plan["from_prova"] == 3 and plan["requests"] == 2
    before = len(fake.prompts)
    job = client.post(f"{base}/index", json={}).json()
    assert job["status"] == "completato" and len(fake.prompts) - before == 2
    assert all("un elemento per OGNI pagina" in p for p in fake.prompts[-2:])
    res = client.get(f"{base}/results").json()
    assert res["stats"]["righe_finali"] == 11

    # con un massimo di pagine per richiesta: più richieste per PDF
    client.put(f"{base}/send", json={"mode": "insieme", "pages_per_request": 2})
    client.put(f"{base}/documents/beta/settings", json={"notes": "nuova nota"})       # beta da rifare
    plan = client.get(f"{base}/index/plan").json()
    assert plan["spec_changed"] == ["beta"] and plan["requests"] == 3
    # tornando a una pagina per richiesta il valore massimo si azzera
    back = client.put(f"{base}/send", json={"mode": "pagina", "pages_per_request": 3}).json()
    assert back["pages_per_request"] is None


def test_restart_and_failed_pages(web, pdf_factory):
    """Rifai da capo (un PDF o tutti), motivo dei fallimenti, pagine fallite sempre ritentate da Avvia."""
    client, fake, app = web
    upload(client, pdf_factory("Alfa.pdf", pages=4, prefix="A"))
    upload(client, pdf_factory("Beta.pdf", pages=3, prefix="B"))
    pid = direct_project(client, "alfa")
    base = f"/api/projects/{pid}"
    client.post(f"{base}/documents/from-library", json={"ids": ["beta"]})
    client.post(f"{base}/prova", json={"plan": {"alfa": "1"}})

    # Beta fallisce sempre: più tentativi del massimo per la riga di comando
    original = fake.__call__

    def broken(request):
        if "di 3 del PDF" in request.prompt:                    # le pagine di Beta (3 pagine)
            raise RuntimeError("pagina illeggibile")
        return original(request)

    app.client().responder = broken
    for _ in range(app.config.indexing.max_page_attempts + 1):
        client.post(f"{base}/index", json={})
    plan = client.get(f"{base}/index/plan").json()
    beta = plan["documents"][1]
    assert beta["failed"] == 3 and "pagina illeggibile" in beta["failed_reason"] and beta["todo"] == 3
    assert plan["restart"] == {"pages": 7, "requests": 7, "minutes": 1}
    before = len(app.client().requests)
    client.post(f"{base}/index", json={})                        # Avvia: le fallite si ritentano sempre
    assert len(app.client().requests) - before == 3

    # da capo solo Beta: Alfa non si tocca
    app.client().responder = fake
    before = len(fake.prompts)
    job = client.post(f"{base}/index", json={"restart": ["beta"]}).json()
    assert job["status"] == "completato" and len(fake.prompts) - before == 3
    assert set(job["result"]["documents"]) == {"beta"}
    assert client.get(f"{base}/index/plan").json()["todo"] == 0

    # da capo tutto: anche la pagina della prova si rifà
    before = len(fake.prompts)
    job = client.post(f"{base}/index", json={"restart": True}).json()
    assert job["status"] == "completato" and len(fake.prompts) - before == 7
    assert client.get(f"{base}/results").json()["stats"]["righe_finali"] == 7
    assert client.post(f"{base}/index", json={"restart": ["gamma"]}).status_code == 400

    # con l'invio insieme il rifacimento conta una richiesta per PDF
    client.put(f"{base}/send", json={"mode": "insieme"})
    assert client.get(f"{base}/index/plan").json()["restart"]["requests"] == 2


def test_incomplete_table_blocks_test_and_index(web, pdf_factory):
    client, _, app = web
    upload(client, pdf_factory("Nuovo.pdf", pages=2))
    pid = direct_project(client, "nuovo")
    project = app.projects.get(pid)
    project.info.fields = []
    project.save()
    summary = client.get(f"/api/projects/{pid}").json()
    assert summary["next"]["tab"] == "settings" and summary["progress"] is None
    for r in (client.get(f"/api/projects/{pid}/index/plan"), client.post(f"/api/projects/{pid}/prova", json={})):
        assert r.status_code == 400 and "Tabella" in r.json()["detail"]
    assert client.get(f"/api/projects/{pid}/prova").json()["available"] is False


def test_job_manager_one_job_per_project_and_cancel():
    jobs = JobManager()
    release = threading.Event()

    def slow(job):
        release.wait(5)
        return "fatto"

    first = jobs.submit("p", "x", "lavoro lento", slow)
    with pytest.raises(JobConflictError):
        jobs.submit("p", "y", "altro", slow)
    other = jobs.submit("altro", "y", "altro", lambda job: 1)
    release.set()
    for _ in range(100):
        if first.status == DONE and other.status == DONE:
            break
        time.sleep(0.02)
    assert first.result == "fatto" and other.result == 1

    class _Manifest:
        def mark_done(self, n): pass
        def mark_failed(self, n, e): pass

    seen = []
    jobs2 = JobManager()

    def work(job):
        def worker(n):
            seen.append(n)
            if n == 2:
                jobs2.cancel(job.id)
        return run_pages(list(range(1, 50)), worker, _Manifest(), 1, "prova", False, job.control)

    job = jobs2.submit("d", "index", "indicizzazione", work)
    for _ in range(200):
        if job.status != "in_corso":
            break
        time.sleep(0.02)
    assert job.status == CANCELLED
    assert len(seen) < 49 and job.result.stopped_reason == "annullato dall'utente"


def test_run_control_reports_progress():
    events = []
    control = RunControl(progress=lambda d, t, m: events.append((d, t)))

    class _Manifest:
        def mark_done(self, n): pass
        def mark_failed(self, n, e): pass

    run_pages([1, 2, 3], lambda n: None, _Manifest(), 2, "x", False, control)
    assert events[0] == (0, 3) and events[-1] == (3, 3)


def test_job_shows_service_messages_and_can_be_cancelled_during_overload(config, pdf_factory):
    """Gemini sovraccarico durante l'analisi: i messaggi arrivano alla pagina e 'Ferma' interrompe subito."""
    from google.genai import errors

    from docanalyzer.core.config import GeminiSettings
    from docanalyzer.core.gemini import GeminiClient

    class Models:
        calls = 0

        def generate_content(self, model, contents, config):
            Models.calls += 1
            raise errors.ServerError(503, {"error": {"code": 503, "message": "high demand"}})

    from types import SimpleNamespace as NS

    app = App(config)
    app._client = GeminiClient(["k"], GeminiSettings(retry_delay_seconds=1, requests_per_minute_per_key=600),
                               client_factory=lambda k: NS(models=Models()), log=app.emit)
    jobs = JobManager()
    client = TestClient(create_app(app, jobs))
    doc_id = upload(client, pdf_factory("Lento.pdf", pages=2))
    job = client.post(f"/api/library/catalogs/{doc_id}/analysis", json={"pages": "1"}).json()
    for _ in range(100):                      # aspetta i primi messaggi di sovraccarico
        data = client.get(f"/api/jobs/{job['id']}").json()
        if len(data["events"]) >= 2:
            break
        time.sleep(0.05)
    assert "sovraccarico" in data["events"][-1]["text"] and data["events"][-1]["time"]
    start = time.time()
    client.post(f"/api/jobs/{job['id']}/cancel")
    for _ in range(100):
        data = client.get(f"/api/jobs/{job['id']}").json()
        if data["status"] != "in_corso":
            break
        time.sleep(0.05)
    assert data["status"] == CANCELLED and time.time() - start < 3
    assert client.get(f"/api/library/catalogs/{doc_id}/analyses").json() == []
