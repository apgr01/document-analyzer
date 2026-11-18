# Changelog

All notable changes to this project are documented here.
Format inspired by [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The user interface
is in Italian: its labels are quoted as they appear (e.g. *Verifiche*), with a translation.

## [Unreleased]

### Changed
- **Simpler interface**: long explanations are now on demand (one visible line, the rest behind a
  "?", remembered per screen); the catalog card is split into tabs (Card, Pages and collections,
  Analysis and guide); the results page keeps only downloads and per-PDF CSVs, with anomalies in a
  collapsible section; no more "Next" buttons besides the next-step banner; a **New project**
  button on the projects page; clearer labels (library *Analisi* column, pages to index, project
  table summary, one-line descriptions in the verification table).

## [0.5.0] — 2026-11-16

### Added
- **⑤ Verification and processing** (*Verifiche*), a new project step (Results becomes ⑥):
  after indexing, the project opens here. For all PDFs or for the selected ones:
  - *page coverage*: every page sent has at least one row, or exactly one; failed or
    unprocessed pages;
  - *content on the page*: on every row, the values of the chosen columns are searched in the
    native text of the page the row comes from, and on which other page they are if missing;
  - *reference list*: Gemini transcribes the catalog's index (or table of contents, price
    list…), one request per PDF, and the program compares it with the CSV: missing entries,
    entries only in the CSV, pages that don't match; the list can be corrected by hand;
  - *suspicious characters*, *empty values*, *duplicates* (also across PDFs).
  Checks that don't need Gemini give their result immediately; findings can be marked as
  accepted ("va bene così").
- **Reversible corrections**, applied every time the CSV and the search page are generated,
  without touching what Gemini read: *replace all* (in one column or all, in one PDF or all),
  hand-edited cells, deleted rows. The CSV rows can be browsed, searched and edited directly in
  step ⑤.
- **Redo single pages** from step ⑤, optionally one page per request when the project sends
  pages together.
- **Key columns** in the project table (*Chiave* checkbox): they identify a row for the checks
  and don't change the extraction.
- `rag describe --pages`: describes only some pages.
- **Interface themes**: the styling is built on CSS variables (scales in `css/tokens.css`,
  colors in the themes `css/themes/light.css` and `dark.css`); the theme is chosen with
  `ui.theme` (`auto`, `light`, `dark` or a new theme, i.e. a file that redefines only the colors
  that change). The *Stile* page (`#/stile`) shows variables and components. The exported search
  page and the game use the same theme.

### Changed
- **New name: Document Analyzer.** Package and command are called `docanalyzer` (formerly
  `ragpdf`), environment variables `DOCANALYZER_*` (formerly `RAGPDF_*`). The `data/` folder
  doesn't change and pages already indexed remain valid.
- The **RAG mode uses the catalog's indexing guide**, the same as the indexer, instead of the
  primer: removed the `primer` commands, the `data/primers/` folder and the primer generation
  prompt. Rule fingerprints don't change: pages already indexed remain valid.
- Neutral examples in documentation, interface and tests (no references to real catalogs).
- README in English, with screenshots of demo catalogs; changelog in English.
- The game shown while waiting is hidden until it is opened.

### Fixed
- Dark theme: checkboxes, menus and scrollbars are now dark too.
- Search page: highlights every searched word, not only the first one.
- Reference list with several key columns (e.g. engine + code): the comparison uses only the
  columns the list reports (an index of engines has no codes).

## [0.4.0] — 2026-11-15

### Added
- **Send mode** for pages sent to Gemini, chosen per project in steps ③ Trial and ④ Indexing:
  *one page per request* (as before) or **all the pages of a PDF together**, sent as a subset
  cropped from the original PDF in one request per PDF (PDFs are never mixed). Far fewer
  requests, useful with the daily request limit of the free tier. If the response is too long,
  or the request too large, the pages are split automatically into more requests for the same
  PDF; an optional maximum number of pages per request. The indexing plan shows the requests per
  PDF and the estimated size of the largest one. The mode doesn't change the rules: pages already
  done remain valid.
- **Start over** in step ④: for a single PDF (the others are untouched) or for all, with results
  deleted and the trial not reused.
- In step ④, the **reason** for the failed pages of each PDF.

### Changed
- *Start indexing* always retries failed pages: before, after 3 attempts a page was no longer
  retried even though the plan still counted it as to do (the command line keeps the
  `indexing.max_page_attempts` limit).

### Fixed
- Usage summary: "1 richiesta" instead of "1 richieste" (singular).

## [0.3.0] — 2026-11-15

A **single, direct pipeline** from PDF to CSV: library → catalog analysis → project created
from a catalog's card → ① Table → ② PDFs and pages → ③ Trial → ④ Indexing → ⑤ Results.

### Added
- **Catalog library**: folders (also uploading whole folders), free tags with filters and
  search, a card with description and **data it contains** (the inventory of indexable data),
  a page viewer with **page collections** (ranges with fixed tags: data, example page, cover,
  index, legend, ...) and *Open the PDF ↗* at the page shown. Bulk actions: move, tag, delete.
- **Catalog analysis with Gemini**, in two requests in a row: the **card** (description, tags,
  data it contains, collections, also deduced from the index) from the chosen pages, and then the
  **indexing guide** (how to read an isolated page of the catalog) with the same pages plus the
  *key pages* (index, legend, examples, first page of each data section). Editable instructions
  with a personal default, a fixed and strictly validated response format (malformed = *invalid*,
  archived and never used), a proposal to review and apply in part, a guide that can be corrected
  before applying it, an archive of analyses. If the guide fails, the card stays and the guide can
  be regenerated.
- **Indexing guide** in the card: editable by hand and **regenerable from the current card**
  (only the second request). It accompanies every page of the catalog in projects.
- **Project from a catalog's card**: write the **table** by hand (name, description, what a row
  represents, columns with description and **page header value**, other instructions). Then
  create the project with that catalog only, or let Gemini search **all analyzed catalogs** for
  similar ones (compatible or partial, with covered columns and data sections), without rewriting
  the table; the project is created from the report with the pages of the chosen sections and the
  guides copied.
- **③ Trial**: extraction with the real rules on a few pages to index per catalog (4 by default,
  adjustable, example pages first, *Other pages* for pages not tried yet, choice of PDFs), with
  rows, Gemini's notes, checks and a trial CSV. If the rules change the trial is outdated;
  otherwise the pages tried already count as indexed.
- In the PDF card, **In projects**: pages to index, guide, indexing status in each project and
  the CSV of that PDF.

### Changed
- **A project is a path in 5 steps** (① Table, ② PDFs and pages, ③ Trial, ④ Indexing,
  ⑤ Results) with the state of each step and the **next step** always in view, also on the home
  page; opening a project lands on the next step.
- **Rules composed by the program**: extraction rules come from the project table, the catalog's
  guide and the PDF's notes; the user no longer sees primers or YAML specifications. Changing the
  table makes all PDFs to redo, the guide and notes only their own PDF.
- Pages to index and guide are **copies** from the library: if they change there, the project
  reports it and *Update from library* copies them again.
- PDFs belong to the library: removing a PDF from a project or deleting a project doesn't delete
  the PDF or its results. `ragpdf remove` refuses a PDF used by a project.
- **No preventive limits** on pages, sizes, number of catalogs or length of instructions: the
  confirmations say how many requests will be sent, how heavy and how long they are; if Gemini
  refuses, the error is shown.
- The page prompt also receives the table description (*what the index is for*).
- **Reduced command line**: `ui`, `doctor`, `add` (into the library, `--folder`), `list`,
  `remove`, `project list/index/export/search`, `primer` and `rag` (RAG mode unchanged).

### Removed
- The **guided setup** (`ragpdf setup` and the *Rules* step): primer and specification written by
  Gemini in versions, with corrections in plain words.
- Project primer and specification, YAML specifications in the workspace and example templates;
  commands `spec`, `index`, `export`, `compare` and `project new/add/remove-doc/note`.
- The **example / reference CSV** (in the rules, in the guided project, in the comparison).
- Creating projects from the home page (uploading PDFs) and from the library selection: a project
  is created only from a catalog's card.
- Projects created with earlier development versions have no table: they must be deleted and
  created again.

### Fixed
- Catalog card: typing the range of a new collection no longer rewrites the *from* and *to*
  fields while typing.
- Gemini Snake: while the game is visible, arrows, WASD and space belong to the game only (before,
  the arrows also turned the pages of the viewer).
- The `hidden` attribute always hides interface elements.

## [0.2.0] — 2026-11-12

### Added
- **Gemini Snake**: a mini game while waiting for Gemini jobs in the interface, with the real
  progress, automatic restart when you lose and a final animation leading to the results (at the
  end of indexing, and at the end of any other job if you are playing: moving to the next page
  waits for the end of the animation). It can be hidden (choice remembered).
- The browser always revalidates the interface files (`Cache-Control: no-cache`), so after an
  update it doesn't mix old pages and new scripts.
- **Indexing projects**: several PDFs with the same structure, common primer and specification,
  notes and pages per PDF (also proposed by Gemini), guided setup with pages from several PDFs and
  a trial on each, a **single CSV** with the file column and a CSV per PDF. Commands
  `ragpdf project ...`; interface organized by projects. Existing catalogs automatically became
  single-PDF projects.
- Standalone HTML **search page** generated from the single CSV (`ricerca.html`).
- **Graphical interface** (`ragpdf ui`): local server and web page with guided setup (clickable
  thumbnails, prompt visible before sending, confirmations, drafts, versions), indexing with
  progress and cancellation, results and downloads.
- Overall rate adapted to Gemini quotas and the `gemini.max_requests_per_minute_total` option.
- **Guided setup** (`ragpdf setup`): Gemini looks at the pages chosen by the user (PDF subset,
  page mapping in the prompt), proposes primer and specification, tries the extraction on some
  pages and corrects them based on observations written in plain words. Saved versions, `/back`,
  resume, manual edits, comparison with a reference CSV, starting from existing primer and
  specification.
- Primer from chosen pages: `ragpdf primer generate <doc> --pages 1,4,10-14`.
- Per-page input mode (`indexing.input`): image + native text (default), image only, single-page
  PDF. Option `gemini.media_resolution`.
- Default specification per document: `index`/`export --all` with different catalogs, merged
  into `TUTTI.csv` when the columns match.
- Warning for scanned PDFs (without text).
- Usage summary (requests and tokens) at the end of indexing and of the guided session.
- Option `gemini.thinking_level` to tune the model's "thinking".
- `ragpdf list` also shows the default specification of each document.
- **Indexing mode**: from a PDF to a CSV according to a YAML *specification* written by the user
  (what a row represents, columns, free instructions, conversion tables, example CSV). Structured
  page-by-page extraction with JSON Schema, inherited page context, normalization, duplicates,
  sorting, anomalies report, merging of several documents (`TUTTI.csv`).
- **Automatic primer draft** from the whole PDF (`ragpdf primer generate`).
- **Automatic specification draft** from a description in plain words, with an example CSV and
  sample pages (`ragpdf spec draft`).
- Comparison with a reference CSV (`ragpdf compare`): coverage, precision and row-by-row
  differences.
- `ragpdf` command with a guided CLI: `doctor`, `add`, `list`, `remove`, `primer`, `spec`,
  `index`, `export`, `rag`.
- Data workspace (`data/`) separate from the application, with a document registry (readable id
  and SHA-256 fingerprint to recognize duplicates).
- Gemini client with a key pool, per-key rate shared between threads, error handling by HTTP
  code, orderly stop when quotas run out.
- Simulated Gemini client (`RAGPDF_FAKE_GEMINI=1`) and 136 automated tests without network.
- Example specifications (`examples/specs/`) and a step-by-step guide
  (`docs/GUIDA_INDICIZZAZIONE.md`), architecture document (`docs/ARCHITETTURA.md`).
- `pyproject.toml`, roadmap, changelog.

### Changed
- Gemini overload (503 "high demand"): new attempts at a fixed interval
  (`gemini.retry_delay_seconds`) instead of doubling, without failing pages; beyond
  `gemini.max_wait_minutes` the job stops in an orderly way.
- Interface: service messages (overload, quotas, slowdowns) appear under the progress bar;
  *Stop* also immediately interrupts ongoing waits.
- Quota errors recognized from the response details (per minute / per day, suggested wait): they
  no longer fail pages.
- All PDF operations go through a single lock (thread safety).
- Preview pages are reused in indexing if the rules don't change.
- Context columns are no longer repeated in every row of Gemini's response; a more compact
  extraction prompt with an explicit rule on row completeness.
- Setting up a catalog from an existing primer and specification updates the same files instead
  of creating copies; the overwrite confirmation appears only if they change.
- Truncated or blocked Gemini responses: immediate, explained error, without retries.
- Code gathered in the `src/ragpdf` package (before: `common`, `ingestion`, `rag` packages).
- RAG mode split into rerunnable phases (`rag describe`, `rag build`, `rag ask`), with `upsert`
  in the index: regenerated pages update it.
- Prompts moved to `configs/prompts/` and made generic.
- Configuration cleaned up and validated; unused options removed.
- ChromaDB becomes optional: `pip install -e ".[rag]"`.
- README rewritten; `.gitignore` reorganized and `docs/` versioned.

### Removed
- `main.py` (replaced by the `ragpdf` command), `requirements.txt` (UTF-16, missing dependencies),
  abstract interfaces not aligned with the implementations.
- Generated files tracked by mistake: Python bytecode and ChromaDB database.

## [0.1.0] — 2026-10-06

### Added
- Mode 1, standard vision-first RAG: PDF → PNG rendering, page descriptions with Gemini Vision
  guided by a primer, manifest to resume interrupted work, indexing in ChromaDB, queries with
  source citations.
- Automatic rotation of several Gemini API keys and parallel processing.
- CLI with the `ingest`, `query`, `list` commands.
