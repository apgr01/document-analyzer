"""Regole di estrazione: validazione, impronta e prompt di pagina."""

import pytest

from docanalyzer.indexing.prompt import PromptBuilder, build_page_schema
from docanalyzer.indexing.spec import ColumnSpec, IndexingSpec, SpecError, load_spec


def write(tmp_path, text):
    path = tmp_path / "s.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_mapping_keeps_tricky_yaml_keys(tmp_path):
    spec = load_spec(write(tmp_path, "row: x\ncolumns:\n  - name: NR. CILINDRI\nmappings:\n  componenti:\n"
                                     "    values:\n      'NO': Ugello\n      01: Uno\n"))
    assert spec.mappings["componenti"].values == {"NO": "Ugello", "1": "Uno"}   # "NO" non diventa False
    assert spec.json_keys()["NR. CILINDRI"] == "nr_cilindri"


def test_spec_errors_are_readable(tmp_path):
    with pytest.raises(SpecError, match="row"):
        load_spec(write(tmp_path, "columns:\n  - name: A\n"))
    with pytest.raises(SpecError, match="duplicate"):
        load_spec(write(tmp_path, "row: x\ncolumns:\n  - name: A\n  - name: A\n"))
    with pytest.raises(SpecError, match="colum"):
        load_spec(write(tmp_path, "row: x\ncolums:\n  - name: A\n"))   # chiave sbagliata
    with pytest.raises(SpecError, match="regolare"):
        load_spec(write(tmp_path, "row: x\ncolumns:\n  - name: A\n    pattern: '['\n"))
    with pytest.raises(SpecError, match="sort_by"):
        load_spec(write(tmp_path, "row: x\ncolumns:\n  - name: A\noutput:\n  sort_by: [B]\n"))
    with pytest.raises(SpecError, match="examples"):          # niente più CSV d'esempio
        load_spec(write(tmp_path, "row: x\ncolumns:\n  - name: A\nexamples:\n  csv: es.csv\n"))


def test_fingerprint_changes_only_when_extraction_changes(tmp_path):
    base = "row: x\ncolumns:\n  - name: A\n    description: codice\n"
    spec = load_spec(write(tmp_path, base))
    fp = spec.extraction_fingerprint("guida", "m")
    assert load_spec(write(tmp_path, base + "    required: true\noutput:\n  delimiter: ';'\n")) \
        .extraction_fingerprint("guida", "m") == fp
    assert load_spec(write(tmp_path, base + "instructions: altro\n")).extraction_fingerprint("guida", "m") != fp
    assert load_spec(write(tmp_path, base + "description: a cosa serve\n")).extraction_fingerprint("guida", "m") != fp
    assert spec.extraction_fingerprint("guida modificata", "m") != fp
    assert spec.extraction_fingerprint("guida", "altro modello") != fp


def test_page_prompt_has_guide_table_and_header_columns():
    spec = IndexingSpec(name="p", description="Trovare i ricambi.", row="un codice", columns=[
        ColumnSpec(name="MOTORE", description="modello", context=True),
        ColumnSpec(name="MARCA", context=True), ColumnSpec(name="CODICE")])
    prompt = PromptBuilder(spec, "LA GUIDA DEL CATALOGO", total_pages=10).page_prompt(3)
    assert "guida all'indicizzazione" in prompt and "LA GUIDA DEL CATALOGO" in prompt
    assert "A cosa serve l'indice: Trovare i ricambi." in prompt and "Ogni riga rappresenta: un codice" in prompt
    assert "pagina 3 di 10" in prompt and "{{" not in prompt and "ESEMPIO DI RISULTATO" not in prompt
    assert prompt.count("DATO DI PAGINA") == 3       # 2 colonne + la regola, spiegata una volta
    assert "Nelle righe lasciale" in prompt
    schema = build_page_schema(spec)
    assert "page_context" in schema["properties"]
    assert schema["properties"]["rows"]["items"]["required"] == list(spec.json_keys().values())
    no_guide = PromptBuilder(spec.model_copy(update={"description": ""}), "", total_pages=1).page_prompt(1)
    assert "nessuna guida disponibile" in no_guide and "A cosa serve" not in no_guide
