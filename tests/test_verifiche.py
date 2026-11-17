"""⑤ Verifiche/Elaborazione: controlli sui risultati e correzioni (Gemini simulato, lavori subito)."""

import re

import pymupdf
import pytest
from fastapi.testclient import TestClient

from docanalyzer import correzioni, verifiche
from docanalyzer.app import App
from docanalyzer.core.fake_gemini import FakeGeminiClient
from docanalyzer.indexing.assemble import DELETED_KEY
from docanalyzer.web.jobs import DONE, JobManager
from docanalyzer.web.server import create_app

# il catalogo: un indice a pagina 1 (pagine stampate = pagina del PDF - 1), un motore per pagina
PAGES = [
    "Indice\nMotore M2 pag. 1\nMotore M3 pag. 2\nMotore M4 pag. 3\nMotore M5 pag. 9\nMotore M9 pag. 8",
    "Motore M2\nCodice C2",
    "Motore M3\nCodice C3",
    "Motore M4\nCodice C4\nCodice C40",
    "Motore M5\nCodice C5",
    "Note finali",
]
# cosa "legge" Gemini su ogni pagina
ROWS = {
    1: [],
    2: [{"motore": "M2", "codice": "C2"}],
    3: [{"motore": "M3", "codice": ""}],                                    # codice vuoto
    4: [{"motore": "M4", "codice": "C4"}, {"motore": "M4", "codice": "C40"}],   # due righe, stesso motore
    5: [{"motore": "M5", "codice": "C§5"}],                                 # carattere sospetto
    6: [{"motore": "M8", "codice": "C8"}],                                  # non è sulla pagina
}
REFERENCE = [("M2", "1"), ("M3", "2"), ("M4", "3"), ("M5", "9"), ("M9", "8")]
COLUMNS = [{"name": "MOTORE", "description": "modello", "key": True}, {"name": "CODICE", "description": "codice"}]


class FakeCatalog:
    def __init__(self):
        self.prompts = []
        self.rows = dict(ROWS)

    def __call__(self, request):
        self.prompts.append(request.prompt)
        props = request.json_schema["properties"]
        if "items" in props:                    # l'elenco di riferimento: riporta solo i motori
            keys = props["items"]["items"]["properties"]["values"]["properties"]
            return {"items": [{"values": {k: m if k == "motore" else "" for k in keys}, "page": p}
                              for m, p in REFERENCE], "notes": ""}
        n = int(re.search(r"pagina (\d+) di", request.prompt).group(1))
        return {"page_summary": f"pagina {n}", "page_context": {}, "rows": self.rows[n], "notes": ""}


def text_pdf(path, pages):
    doc = pymupdf.open()
    for text in pages:
        doc.new_page().insert_text((72, 72), text)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def indexed(config, tmp_path):
    """Un progetto con il catalogo già indicizzato."""
    fake = FakeCatalog()
    app = App(config, client=FakeGeminiClient(fake, parallelism=2))
    client = TestClient(create_app(app, JobManager(run_inline=True)))
    pdf = text_pdf(tmp_path / "Motori.pdf", PAGES)
    with open(pdf, "rb") as f:
        doc_id = client.post("/api/library/catalogs", files={"file": (pdf.name, f, "application/pdf")}).json()["id"]
    r = client.post(f"/api/library/catalogs/{doc_id}/guided/direct",
                    json={"name": "Verifiche", "row": "una riga per ogni codice", "columns": COLUMNS})
    pid = r.json()["project"]["id"]
    base = f"/api/projects/{pid}"
    assert client.post(f"{base}/index", json={}).json()["status"] == DONE
    return client, fake, app, base, doc_id


def run(client, base, check, **body):
    """Esegue una verifica: senza Gemini l'esito è immediato, con Gemini parte un lavoro."""
    r = client.post(f"{base}/verifiche/{check}", json=body)
    assert r.status_code == 200, r.text
    if "job" in r.json():
        assert r.json()["job"]["status"] == DONE, r.json()
    else:
        assert check in r.json()["results"]
    return client.get(f"{base}/verifiche/{check}").json()


def test_overview_and_steps(indexed):
    client, _, _, base, doc_id = indexed
    project = client.get(base).json()
    assert project["steps"]["verify"]["state"] == "da fare" and project["next"]["tab"] == "verify"
    view = client.get(f"{base}/verifiche").json()
    assert [c["id"] for c in view["checks"]] == list(verifiche.CHECKS)
    assert view["key_columns"] == ["MOTORE"] and view["check_columns"] == ["MOTORE"]
    cells = view["documents"][0]["checks"]
    assert {c["state"] for c in cells.values()} == {"non eseguita"}
    run(client, base, "copertura")
    cell = client.get(f"{base}/verifiche").json()["documents"][0]["checks"]["copertura"]
    assert cell["state"] == "problemi" and cell["problems"] == 1
    project = client.get(base).json()
    assert project["steps"]["verify"]["state"] == "da rivedere" and project["next"]["tab"] == "results"


def test_coverage(indexed):
    client, _, _, base, _ = indexed
    items = run(client, base, "copertura")["items"]
    assert [(i["page"], i["problem"]) for i in items] == [(1, "nessuna riga")]
    client.put(f"{base}/verifiche/impostazioni", json={"coverage": "esattamente"})
    view = client.get(f"{base}/verifiche").json()
    assert view["documents"][0]["checks"]["copertura"]["state"] == "superata"     # impostazioni cambiate
    items = run(client, base, "copertura")["items"]
    assert [(i["page"], i["problem"]) for i in items] == [(1, "nessuna riga"), (4, "2 righe")]
    assert client.put(f"{base}/verifiche/impostazioni", json={"coverage": "boh"}).status_code == 400


def test_text_on_page(indexed):
    client, _, _, base, _ = indexed
    items = run(client, base, "testo")["items"]
    assert [(i["page"], i["values"]["MOTORE"], i["status"]) for i in items] == [(6, "M8", "non trovata")]
    summary = client.get(f"{base}/verifiche").json()["documents"][0]["checks"]["testo"]["summary"]
    assert summary["confermata"] == 5 and summary["righe"] == 6
    # anche il codice: C§5 si confronta senza simboli, C40 è sulla pagina 4
    client.put(f"{base}/verifiche/impostazioni", json={"check_columns": ["MOTORE", "CODICE", "NON ESISTE"]})
    assert client.get(f"{base}/verifiche").json()["check_columns"] == ["MOTORE", "CODICE"]
    items = run(client, base, "testo")["items"]
    assert [(i["page"], i["missing"]) for i in items] == [(6, ["MOTORE", "CODICE"])]


def test_text_elsewhere(indexed):
    client, fake, _, base, doc_id = indexed
    fake.rows[6] = [{"motore": "M3", "codice": "C3"}]          # è sulla pagina 3, non sulla 6
    assert client.post(f"{base}/index", json={"redo": {doc_id: [6]}}).json()["status"] == DONE
    items = run(client, base, "testo")["items"]                # anche l'indice (pagina 1) la nomina
    assert [(i["page"], i["status"], i["elsewhere"]) for i in items] == [(6, "altra pagina", [3, 1])]


def test_reference_list(indexed):
    client, fake, _, base, doc_id = indexed
    # senza pagine di riferimento (niente Indice nella scheda) non si può leggere
    r = client.post(f"{base}/verifiche/riferimento", json={})
    assert r.status_code == 400 and "nessuna pagina di riferimento" in r.json()["detail"]
    assert client.put(f"{base}/verifiche/impostazioni", json={"reference_pages": {doc_id: "99"}}).status_code == 400
    client.put(f"{base}/verifiche/impostazioni", json={"reference_pages": {doc_id: "1"}})
    before = len(fake.prompts)
    items = run(client, base, "riferimento")["items"]
    assert len(fake.prompts) - before == 1 and "una riga per ogni codice" in fake.prompts[-1]
    found = {(i["kind"], i["values"]["MOTORE"]) for i in items}
    assert found == {("mancante", "M9"), ("solo nel CSV", "M8"), ("pagina", "M5")}
    page = next(i for i in items if i["kind"] == "pagina")
    assert page["pages"] == [5] and page["expected"] == 10
    summary = client.get(f"{base}/verifiche/riferimento").json()["summaries"][doc_id]["summary"]
    assert summary["scarto"] == 1 and summary["voci"] == 5 and summary["trovate"] == 4

    # rieseguire non rilegge l'elenco; correggerlo a mano sì cambia l'esito
    run(client, base, "riferimento")
    assert len(fake.prompts) - before == 1
    ref = client.get(f"{base}/verifiche/riferimento/{doc_id}").json()
    assert ref["pages"] == "1" and len(ref["reference"]["items"]) == 5
    edited = [i for i in ref["reference"]["items"] if i["values"]["MOTORE"] != "M9"]
    edited.append({"values": {"MOTORE": "M8"}, "page": "5"})
    saved = client.put(f"{base}/verifiche/riferimento/{doc_id}", json={"items": edited}).json()
    assert saved["reference"]["edited"] and len(saved["reference"]["items"]) == 5
    view = client.get(f"{base}/verifiche").json()["documents"][0]
    assert view["checks"]["riferimento"]["state"] == "superata" and view["reference"]["edited"]
    items = run(client, base, "riferimento")["items"]
    assert {(i["kind"], i["values"]["MOTORE"]) for i in items} == {("pagina", "M5")}
    # "rileggi" chiede di nuovo a Gemini (e sostituisce l'elenco corretto a mano)
    assert "job" in client.post(f"{base}/verifiche/riferimento", json={"reread": True, "docs": [doc_id]}).json()
    assert len(fake.prompts) - before == 2
    assert not client.get(f"{base}/verifiche/riferimento/{doc_id}").json()["reference"]["edited"]
    # "esegui le verifiche senza Gemini" rifà anche il confronto con l'elenco già letto, senza richieste
    r = client.post(f"{base}/verifiche/tutte", json={}).json()
    assert "riferimento" in r["results"] and len(fake.prompts) - before == 2


def test_characters_empty_duplicates(indexed):
    client, _, _, base, doc_id = indexed
    items = run(client, base, "caratteri")["items"]
    assert [(i["page"], i["column"], i["chars"]) for i in items] == [(5, "CODICE", ["§"])]
    # vuoti: le colonne chiave e quelle da controllare
    assert run(client, base, "vuoti")["items"] == []
    client.put(f"{base}/verifiche/impostazioni", json={"check_columns": ["CODICE"]})
    items = run(client, base, "vuoti")["items"]
    assert [(i["page"], i["empty"]) for i in items] == [(3, ["CODICE"])]
    items = run(client, base, "doppioni")["items"]
    assert len(items) == 1 and items[0]["key"] == {"MOTORE": "M4"} and items[0]["same_pdf"]
    assert [(o["page"], o["position"]) for o in items[0]["occurrences"]] == [(4, 0), (4, 1)]

    # "va bene così": la segnalazione resta, ma non conta tra i problemi aperti
    client.post(f"{base}/verifiche/accetta", json={"ids": [items[0]["id"]]})
    cell = client.get(f"{base}/verifiche").json()["documents"][0]["checks"]["doppioni"]
    assert cell["state"] == "ok" and cell["accepted"] == 1
    assert client.get(f"{base}/verifiche/doppioni").json()["items"][0]["accepted"]
    client.post(f"{base}/verifiche/accetta", json={"ids": [items[0]["id"]], "accepted": False})
    assert client.get(f"{base}/verifiche").json()["documents"][0]["checks"]["doppioni"]["state"] == "problemi"
    assert client.post(f"{base}/verifiche/nessuna", json={}).status_code == 404
    assert client.post(f"{base}/verifiche/testo", json={"docs": ["altro"]}).status_code == 400


def test_run_all_free_checks(indexed):
    """"Esegui le verifiche senza Gemini": tutte (o solo alcune) in una volta, senza lavori."""
    client, fake, _, base, doc_id = indexed
    before = len(fake.prompts)
    r = client.post(f"{base}/verifiche/tutte", json={"docs": [doc_id]}).json()
    assert set(r["results"]) == {"copertura", "testo", "caratteri", "vuoti", "doppioni"} and not r["skipped"]
    assert len(fake.prompts) == before
    cells = client.get(f"{base}/verifiche").json()["documents"][0]["checks"]
    assert cells["riferimento"]["state"] == "non eseguita" and cells["copertura"]["state"] == "problemi"
    r = client.post(f"{base}/verifiche/tutte", json={"checks": ["vuoti", "riferimento"]}).json()
    assert list(r["results"]) == ["vuoti"]
    # senza colonne chiave alcune verifiche non si possono fare: le altre sì
    client.put(f"{base}/settings", json={"columns": [{"name": "MOTORE"}, {"name": "CODICE"}]})
    r = client.post(f"{base}/verifiche/tutte", json={}).json()
    assert set(r["skipped"]) == {"testo", "vuoti", "doppioni"} and "Chiave" in r["skipped"]["doppioni"]


def test_corrections(indexed):
    client, fake, app, base, doc_id = indexed
    rows = client.get(f"{base}/righe").json()
    assert rows["total"] == 6 and rows["columns"] == ["MOTORE", "CODICE", "PAGINA_PDF", "FILE_ORIGINE"]
    assert client.get(f"{base}/righe", params={"q": "m4"}).json()["total"] == 2
    assert client.get(f"{base}/righe", params={"page": 4, "limit": 1}).json()["rows"][0]["values"]["CODICE"] == "C4"

    # sostituisci tutte: § -> niente, nella colonna CODICE
    view = client.post(f"{base}/correzioni/regola", json={"find": "§", "replace": "", "column": "CODICE"}).json()
    assert view["rules"][0]["changed"] == 1
    assert client.post(f"{base}/correzioni/regola", json={"find": ""}).status_code == 400
    assert client.post(f"{base}/correzioni/regola", json={"find": "x", "column": "BOH"}).status_code == 400
    assert run(client, base, "caratteri")["items"] == []
    # una cella a mano, una riga eliminata
    client.post(f"{base}/correzioni/cella", json={"doc": doc_id, "page": 3, "position": 0, "column": "CODICE",
                                                  "value": "C3"})
    view = client.post(f"{base}/correzioni/riga", json={"doc": doc_id, "page": 6, "position": 0}).json()
    assert len(view["edits"]) == 1 and view["edits"][0]["original"] == "" and view["edits"][0]["applicable"]
    assert view["deletions"][0]["original"]["MOTORE"] == "M8"
    rows = client.get(f"{base}/righe").json()
    assert rows["total"] == 5
    changed = {(r["page"], tuple(r["changed"])) for r in rows["rows"] if r["changed"]}
    assert changed == {(3, ("CODICE",)), (5, ("CODICE",))}
    csv = client.get(f"{base}/download/csv").content.decode("utf-8-sig")
    assert "M8" not in csv and "M3,C3" in csv and "M5,C5" in csv and "§" not in csv
    assert client.get(f"{base}/results").json()["stats"]["righe_finali"] == 5
    # tornare al valore estratto toglie la correzione
    view = client.post(f"{base}/correzioni/cella", json={"doc": doc_id, "page": 3, "position": 0,
                                                         "column": "CODICE", "value": ""}).json()
    assert view["edits"] == []
    assert client.post(f"{base}/correzioni/riga", json={"doc": doc_id, "page": 1, "position": 0}).status_code == 400

    # rifare una pagina: se il valore originale cambia la correzione non si applica più (ma resta)
    fake.rows[6] = [{"motore": "M6", "codice": "C6"}]
    assert client.post(f"{base}/index", json={"redo": {doc_id: [6]}}).json()["status"] == DONE
    view = client.get(f"{base}/correzioni").json()
    assert not view["deletions"][0]["applicable"]
    assert "M6" in client.get(f"{base}/download/csv").content.decode("utf-8-sig")
    # togliere una correzione
    assert client.delete(f"{base}/correzioni/{view['rules'][0]['id']}").json()["rules"] == []
    assert client.delete(f"{base}/correzioni/nessuna").status_code == 404


def test_redo_pages_only(indexed):
    client, fake, _, base, doc_id = indexed
    before = len(fake.prompts)
    assert client.post(f"{base}/index", json={"redo": {doc_id: [2, 6]}}).json()["status"] == DONE
    assert len(fake.prompts) - before == 2
    assert client.post(f"{base}/index", json={"redo": {"altro": [1]}}).status_code == 400


def test_apply_rules_unit():
    """Le regole non toccano le celle modificate a mano; i risultati originali restano intatti."""
    results = {1: {"rows": [{"a": "x§", "b": "§"}, {"a": "§"}], "page_context": {"b": "§§"}}}
    corr = correzioni.Corrections(
        rules=[correzioni.Rule(find="§", replace="@")],
        edits=[correzioni.CellEdit(doc="d", page=1, position=0, column="a", original="x§", value="manuale")],
        deletions=[correzioni.RowDeletion(doc="d", page=1, position=1, original={"a": "§"})],
    )
    applied = correzioni.apply(corr, "d", results)
    assert applied.results[1]["rows"][0] == {"a": "manuale", "b": "@"}
    assert applied.results[1]["rows"][1] == {DELETED_KEY: True}
    assert applied.results[1]["page_context"] == {"b": "@@"}
    assert results[1]["rows"][0]["a"] == "x§"
    assert applied.status[corr.rules[0].id] == 2 and applied.status[corr.edits[0].id] == 1
    assert correzioni.apply(corr, "altro", results).status[corr.rules[0].id] == 4


def test_norm_and_chars():
    assert verifiche.norm("MX 260/C") == "mx260c"
    assert verifiche.suspicious_char("�") and verifiche.suspicious_char("")
    assert not verifiche.suspicious_char("°") and not verifiche.unusual_char("°")
    assert verifiche.unusual_char("§") and not verifiche.unusual_char("a")


def test_stale_only_where_corrections_apply(indexed, tmp_path):
    """Una correzione su un PDF rende da rieseguire le sue verifiche, non quelle degli altri PDF
    (tranne caratteri e doppioni, che confrontano i PDF tra loro)."""
    client, fake, _, base, doc_id = indexed
    pdf = text_pdf(tmp_path / "Altro.pdf", ["Motore M2\nCodice C2"] * 6)
    with open(pdf, "rb") as f:
        other = client.post("/api/library/catalogs", files={"file": (pdf.name, f, "application/pdf")}).json()["id"]
    client.post(f"{base}/documents/from-library", json={"ids": [other]})
    assert client.post(f"{base}/index", json={}).json()["status"] == DONE
    client.post(f"{base}/verifiche/tutte", json={})
    client.post(f"{base}/correzioni/cella", json={"doc": doc_id, "page": 2, "position": 0, "column": "CODICE",
                                                  "value": "X"})
    docs = {d["id"]: d["checks"] for d in client.get(f"{base}/verifiche").json()["documents"]}
    assert docs[doc_id]["testo"]["state"] == "superata" and docs[doc_id]["vuoti"]["state"] == "superata"
    assert docs[other]["testo"]["state"] != "superata" and docs[other]["vuoti"]["state"] != "superata"
    assert docs[other]["doppioni"]["state"] == "superata"


def test_reference_compares_only_listed_key_columns(indexed):
    """Chiave motore + codice, ma l'indice elenca solo i motori: si confronta sul motore."""
    client, _, _, base, doc_id = indexed
    columns = [{**COLUMNS[0]}, {**COLUMNS[1], "key": True}]
    assert client.put(f"{base}/settings", json={"columns": columns}).status_code == 200
    assert client.get(f"{base}/verifiche").json()["key_columns"] == ["MOTORE", "CODICE"]
    client.put(f"{base}/verifiche/impostazioni", json={"reference_pages": {doc_id: "1"}})
    items = run(client, base, "riferimento")["items"]
    assert {(i["kind"], i["values"]["MOTORE"]) for i in items} == {("mancante", "M9"), ("solo nel CSV", "M8"),
                                                                   ("pagina", "M5")}
