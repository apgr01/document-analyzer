"""Prova dei comandi rimasti come li userebbe una persona (Gemini simulato)."""

import pytest
from conftest import new_project

from docanalyzer.app import App
from docanalyzer.cli import build_parser, main
from docanalyzer.core.config import load_config


@pytest.fixture
def run(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(f"workspace_dir: {(tmp_path / 'data').as_posix()}\nrender:\n  dpi: 72\n", encoding="utf-8")
    monkeypatch.setenv("DOCANALYZER_FAKE_GEMINI", "1")

    def _run(*args):
        return main(["--config", str(cfg), *args])

    _run.app = lambda: App(load_config(cfg))
    return _run


def test_commands_left():
    commands = set(build_parser()._subparsers._group_actions[0].choices)
    assert commands == {"ui", "doctor", "add", "list", "remove", "project", "rag"}


def test_library_commands(run, pdf_factory, capsys):
    pdf = pdf_factory("Catalogo Ricambi.pdf", pages=2)
    assert run("doctor") == 0
    assert run("add", str(pdf), "--folder", "Motori/VM") == 0
    assert run("add", str(pdf)) == 1                            # duplicato
    assert run("list") == 0
    out = capsys.readouterr().out
    assert "catalogo-ricambi" in out and "Motori/VM" in out and "Cataloghi nella biblioteca: 0" in out
    app = run.app()
    assert app.library.card(app.documents.get("catalogo-ricambi")).folder == "Motori/VM"
    assert run("remove", "catalogo-ricambi", "-y") == 0
    assert run.app().documents.list() == []


def test_project_commands(run, pdf_factory, tmp_path, capsys):
    run("add", str(pdf_factory("Alfa.pdf", pages=3, prefix="A")))
    assert run("project", "list") == 0
    assert "dalla scheda di un catalogo" in capsys.readouterr().out
    app = run.app()
    new_project(app, [app.documents.get("alfa")], name="Motori")
    assert run("project", "list") == 0
    assert "Motori" in capsys.readouterr().out
    assert run("remove", "alfa", "-y") == 1                     # usato dal progetto
    assert run("project", "index", "motori", "-y") == 0
    out = capsys.readouterr()
    assert "nessuna guida" in out.err + out.out and "CSV unico del progetto" in out.out
    assert (tmp_path / "data" / "exports" / "motori" / "motori.csv").exists()
    assert run("project", "export", "motori") == 0
    assert run("project", "index", "nessuno") == 1


def test_rag_commands(run, pdf_factory, monkeypatch, capsys):
    """describe con la guida del catalogo (anche solo alcune pagine), build e ask (indice finto)."""
    from fake_index import FakeIndex

    import docanalyzer.rag.vector_index as vector_index

    index = FakeIndex()
    monkeypatch.setattr(vector_index, "VectorIndex", lambda *a, **k: index)
    run("add", str(pdf_factory("Grande.pdf", pages=12)))
    assert run("rag", "ask", "che motori ci sono?") == 1                     # indice vuoto
    assert run("rag", "describe", "grande", "--pages", "1,4,10-11") == 0
    out = capsys.readouterr().out
    assert "non ha una guida all'indicizzazione" in out and "4 pagine completate" in out
    assert run("rag", "build") == 0 and index.count() == 4
    assert run("rag", "ask", "che motori ci sono?") == 0
    out = capsys.readouterr().out
    assert "[simulato]" in out and "Grande.pdf, pagina" in out
    assert run("rag", "describe") == 1                                      # nessun catalogo indicato


def test_project_index_together(run, pdf_factory, capsys):
    run("add", str(pdf_factory("Alfa.pdf", pages=4, prefix="A")))
    app = run.app()
    project = new_project(app, [app.documents.get("alfa")], name="Motori")
    project.set_send("insieme")
    project.save()
    assert run("project", "index", "motori", "-y") == 0
    out = capsys.readouterr().out
    assert "le pagine di ogni PDF insieme" in out and "Consumo: 1 richiesta a Gemini" in out
