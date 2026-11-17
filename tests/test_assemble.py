from docanalyzer.indexing.assemble import ERROR, INFO, WARNING, assemble, merge
from docanalyzer.indexing.spec import IndexingSpec


def make_spec(**kw):
    data = {
        "name": "t",
        "row": "un codice",
        "columns": [
            {"name": "MOTORE", "context": True, "required": True},
            {"name": "CILINDRI", "type": "integer", "context": True},
            {"name": "CODICE", "required": True, "pattern": "RC.*"},
        ],
    }
    data.update(kw)
    return IndexingSpec.model_validate(data)


def page(rows, context=None, notes=""):
    return {"rows": rows, "page_context": context or {}, "notes": notes}


def test_context_inheritance_and_normalization():
    spec = make_spec()
    results = {
        1: page([], {"MOTORE": "MX 450/S", "CILINDRI": "1.0"}),            # solo intestazione
        2: page([{"MOTORE": "", "CILINDRI": "", "CODICE": " RC001  AF "}]),  # tabella che continua
        3: page([{"MOTORE": "", "CILINDRI": "", "CODICE": "RC002"}], {"MOTORE": "MX 100", "CILINDRI": "2"}),
    }
    idx = assemble(spec, results, "cat.pdf", expected_pages=[1, 2, 3])
    assert idx.columns == ["MOTORE", "CILINDRI", "CODICE", "PAGINA_PDF", "FILE_ORIGINE"]
    assert idx.rows == [
        {"MOTORE": "MX 450/S", "CILINDRI": "1", "CODICE": "RC001 AF", "PAGINA_PDF": "2", "FILE_ORIGINE": "cat.pdf",
         "_src": [2, 0]},
        {"MOTORE": "MX 100", "CILINDRI": "2", "CODICE": "RC002", "PAGINA_PDF": "3", "FILE_ORIGINE": "cat.pdf",
         "_src": [3, 0]},
    ]
    assert idx.stats["valori_ereditati"] == 2
    assert idx.anomalies == []


def test_no_inheritance_when_disabled():
    spec = make_spec(inherit_context=False)
    results = {1: page([], {"MOTORE": "A"}), 2: page([{"CODICE": "RC1"}])}
    idx = assemble(spec, results, "c.pdf", [1, 2])
    assert idx.rows[0]["MOTORE"] == ""
    assert [(a.level, a.column) for a in idx.anomalies] == [(ERROR, "MOTORE")]


def test_anomalies_dedupe_sort_and_missing_pages():
    spec = make_spec(output={"page_column": None, "source_column": None, "sort_by": ["CODICE"]})
    rows = [
        {"MOTORE": "M", "CILINDRI": "due", "CODICE": "RC9"},
        {"MOTORE": "M", "CILINDRI": "2", "CODICE": "XYZ"},
        {"MOTORE": "M", "CILINDRI": "2", "CODICE": "XYZ"},   # duplicato
        {"MOTORE": "", "CILINDRI": "", "CODICE": ""},        # vuota: scartata
    ]
    idx = assemble(spec, {1: page(rows, notes="testo poco leggibile")}, "c.pdf", [1, 2, 3], {2: "timeout"})
    assert [r["CODICE"] for r in idx.rows] == ["RC9", "XYZ"]
    assert idx.stats["duplicati_rimossi"] == 1
    found = {(a.level, a.page, a.csv_row, a.column, a.problem) for a in idx.anomalies}
    assert (WARNING, 1, 2, "CILINDRI", "non è un numero intero") in found
    assert (WARNING, 1, 3, "CODICE", "non rispetta il formato RC.*") in found
    assert (ERROR, 2, None, None, "pagina non elaborata (timeout)") in found
    assert (INFO, 1, None, None, "nota del modello: testo poco leggibile") in found
    assert (INFO, 3, None, None, "pagina non ancora elaborata") in found
    assert idx.stats["pagine_da_elaborare"] == 1 and idx.stats["errori"] == 1


def test_default_value():
    spec = make_spec(columns=[{"name": "A", "default": "N/D"}, {"name": "B"}])
    idx = assemble(spec, {1: page([{"A": "", "B": "x"}])}, "c.pdf", [1])
    assert idx.rows[0]["A"] == "N/D"


def test_merge_removes_duplicates_across_documents():
    spec = make_spec(output={"source_column": None, "page_column": None})
    a = assemble(spec, {1: page([{"MOTORE": "M", "CODICE": "RC1"}])}, "a.pdf", [1])
    b = assemble(spec, {1: page([{"MOTORE": "M", "CODICE": "RC1"}, {"MOTORE": "N", "CODICE": "RC2"}])}, "b.pdf", [1])
    merged = merge(spec, [a, b])
    assert len(merged.rows) == 2 and merged.stats["duplicati_rimossi"] == 1
