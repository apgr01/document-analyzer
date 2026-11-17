"""Temi dell'interfaccia.

Lo stile è diviso in livelli (vedi ``static/css/``):

- ``tokens.css``       scale (spazi, testo, raggi, durate) e misure dei componenti;
- ``themes/light.css`` il tema di base: definisce **tutti** i colori, come variabili;
- ``themes/<nome>.css`` gli altri temi, che ridefiniscono solo le variabili che cambiano;
- ``app.css``, ``game.css`` i componenti, che usano solo le variabili.

Il tema si sceglie in configurazione (``ui.theme``): ``auto`` (chiaro o scuro secondo il
sistema), ``light``, ``dark`` o il nome di un file in ``themes/``. Le stesse regole valgono per
l'interfaccia (fogli collegati) e per le pagine autonome come la pagina di ricerca (CSS incorporato).
"""

from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"
CSS_DIR = STATIC_DIR / "css"
THEMES_DIR = CSS_DIR / "themes"
BASE_THEME = "light"
DARK_THEME = "dark"
AUTO = "auto"
DARK_MEDIA = "(prefers-color-scheme: dark)"


def available_themes() -> list[str]:
    return sorted(p.stem for p in THEMES_DIR.glob("*.css"))


def check_theme(theme: str) -> str:
    """Il nome del tema, se esiste; altrimenti un errore che elenca quelli disponibili."""
    if theme != AUTO and theme not in available_themes():
        raise ValueError(f"Tema '{theme}' inesistente: scegli auto oppure uno tra {', '.join(available_themes())} "
                         f"(file in {THEMES_DIR}).")
    return theme


def theme_layers(theme: str) -> list[tuple[str, str | None]]:
    """I fogli del tema, in ordine: (percorso relativo a ``css/``, media query o ``None``)."""
    check_theme(theme)
    layers: list[tuple[str, str | None]] = [("tokens.css", None), (f"themes/{BASE_THEME}.css", None)]
    if theme == AUTO:
        layers.append((f"themes/{DARK_THEME}.css", DARK_MEDIA))
    elif theme != BASE_THEME:
        layers.append((f"themes/{theme}.css", None))
    return layers


def stylesheet_links(theme: str, components: tuple[str, ...] = ("app.css", "game.css")) -> str:
    """I ``<link>`` per l'interfaccia: tema e componenti."""
    lines = []
    for path, media in [*theme_layers(theme), *[(c, None) for c in components]]:
        media_attr = f' media="{media}"' if media else ""
        lines.append(f'<link rel="stylesheet" href="/static/css/{path}"{media_attr}>')
    return "\n  ".join(lines)


def inline_theme_css(theme: str) -> str:
    """Il CSS del tema da incorporare in una pagina autonoma (variabili: scale e colori)."""
    parts = []
    for path, media in theme_layers(theme):
        css = (CSS_DIR / path).read_text(encoding="utf-8")
        parts.append(f"@media {media} {{\n{css}\n}}" if media else css)
    return "\n".join(parts)
