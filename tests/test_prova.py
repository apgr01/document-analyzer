"""③ Prova: campione di pagine, estrazione con le regole vere, risultati, riuso nell'indicizzazione."""

import re

import pytest
from conftest import new_project

from docanalyzer.app import App
from docanalyzer.core.fake_gemini import FakeGeminiClient
from docanalyzer.core.projects import DocumentSettings, ProjectError
from docanalyzer.prova import default_plan, is_stale, load_state, prova_view, run_prova, sample_pages, seed_index


def responder(req):
    n = int(re.search(r"pagina (\d+) di", req.prompt).group(1))
    return {"page_summary": f"pagina {n}", "page_context": {"motore": f"M{n}"},
            "rows": [{"motore": "", "codice": f"C{n}"}], "notes": "dubbio" if n == 7 else ""}


@pytest.fixture
def setup(config, pdf_factory):
    app = App(config, client=FakeGeminiClient(responder))
    alfa = app.add_to_library(pdf_factory("Alfa.pdf", pages=30, prefix="A"))
    beta = app.add_to_library(pdf_factory("Beta.pdf", pages=5, prefix="B"))
    lib = app.library
    lib.add_collection(alfa, 5, 24, "dati")
    lib.add_collection(alfa, 7, 7, "esempio")
    lib.add_collection(alfa, 2, 2, "esempio")            # esempio fuori dalle pagine da indicizzare
    project = new_project(app, [alfa, beta])
    return app, project, alfa, beta


def test_sample_pages(setup):
    app, project, alfa, beta = setup
    pages = sample_pages(app, project, alfa)
    # prima la pagina d'esempio che è anche da indicizzare (7), poi distribuite tra le pagine 5-24
    assert len(pages) == 4 and 7 in pages and 2 not in pages and all(5 <= p <= 24 for p in pages)
    assert len(sample_pages(app, project, alfa, 10)) == 10
    assert sample_pages(app, project, beta) == [1, 2, 4, 5] and sample_pages(app, project, beta, 9) == [1, 2, 3, 4, 5]
    assert sample_pages(app, project, alfa, 3, exclude=set(range(5, 23))) == [23, 24]
    assert default_plan(app, project, 2, doc_ids=["beta"]) == {"beta": [2, 4]}


def test_run_view_and_more_pages(setup):
    app, project, alfa, beta = setup
    plan = default_plan(app, project)
    summary = run_prova(app, project, plan)
    assert summary == {"pages": 8, "failed": 0, "rows": 8}
    assert not alfa.extraction_dir(project.id).exists()           # niente nell'indicizzazione vera
    view = prova_view(app, project)
    assert view["available"] and [d["id"] for d in view["documents"]] == ["alfa", "beta"]
    a = view["documents"][0]
    assert a["pages"] == plan["alfa"] and len(a["rows"]) == 4 and a["notes"] == {"7": "dubbio"}
    assert a["columns"] == ["MOTORE", "CODICE", "PAGINA_PDF", "FILE_ORIGINE"] and a["rows"][0]["MOTORE"].startswith("M")
    assert not a["stale"] and view["csv"] == f"{project.id}_prova.csv"
    assert is_stale(app, project) is False
    # altre pagine: mai provate prima
    more = default_plan(app, project, more=True)
    assert not set(more["alfa"]) & set(plan["alfa"]) and more["beta"] == [3]
    # prova solo su Beta: quella di Alfa resta
    run_prova(app, project, {"beta": [3]})
    view = prova_view(app, project)
    assert view["documents"][1]["pages"] == [3] and view["documents"][0]["pages"] == plan["alfa"]
    assert load_state(project)["history"]["beta"] == [1, 2, 3, 4, 5]


def test_errors(setup):
    app, project, alfa, beta = setup
    assert is_stale(app, project) is None and not prova_view(app, project)["available"]
    with pytest.raises(ProjectError, match="almeno"):
        run_prova(app, project, {"alfa": []})
    with pytest.raises(ProjectError, match="fuori"):
        run_prova(app, project, {"beta": [6]})
    with pytest.raises(ProjectError, match="non fa parte"):
        run_prova(app, project, {"gamma": [1]})


def test_changes_make_the_prova_stale(setup):
    app, project, alfa, beta = setup
    run_prova(app, project, {"alfa": [7], "beta": [1]})
    project.set_settings(beta.id, DocumentSettings(notes="nuova nota"))
    view = prova_view(app, project)
    assert [d["stale"] for d in view["documents"]] == [False, True] and is_stale(app, project) is True
    project.set_settings(beta.id, DocumentSettings())
    assert is_stale(app, project) is False
    project.info.row = "altra riga"
    assert is_stale(app, project) is True


def test_prova_pages_are_reused_by_the_indexing(setup):
    app, project, alfa, beta = setup
    run_prova(app, project, {"alfa": [7, 25], "beta": [1]})
    extractor = app.extractor()
    spec, guide = app.document_rules(project, alfa)
    before = len(app.client().requests)
    # solo le pagine da indicizzare: la 25 è fuori dalla selezione e non viene copiata
    assert seed_index(app, project, alfa, spec, guide, extractor) == 1
    report = extractor.run(alfa, spec, guide, show_progress=False)
    assert report.requested == 19 and len(app.client().requests) - before == 19
    # regole cambiate dopo la prova: niente riuso
    project.set_settings(beta.id, DocumentSettings(notes="x"))
    assert seed_index(app, project, beta, *app.document_rules(project, beta), extractor) == 0
