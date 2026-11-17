"""Progetti: Tabella, PDF dalla biblioteca (pagine e guida copiate), regole composte, CSV unico."""

import json
import re

import pytest
from conftest import new_project

from docanalyzer.app import App
from docanalyzer.core.fake_gemini import FakeGeminiClient
from docanalyzer.core.library import LibraryError
from docanalyzer.core.projects import AUTO_COLUMNS, DocumentSettings, ProjectError, clean_columns
from docanalyzer.indexing.extractor import SpecChangedError
from docanalyzer.indexing.spec import OutputSpec, read_csv_rows


def responder(req):
    """Ogni pagina ha il codice 'COMUNE' (presente in tutti i PDF) e uno proprio."""
    n = int(re.search(r"pagina (\d+) di", req.prompt).group(1))
    return {"page_summary": "", "page_context": {"motore": f"M{n}"},
            "rows": [{"motore": "", "codice": "COMUNE"}, {"motore": "", "codice": f"C{n}"}], "notes": ""}


@pytest.fixture
def app(config):
    return App(config, client=FakeGeminiClient(responder, parallelism=2))


@pytest.fixture
def setup(app, pdf_factory):
    alfa = app.add_to_library(pdf_factory("Alfa.pdf", pages=6, prefix="A"), folder="Motori")
    beta = app.add_to_library(pdf_factory("Beta.pdf", pages=4, prefix="B"))
    lib = app.library
    a1 = lib.add_collection(alfa, 2, 3, "dati", "tabelle motori")
    a2 = lib.add_collection(alfa, 5, 5, "dati", "tabelle accessori")
    lib.add_collection(alfa, 1, 1, "indice")
    lib.save_card(alfa, lib.card(alfa).model_copy(update={"guide": "# Guida Alfa\n"}))
    project = new_project(app, [alfa, beta], name="Motori Diesel", description="Ricambi", instructions="niente spazi")
    return project, alfa, beta, a1, a2


def index_all(app, project):
    extractor = app.extractor()
    for doc in app.project_documents(project):
        extractor.run(doc, *app.document_rules(project, doc), show_progress=False)


def test_clean_columns_and_store(app, pdf_factory):
    assert clean_columns([{"name": " A  b ", "description": " x ", "header": 1}, {"name": ""}, {"name": "C"}]) == [
        {"name": "A b", "description": "x", "header": True, "key": False},
        {"name": "C", "description": "", "header": False, "key": False}]
    with pytest.raises(ProjectError, match="due volte"):
        clean_columns([{"name": "A"}, {"name": "a"}])
    # le due colonne che il programma aggiunge a ogni riga: nomi riservati
    assert list(AUTO_COLUMNS) == [OutputSpec().page_column, OutputSpec().source_column]
    for name in ("FILE_ORIGINE", " pagina_pdf "):
        with pytest.raises(ProjectError, match="la aggiunge già il programma"):
            clean_columns([{"name": "MOTORE"}, {"name": name}])
    doc = app.add_to_library(pdf_factory("Uno.pdf"))
    project = new_project(app, [doc], name="Motori Diesel")
    assert project.id == "motori-diesel" and new_project(app, [doc], name="Motori Diesel").id == "motori-diesel-2"
    assert app.projects.get("Motori Diesel").id == "motori-diesel"
    with pytest.raises(ProjectError, match="non trovato"):
        app.projects.get("nessuno")
    assert [p.id for p in app.projects.containing(doc.id)] == ["motori-diesel", "motori-diesel-2"]
    with pytest.raises(ProjectError, match="nome"):
        new_project(app, [doc], name="  ")
    with pytest.raises(ProjectError, match="Compila la tabella"):
        new_project(app, [doc], row=" ")
    with pytest.raises(ProjectError, match="Compila la tabella"):
        new_project(app, [doc], columns=[{"name": " "}])
    app.add_to_project(project, doc)                                   # già presente: niente doppioni
    assert app.projects.get(project.id).info.documents == [doc.id]


def test_pages_and_guide_are_copied(app, setup):
    project, alfa, beta, a1, a2 = setup
    s = project.settings_for(alfa.id)
    assert (s.pages, s.collections, s.guide) == ("2-3, 5", [a1.id, a2.id], "# Guida Alfa\n")
    # Beta non ha collezioni "dati" né guida: tutto il PDF, nessuna guida
    assert project.settings_for(beta.id).is_empty
    stored = json.loads(json.dumps(project.info.model_dump()))
    assert stored["fields"][0] == {"name": "MOTORE", "description": "modello", "header": True, "key": False}


def test_rules_are_composed_from_table_guide_and_notes(app, setup):
    project, alfa, beta, *_ = setup
    base = app.project_rules(project)
    assert base.name == project.id and base.row == "una riga per ogni codice" and base.description == "Ricambi"
    assert [(c.name, c.context) for c in base.columns] == [("MOTORE", True), ("CODICE", False)]
    assert base.instructions == "niente spazi"
    project.set_settings(beta.id, DocumentSettings(notes="Il codice è in basso.", pages="2"))
    spec, guide = app.document_rules(project, beta, base)
    assert "NOTE SPECIFICHE PER QUESTO PDF (Beta)" in spec.instructions and spec.pages == "2" and guide == ""
    spec, guide = app.document_rules(project, alfa, base)
    assert spec.instructions == "niente spazi" and spec.pages == "2-3, 5" and guide == "# Guida Alfa\n"
    project.info.row = ""
    with pytest.raises(ProjectError, match="Tabella"):
        app.project_rules(project)
    assert app.project_progress(project) is None


def test_index_and_merged_csv(app, setup):
    project, alfa, beta, *_ = setup
    index_all(app, project)
    # la guida del catalogo accompagna ogni sua pagina
    prompts = [r.prompt for r in app.client().requests]
    assert sum("# Guida Alfa" in p for p in prompts) == 3 and sum("nessuna guida" in p for p in prompts) == 4
    result = app.export_project(project)
    columns, rows = read_csv_rows(result.csv_path)
    assert result.csv_path.name == "motori-diesel.csv"
    assert columns == ["MOTORE", "CODICE", "PAGINA_PDF", "FILE_ORIGINE"]
    # 'COMUNE' compare su ogni pagina indicizzata di entrambi i PDF: tutte le occorrenze restano
    comune = sorted((r["FILE_ORIGINE"], r["PAGINA_PDF"]) for r in rows if r["CODICE"] == "COMUNE")
    assert comune == [("Alfa.pdf", "2"), ("Alfa.pdf", "3"), ("Alfa.pdf", "5")] + [
        ("Beta.pdf", str(n)) for n in range(1, 5)]
    assert {r["MOTORE"] for r in rows if r["PAGINA_PDF"] == "3" and r["FILE_ORIGINE"] == "Alfa.pdf"} == {"M3"}
    assert result.index.stats["documenti_indicizzati"] == 2
    per_doc = {d.id: r.csv_path for d, r in result.documents}
    assert per_doc["alfa"].parent.name == "documenti" and per_doc["alfa"].exists()
    assert app.project_progress(project) == {"to_index": 7, "done": 7, "failed": 0, "stale": []}


def test_changes_make_only_the_right_documents_stale(app, setup):
    project, alfa, beta, *_ = setup
    index_all(app, project)
    extractor = app.extractor()
    # note di un PDF: solo quel PDF
    project.set_settings(beta.id, DocumentSettings(notes="nuova nota"))
    project.save()
    extractor.open_manifest(alfa, *app.document_rules(project, alfa))
    with pytest.raises(SpecChangedError):
        extractor.open_manifest(beta, *app.document_rules(project, beta))
    assert [d.id for d in app.export_project(project).stale] == ["beta"]
    assert app.project_progress(project)["stale"] == ["beta"]
    # guida di un PDF (aggiornata dalla biblioteca): solo quel PDF
    project.set_settings(beta.id, DocumentSettings())
    app.library.save_card(alfa, app.library.card(alfa).model_copy(update={"guide": "# Guida nuova\n"}))
    assert [c["guide_changed"] for c in app.library_changes(project)] == [True, False]
    app.update_from_library(project, [alfa.id])
    assert [d.id for d in app.export_project(project).stale] == ["alfa"]
    # tabella: tutti
    project.info.instructions = "altro"
    assert {d.id for d in app.export_project(project).stale} == {"alfa", "beta"}


def test_missing_documents_are_reported(app, setup):
    project, alfa, beta, *_ = setup
    app.extractor().run(alfa, *app.document_rules(project, alfa), show_progress=False)
    result = app.export_project(project)
    assert [d.id for d in result.not_indexed] == ["beta"]


def test_library_changes_and_update(app, setup):
    project, alfa, beta, a1, a2 = setup
    assert [c["changed"] for c in app.library_changes(project)] == [False, False]
    # la biblioteca cambia: il progetto no (le pagine sono una copia), ma lo segnala
    app.library.update_collection(alfa, a1.id, 2, 4, "dati", "tabelle motori")
    app.library.remove_collection(alfa, a2.id)
    c = app.library.add_collection(alfa, 6, 6, "dati", "nuove tabelle")
    change = app.library_changes(project)[0]
    assert project.settings_for(alfa.id).pages == "2-3, 5"
    assert change["changed"] and change["pages_changed"] and not change["guide_changed"]
    assert change["library_pages"] == "2-4" and change["missing"] == 1
    assert [x["id"] for x in change["new_data"]] == [c.id]          # solo un suggerimento
    assert app.update_from_library(project, [alfa.id]) == [alfa.id]
    settings = project.settings_for(alfa.id)
    assert settings.pages == "2-4" and settings.collections == [a1.id] and settings.guide == "# Guida Alfa\n"
    assert app.library_changes(project)[0]["changed"] is False
    # una guida aggiunta nella biblioteca dopo la creazione del progetto
    app.library.save_card(beta, app.library.card(beta).model_copy(update={"guide": "# Guida Beta\n"}))
    assert app.library_changes(project)[1]["guide_changed"] and app.update_from_library(project, [beta.id])
    assert project.settings_for(beta.id).guide == "# Guida Beta\n"
    app.library.remove_collection(alfa, a1.id)
    with pytest.raises(LibraryError, match="nessuna delle collezioni"):
        app.update_from_library(project, [alfa.id])


def test_document_in_projects(app, setup):
    project, alfa, beta, *_ = setup
    other = new_project(app, [alfa], name="Componenti")
    other.info.fields = []
    other.save()
    items = {p["name"]: p for p in app.document_in_projects(alfa)}
    assert set(items) == {"Motori Diesel", "Componenti"} and items["Componenti"]["configured"] is False
    motori = items["Motori Diesel"]
    assert motori["pages"] == "2-3, 5" and motori["from_library"] and motori["has_guide"] and not motori["csv"]
    index_all(app, project)
    motori = {p["name"]: p for p in app.document_in_projects(alfa)}["Motori Diesel"]
    assert (motori["to_index"], motori["done"], motori["csv"], motori["stale"]) == (3, 3, True, False)
    assert (app.project_export_dir(project) / "documenti" / "alfa.csv").exists()


def test_remove(app, setup):
    project, alfa, beta, *_ = setup
    app.remove_from_project(project, beta)
    assert app.projects.get(project.id).info.documents == ["alfa"] and app.documents.get("beta")
    app.remove_project(project)
    assert app.projects.list() == [] and len(app.documents.list()) == 2


def test_search_page(app, setup):
    project, *_ = setup
    index_all(app, project)
    result = app.export_project(project)
    html = result.search_page.read_text(encoding="utf-8")
    assert result.search_page.name == "ricerca.html" and "<title>Ricerca — Motori Diesel</title>" in html
    data = json.loads(html.split("const D = ", 1)[1].split(";\nconst PAGE", 1)[0])
    assert data["columns"] == ["MOTORE", "CODICE", "PAGINA_PDF", "FILE_ORIGINE"] and len(data["rows"]) == 14
    assert data["files"] == {"Alfa.pdf": "alfa", "Beta.pdf": "beta"}
    assert data["page_col"] == 2 and data["source_col"] == 3
    assert data["pdf_link"].startswith("../../documents/")
    assert "</script>" not in html.split("const D = ", 1)[1].split("const PAGE", 1)[0]


def test_send_mode(app, setup):
    project, *_ = setup
    assert project.info.send_mode == "pagina" and app.send_options(project) == {"send": "pagina", "max_pages": None}
    project.set_send("insieme", 10)
    assert app.send_options(project) == {"send": "insieme", "max_pages": 10}
    project.set_send("pagina", 10)                          # il massimo vale solo per "insieme"
    assert project.info.pages_per_request is None
    with pytest.raises(ProjectError, match="sconosciuta"):
        project.set_send("tutto")
    with pytest.raises(ProjectError, match="almeno 1"):
        project.set_send("insieme", 0)
    # la modalità di invio non cambia le regole: niente da rifare
    index_all(app, project)
    project.set_send("insieme")
    assert app.export_project(project).stale == []
