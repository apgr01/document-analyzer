"""Biblioteca dei cataloghi: cartelle, tag, campi, collezioni di pagine e passaggio ai progetti."""

import pytest
import yaml
from conftest import TABLE, new_project
from fastapi.testclient import TestClient

from docanalyzer.app import App
from docanalyzer.core.fake_gemini import FakeGeminiClient
from docanalyzer.core.library import LibraryCard, LibraryError, normalize_folder, normalize_tags
from docanalyzer.web.jobs import JobManager
from docanalyzer.web.server import create_app


@pytest.fixture
def app(config):
    return App(config, client=FakeGeminiClient(None))


@pytest.fixture
def client(app):
    return TestClient(create_app(app, JobManager(run_inline=True)))


def upload(client, pdf, folder=""):
    with open(pdf, "rb") as f:
        r = client.post("/api/library/catalogs", files={"file": (pdf.name, f, "application/pdf")},
                        data={"folder": folder})
    assert r.status_code == 200, r.text
    return r.json()


def test_normalization():
    assert normalize_folder(" Motori / Diesel/ ") == "Motori/Diesel"
    assert normalize_folder("Motori\\VM") == "Motori/VM"
    assert normalize_folder("") == ""
    with pytest.raises(LibraryError):
        normalize_folder("Motori/../x")
    assert normalize_tags([" Motori ", "motori", "tabelle  codici", ""]) == ["Motori", "tabelle codici"]


def test_library_lives_without_projects(app, pdf_factory):
    doc = app.add_to_library(pdf_factory("Alfa.pdf", pages=5), folder="Motori/Diesel")
    assert app.projects.containing(doc.id) == []
    assert app.library.card(doc).folder == "Motori/Diesel"
    assert app.library.folders() == ["Motori", "Motori/Diesel"]
    # al riavvio non diventa un progetto (la scheda c'è)
    App(app.config, client=app._client)
    assert app.projects.list() == []


def test_old_documents_get_a_card(app, pdf_factory):
    # documento di una versione precedente: senza scheda; non diventa un progetto
    doc = app.documents.add(pdf_factory("Vecchio.pdf"))
    assert not app.library.has_card(doc)
    again = App(app.config, client=app._client)
    assert again.library.has_card(doc) and again.library.card(doc).folder == ""
    assert again.projects.list() == []


def test_collections(app, pdf_factory):
    doc = app.add_to_library(pdf_factory("Alfa.pdf", pages=10))
    lib = app.library
    a = lib.add_collection(doc, 9, 3, "dati", " tabelle ")     # ordine invertito: corretto
    assert (a.start, a.end, a.comment) == (3, 9, "tabelle")
    lib.add_collection(doc, 1, 1, "copertina")
    lib.add_collection(doc, 4, 5, "esempio")
    card = lib.card(doc)
    assert [c.tag for c in card.collections] == ["copertina", "dati", "esempio"]   # per pagina
    assert card.pages_with_tag("dati") == list(range(3, 10))
    with pytest.raises(LibraryError, match="fuori"):
        lib.add_collection(doc, 8, 11, "indice")
    with pytest.raises(ValueError):
        lib.add_collection(doc, 1, 2, "inventato")
    lib.update_collection(doc, a.id, 3, 4, "tabelle-tecniche", "")
    assert lib.card(doc).pages_with_tag("dati") == []
    lib.remove_collection(doc, a.id)
    with pytest.raises(LibraryError):
        lib.remove_collection(doc, a.id)
    assert len(lib.card(doc).collections) == 2


def test_folders(app, pdf_factory):
    lib = app.library
    a = app.add_to_library(pdf_factory("Alfa.pdf"), folder="Motori/Diesel")
    b = app.add_to_library(pdf_factory("Beta.pdf"), folder="Motori")
    lib.create_folder("Trattori")
    assert lib.folders() == ["Motori", "Motori/Diesel", "Trattori"]
    lib.rename_folder("Motori", "Archivio/Motori")
    assert lib.card(a).folder == "Archivio/Motori/Diesel"
    assert lib.card(b).folder == "Archivio/Motori"
    assert "Motori" not in lib.folders() and "Archivio" in lib.folders()
    with pytest.raises(LibraryError, match="dentro sé stessa"):
        lib.rename_folder("Archivio", "Archivio/x")
    with pytest.raises(LibraryError, match="Esiste già"):
        lib.rename_folder("Archivio/Motori", "Trattori")
    with pytest.raises(LibraryError, match="contiene 2 cataloghi"):
        lib.delete_folder("Archivio")
    lib.move([a, b], "")
    lib.delete_folder("Archivio")
    assert lib.folders() == ["Trattori"]


def test_delete_only_outside_projects(app, pdf_factory):
    doc = app.add_to_library(pdf_factory("Alfa.pdf"))
    project = new_project(app, [doc])
    with pytest.raises(LibraryError, match="toglilo prima"):
        app.delete_document(doc)
    app.remove_project(project)
    assert app.documents.list()               # il PDF resta
    app.delete_document(doc)
    assert app.documents.list() == []


def test_api_library(client, app, pdf_factory):
    alfa_pdf = pdf_factory("Alfa.pdf", pages=12)
    alfa = upload(client, alfa_pdf, folder="Motori")
    upload(client, pdf_factory("Beta.pdf", pages=4), folder="Motori/VM")
    copy = alfa_pdf.with_name("Copia di Alfa.pdf")
    copy.write_bytes(alfa_pdf.read_bytes())
    again = upload(client, copy)                                    # stesso contenuto, altro nome
    assert again["already_present"] and again["id"] == alfa["id"] and again["folder"] == "Motori"
    bad = client.post("/api/library/catalogs", files={"file": ("x.txt", b"x", "text/plain")})
    assert bad.status_code == 400

    r = client.put("/api/library/catalogs/alfa", json={
        "title": "Catalogo Alfa 2024", "description": "Motori agricoli", "tags": ["motori", "Motori", "diesel"],
        "fields": [{"name": "motore", "description": "modello"}, {"name": "alesaggio"}, {"name": " "}]}).json()
    assert r["title"] == "Catalogo Alfa 2024" and r["tags"] == ["motori", "diesel"]
    assert [f["name"] for f in r["fields"]] == ["motore", "alesaggio"]
    dup = client.put("/api/library/catalogs/alfa", json={"fields": [{"name": "a"}, {"name": "A"}]})
    assert dup.status_code == 400

    r = client.post("/api/library/catalogs/alfa/collections",
                    json={"start": 3, "end": 10, "tag": "dati", "comment": "tabelle"}).json()
    cid = r["collections"][0]["id"]
    client.post("/api/library/catalogs/alfa/collections", json={"start": 4, "end": 5, "tag": "esempio"})
    assert client.post("/api/library/catalogs/alfa/collections",
                       json={"start": 3, "end": 30, "tag": "indice"}).status_code == 400
    assert client.put(f"/api/library/catalogs/alfa/collections/{cid}",
                      json={"start": 3, "end": 11, "tag": "dati"}).json()["to_index"] == 9

    client.post("/api/library/tags", json={"ids": ["alfa", "beta"], "add": ["da studiare"], "remove": ["diesel"]})
    overview = client.get("/api/library/catalogs").json()
    assert overview["folders"] == ["Motori", "Motori/VM"]
    assert {t["name"]: t["count"] for t in overview["tags"]} == {"da studiare": 2, "motori": 1}
    assert [t["id"] for t in overview["page_tags"]][:2] == ["dati", "esempio"]

    assert client.post("/api/library/folders", json={"path": "Nuova"}).json()["folder"] == "Nuova"
    client.post("/api/library/move", json={"ids": ["beta"], "folder": "Nuova"})
    assert client.put("/api/library/folders", json={"path": "Nuova", "new_path": "Altro"}).json()["folder"] == "Altro"
    assert client.delete("/api/library/folders", params={"path": "Altro"}).status_code == 400
    assert client.post("/api/library/move", json={"ids": []}).status_code == 400

    # i progetti si creano solo dalla scheda di un catalogo (non più dalla selezione, né vuoti)
    assert client.post("/api/library/projects", json={"name": "X", "ids": ["alfa"]}).status_code in (404, 405)
    assert client.post("/api/projects", json={"name": "X"}).status_code in (404, 405)
    client.put("/api/library/catalogs/alfa", json={"guide": "# Guida Alfa"})
    project = client.post("/api/library/catalogs/alfa/guided/direct",
                          json={"name": "Motori", **TABLE}).json()["project"]
    stored = yaml.safe_load((app.projects.get(project["id"]).folder / "project.yaml").read_text(encoding="utf-8"))
    assert stored["settings"]["alfa"]["pages"] == "3-11" and len(stored["settings"]["alfa"]["collections"]) == 1
    assert stored["settings"]["alfa"]["guide"] == "# Guida Alfa\n" and stored["fields"][0]["header"] is True
    assert client.delete("/api/library/catalogs/alfa").status_code == 400      # usato dal progetto

    other = client.post("/api/library/catalogs/beta/guided/direct", json={"name": "Altro", **TABLE}).json()["project"]
    added = client.post(f"/api/projects/{other['id']}/documents/from-library", json={"ids": ["alfa", "beta"]})
    assert added.json()["added"] == ["alfa"]
    assert client.post(f"/api/projects/{other['id']}/documents/from-library",
                       json={"ids": ["alfa"]}).json()["added"] == []
    assert app.projects.get(other["id"]).settings_for("alfa").guide == "# Guida Alfa\n"
    summary = client.get("/api/library/catalogs/alfa").json()
    assert {p["name"] for p in summary["projects"]} == {"Motori", "Altro"}


def test_card_defaults_and_key_pages(app, pdf_factory):
    card = LibraryCard()
    assert card.folder == "" and card.pages_with_tag("esempio") == [] and not card.analyzed and card.guide == ""
    doc = app.add_to_library(pdf_factory("Alfa.pdf", pages=20))
    for start, end, tag in [(1, 1, "copertina"), (2, 3, "indice"), (4, 4, "legenda"), (6, 9, "dati"),
                            (7, 7, "esempio"), (12, 15, "dati"), (16, 18, "disegni")]:
        app.library.add_collection(doc, start, end, tag)
    assert app.library.card(doc).key_pages() == [2, 3, 4, 6, 7, 12]


def test_old_page_tag_is_renamed(app, pdf_factory):
    """Le schede salvate con il vecchio tag "da-indicizzare" si leggono come "dati"."""
    doc = app.add_to_library(pdf_factory("Alfa.pdf", pages=6))
    path = app.library.card_path(doc)
    text = path.read_text(encoding="utf-8").replace("collections: []", (
        "collections:\n- id: vecchia01\n  start: 2\n  end: 4\n  tag: da-indicizzare\n  comment: tabelle\n"))
    path.write_text(text, encoding="utf-8")
    card = app.library.card(doc)
    assert card.collections[0].tag == "dati" and card.pages_with_tag("dati") == [2, 3, 4]
    project = new_project(app, [doc])
    assert project.settings_for(doc.id).pages == "2-4"
