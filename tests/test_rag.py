"""Modalità RAG: descrizione delle pagine con la guida del catalogo, indice, risposte con le fonti."""

import hashlib
import re

import pytest
from fake_index import FakeIndex

from docanalyzer.app import App
from docanalyzer.core.fake_gemini import FakeGeminiClient
from docanalyzer.core.fileio import read_json
from docanalyzer.rag.pipeline import NO_GUIDE, QueryEngine, build_index, describe_document


def describer(request):
    """Gemini simulato: descrive la pagina con il suo numero; risponde citando la prima fonte."""
    if "DOMANDA" in request.prompt:
        source = re.search(r"\[FONTE 1: (.+?)\]", request.prompt).group(1)
        return f"Risposta basata su {source}."
    n = re.search(r"pagina (\d+) di", request.prompt).group(1)
    return f"Pagina {n}: tabella dei filtri olio del motore M{n}."


@pytest.fixture
def app(config):
    return App(config, client=FakeGeminiClient(describer, parallelism=2))


def test_describe_uses_the_catalog_guide_and_resumes(app, pdf_factory):
    doc = app.add_to_library(pdf_factory("Alfa.pdf", pages=4))
    card = app.library.card(doc)
    card.guide = "# Guida Alfa\n\nIl modello del motore è nel titolo."
    app.library.save_card(doc, card)

    guide = app.guide_text(doc)
    report = describe_document(doc, guide, app.client(), app.config, pages=[1, 3], show_progress=False)
    assert report.succeeded == 2
    prompts = [r.prompt for r in app.client().requests]
    assert len(prompts) == 2 and all("Il modello del motore è nel titolo." in p for p in prompts)
    assert read_json(doc.descriptions_dir / "page-0003.json")["description"].startswith("Pagina 3:")

    # riprendibile: le pagine fatte non si rifanno; force le rifà
    assert describe_document(doc, guide, app.client(), app.config, pages=[1, 3], show_progress=False).requested == 0
    report = describe_document(doc, guide, app.client(), app.config, show_progress=False)
    assert report.requested == 2 and len(app.client().requests) == 4          # solo le pagine 2 e 4
    report = describe_document(doc, guide, app.client(), app.config, pages=[1], force=True, show_progress=False)
    assert report.succeeded == 1


def test_describe_without_guide(app, pdf_factory):
    doc = app.add_to_library(pdf_factory("Beta.pdf", pages=1))
    assert app.guide_text(doc) == ""
    describe_document(doc, app.guide_text(doc), app.client(), app.config, show_progress=False)
    assert NO_GUIDE in app.client().requests[0].prompt


def test_build_index_and_answer_with_sources(app, pdf_factory):
    alfa = app.add_to_library(pdf_factory("Alfa.pdf", pages=3))
    beta = app.add_to_library(pdf_factory("Beta.pdf", pages=2))
    for doc in (alfa, beta):
        describe_document(doc, "", app.client(), app.config, show_progress=False)
    index = FakeIndex()
    assert build_index([alfa, beta], index) == 5
    assert index.items["alfa:2"][1] == {"doc_id": "alfa", "source": "Alfa.pdf", "page": 2}

    engine = QueryEngine(index, app.client(), app.config)
    answer = engine.ask("filtri olio del motore M2")
    assert answer.text.startswith("Risposta basata su")
    assert len(answer.sources) == app.config.rag.top_k
    assert {s["page"] for s in answer.sources} >= {2}
    prompt = app.client().requests[-1].prompt
    assert "[FONTE 1:" in prompt and "filtri olio del motore M2" in prompt

    # solo un documento
    answer = engine.ask("motore", doc_id="beta")
    assert index.queries[-1][2] == {"doc_id": "beta"} and {s["source"] for s in answer.sources} == {"Beta.pdf"}
    # niente di pertinente, domanda vuota
    assert QueryEngine(FakeIndex(), app.client(), app.config).ask("motore").sources == []
    with pytest.raises(ValueError, match="vuota"):
        engine.ask("   ")


def word_hash_embedding():
    """Embedding deterministico per i test: conta le parole in 64 "secchi" (niente download)."""
    from chromadb.api.types import EmbeddingFunction

    class WordHashEmbedding(EmbeddingFunction):
        def __init__(self):
            pass

        def __call__(self, input):
            out = []
            for text in input:
                vec = [0.0] * 64
                for w in re.findall(r"\w+", text.lower()):
                    vec[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
                norm = sum(v * v for v in vec) ** 0.5 or 1.0
                out.append([v / norm for v in vec])
            return out

        @staticmethod
        def name():
            return "word-hash-test"

        def get_config(self):
            return {}

        @staticmethod
        def build_from_config(config):
            return WordHashEmbedding()

    return WordHashEmbedding()


def test_vector_index_with_chromadb(tmp_path):
    pytest.importorskip("chromadb")
    from docanalyzer.rag.vector_index import VectorIndex

    index = VectorIndex(tmp_path / "indice", "prova", embedding_function=word_hash_embedding())
    assert index.query("qualsiasi cosa", 3) == []                       # indice vuoto
    index.upsert(["a:1", "a:2", "b:1"],
                 ["filtro olio motore diesel", "pompa acqua motore", "cinghia distribuzione"],
                 [{"doc_id": "a", "source": "A.pdf", "page": 1}, {"doc_id": "a", "source": "A.pdf", "page": 2},
                  {"doc_id": "b", "source": "B.pdf", "page": 1}])
    assert index.count() == 3
    hits = index.query("filtro olio", 5)
    assert len(hits) == 3 and hits[0]["metadata"]["page"] == 1 and hits[0]["metadata"]["doc_id"] == "a"
    assert [h["metadata"]["doc_id"] for h in index.query("motore", 5, where={"doc_id": "b"})] == ["b"]
    index.upsert(["a:1"], ["cinghia nuova"], [{"doc_id": "a", "source": "A.pdf", "page": 1}])   # sostituisce
    assert index.count() == 3 and index.query("cinghia nuova", 1)[0]["text"] == "cinghia nuova"
    index.delete_document("a")
    assert index.count() == 1
