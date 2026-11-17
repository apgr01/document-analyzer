"""Lo stile resta parametrizzato: colori solo nei temi, niente stili fissi nel JS, variabili definite."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docanalyzer.app import App
from docanalyzer.web import theme
from docanalyzer.web.jobs import JobManager
from docanalyzer.web.server import create_app

STATIC = theme.STATIC_DIR
CSS = theme.CSS_DIR
SEARCH_PAGE = Path(theme.__file__).parent.parent / "indexing" / "search_page.py"
# un colore scritto a mano: #abc, #aabbcc, #aabbccdd, rgb()/rgba()/hsl()
COLOR = re.compile(r"(?<![\w&])#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b(?![-\w])|\b(?:rgba?|hsla?)\(")


def defined_variables(*paths: Path) -> set[str]:
    return {m for p in paths for m in re.findall(r"(--[\w-]+)\s*:", p.read_text(encoding="utf-8"))}


def used_variables(text: str) -> set[str]:
    return set(re.findall(r"var\((--[\w-]+)", text))


def ui_sources() -> dict[str, str]:
    files = [*STATIC.glob("*.js"), STATIC / "index.html", CSS / "tokens.css", CSS / "app.css", CSS / "game.css"]
    return {p.name: p.read_text(encoding="utf-8") for p in files}


def test_colors_only_in_themes():
    sources = ui_sources()
    sources["search_page.py"] = SEARCH_PAGE.read_text(encoding="utf-8")
    found = {name: COLOR.findall(text) for name, text in sources.items()}
    assert {k: v for k, v in found.items() if v} == {}


def test_no_fixed_inline_styles_in_js():
    for path in STATIC.glob("*.js"):
        styles = re.findall(r'style="([^"]*)"', path.read_text(encoding="utf-8"))
        fixed = [s for s in styles if "${" not in s]              # solo valori calcolati (es. larghezza di una barra)
        assert fixed == [], (path.name, fixed)


def test_variables_are_defined():
    defined = defined_variables(CSS / "tokens.css", CSS / "themes" / "light.css", CSS / "app.css")
    for name, text in ui_sources().items():
        assert used_variables(text) - defined == set(), name
    assert used_variables(SEARCH_PAGE.read_text(encoding="utf-8")) - defined == set()
    # il gioco legge --game-<nome> dal tema
    snake = (STATIC / "snake.js").read_text(encoding="utf-8")
    game = {f"--game-{n}" for n in re.findall(r'v\("([\w-]+)"\)', snake)} | {f"--game-snake-{i}" for i in range(1, 7)}
    assert game - defined == set()
    # la pagina Stile mostra solo variabili esistenti
    guide = (STATIC / "stile.js").read_text(encoding="utf-8")
    assert set(re.findall(r'"(--[\w-]+)"', guide)) - defined == set()


def test_themes_override_only_known_variables():
    base = defined_variables(CSS / "themes" / "light.css")
    for path in (CSS / "themes").glob("*.css"):
        assert defined_variables(path) - base == set(), path.name
    assert {"light", "dark"} <= set(theme.available_themes())


def test_theme_layers():
    assert theme.theme_layers("auto")[-1] == ("themes/dark.css", theme.DARK_MEDIA)
    assert theme.theme_layers("dark")[-1] == ("themes/dark.css", None)
    assert [p for p, _ in theme.theme_layers("light")] == ["tokens.css", "themes/light.css"]
    with pytest.raises(ValueError, match="inesistente"):
        theme.theme_layers("neon")
    css = theme.inline_theme_css("auto")
    assert "--space-s" in css and "--color-bg" in css and "@media (prefers-color-scheme: dark)" in css


def test_configured_theme_reaches_the_page(config):
    config.ui.theme = "dark"
    client = TestClient(create_app(App(config), JobManager(run_inline=True)))
    page = client.get("/").text
    assert '<link rel="stylesheet" href="/static/css/themes/dark.css">' in page and "{{" not in page
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/api/theme").json() == {"theme": "dark", "available": theme.available_themes()}
    config.ui.theme = "neon"
    with pytest.raises(ValueError, match="neon"):
        create_app(App(config))
