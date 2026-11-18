/* Componenti comuni dell'interfaccia: piccoli costruttori di HTML usati da tutte le schermate.
 *
 * - helpBlock(key, summary, details): una riga di spiegazione sempre visibile; il resto si apre
 *   con il "?" e la scelta (aperto/chiuso) resta ricordata nel browser per quella chiave.
 *
 * Lo stile è in css/app.css (sezione "aiuto"). Viene caricato prima degli altri script.
 */
"use strict";

const HELP_STORE = "docanalyzer:help-open";

function helpOpenKeys() {
  try { return new Set(JSON.parse(localStorage.getItem(HELP_STORE) || "[]")); } catch { return new Set(); }
}

/** Spiegazione a richiesta. ``summary`` e ``details`` sono HTML scritto dal programma (non dati). */
function helpBlock(key, summary, details) {
  const open = helpOpenKeys().has(key) ? " open" : "";
  return `<details class="help" data-help="${key}"${open}><summary>${summary}</summary>
    <div class="help-body">${details}</div></details>`;
}

// ricorda quali spiegazioni sono aperte (l'evento toggle non risale: si ascolta in cattura)
document.addEventListener("toggle", e => {
  const el = e.target;
  if (!(el instanceof HTMLDetailsElement) || !el.classList.contains("help")) return;
  const keys = helpOpenKeys();
  if (el.open) keys.add(el.dataset.help); else keys.delete(el.dataset.help);
  try { localStorage.setItem(HELP_STORE, JSON.stringify([...keys])); } catch { /* ignorato */ }
}, true);
