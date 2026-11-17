import pytest

from docanalyzer.core.documents import DocumentError, DuplicateDocumentError
from docanalyzer.core.workspace import slugify


def test_slugify():
    assert slugify("Catalogo 5 ACME rel 2") == "catalogo-5-acme-rel-2"
    assert slugify("Più è già") == "piu-e-gia"
    assert slugify("***") == "documento"


def test_add_and_get(store, pdf_factory):
    doc = store.add(pdf_factory("Catalogo 5 ACME rel 2.pdf", pages=2))
    assert doc.id == "catalogo-5-acme-rel-2"
    assert doc.info.page_count == 2
    assert doc.pdf_path.exists()

    assert store.get("catalogo-5-acme-rel-2").id == doc.id
    assert store.get("Catalogo 5 ACME rel 2.pdf").id == doc.id
    assert store.get("catalogo-5").id == doc.id          # parte dell'id
    assert [d.id for d in store.list()] == [doc.id]


def test_duplicate_content_is_detected(store, pdf_factory, tmp_path):
    pdf = pdf_factory("a.pdf")
    store.add(pdf)
    copy = tmp_path / "copia con altro nome.pdf"
    copy.write_bytes(pdf.read_bytes())
    with pytest.raises(DuplicateDocumentError) as exc:
        store.add(copy)
    assert exc.value.existing.id == "a"


def test_same_name_different_content_gets_new_id(store, pdf_factory, tmp_path):
    first = store.add(pdf_factory("cat.pdf", prefix="A"))
    other = tmp_path / "altra"
    other.mkdir()
    from conftest import make_pdf

    second = store.add(make_pdf(other / "cat.pdf", prefix="B"))
    assert (first.id, second.id) == ("cat", "cat-2")


def test_get_errors(store, pdf_factory):
    with pytest.raises(DocumentError, match="non contiene documenti"):
        store.get("x")
    store.add(pdf_factory("motori alfa.pdf", prefix="A"))
    store.add(pdf_factory("motori beta.pdf", prefix="B"))
    with pytest.raises(DocumentError, match="più documenti"):
        store.get("motori")
    with pytest.raises(DocumentError, match="non trovato"):
        store.get("gamma")


def test_not_a_pdf(store, tmp_path):
    txt = tmp_path / "file.txt"
    txt.write_text("ciao")
    with pytest.raises(DocumentError, match="non è un PDF"):
        store.add(txt)
