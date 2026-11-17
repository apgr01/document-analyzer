/* Pagina Stile (#/stile): le variabili del tema e i componenti dell'interfaccia, per chi vuole
 * creare un tema o controllare che un tema funzioni. Tutto quello che si vede usa le classi e le
 * variabili vere (css/tokens.css, css/themes/, css/app.css): cambiando tema cambia anche qui.
 *
 * Usa le utilità di app.js; viene caricato prima, le funzioni si chiamano dopo l'avvio.
 */
"use strict";

const STYLE_COLORS = [
  ["Superfici e testo", ["--color-bg", "--color-surface", "--color-text", "--color-text-muted", "--color-border",
                         "--color-paper", "--color-backdrop"]],
  ["Accento", ["--color-accent", "--color-accent-soft", "--color-on-accent"]],
  ["Stati", ["--color-success", "--color-success-soft", "--color-success-strong", "--color-success-border",
             "--color-warning", "--color-warning-soft", "--color-danger", "--color-danger-soft", "--color-highlight"]],
  ["Gemini", ["--color-gemini"]],
  ["Collezioni di pagine", ["dati", "esempio", "copertina", "indice", "introduzione", "legenda", "tabelle-tecniche",
                            "disegni", "avvertenze", "vuota", "altro", "default"].map(t => `--color-tag-${t}`)],
  ["Gioco durante l'attesa", ["bg", "bg-top", "bg-bottom", "track", "text", "text-muted", "text-faint", "light",
                              "snake-1", "snake-2", "snake-3", "snake-4", "snake-5", "snake-6", "spark", "hit"]
                              .map(t => `--game-${t}`)],
];
const STYLE_SPACES = ["--space-3xs", "--space-2xs", "--space-xs", "--space-s", "--space-m", "--space-l", "--space-xl",
                      "--space-2xl", "--gutter"];
const STYLE_TEXTS = ["--text-2xs", "--text-xs", "--text-sm", "--text-base", "--text-md", "--text-lg", "--text-xl"];
const STYLE_RADII = ["--radius-xs", "--radius-sm", "--radius-md", "--radius-lg", "--radius-pill"];

async function renderStyleGuide() {
  const theme = await api("GET", "/api/theme");
  const css = getComputedStyle(document.documentElement);
  const value = name => css.getPropertyValue(name).trim();
  const swatch = name => `<div class="swatch"><i style="--c: var(${name})"></i>
    <span><code>${esc(name)}</code><span class="muted">${esc(value(name))}</span></span></div>`;

  view.innerHTML = `
    <p class="small"><a href="#/">&larr; Progetti</a></p>
    <h1>Stile dell'interfaccia</h1>
    <p class="muted">Tema in uso: <strong>${esc(theme.theme)}</strong> · temi disponibili: ${theme.available.map(esc).join(", ")}.</p>
    <div class="note">Un <strong>tema</strong> è un file CSS in <code>web/static/css/themes/</code> che ridefinisce le
      variabili qui sotto; si sceglie in <code>configs/default.yaml</code> (<code>ui.theme</code>). Il tema chiaro
      (<code>light.css</code>) le definisce tutte; un tema nuovo ridefinisce solo quelle che cambiano (come
      <code>dark.css</code>). Scale e misure dei componenti stanno in <code>tokens.css</code>.</div>

    <div class="panel"><h3>Colori</h3>
      ${STYLE_COLORS.map(([title, names]) => `<h4 class="subhead">${esc(title)}</h4>
        <div class="swatches">${names.map(swatch).join("")}</div>`).join("")}
    </div>

    <div class="grid2">
      <div class="panel"><h3>Spazi</h3>
        ${STYLE_SPACES.map(n => `<div class="row mb-s"><code class="input-short">${esc(n)}</code>
          <span class="space-bar" style="width: var(${n})"></span><span class="muted small">${esc(value(n))}</span></div>`).join("")}
      </div>
      <div class="panel"><h3>Testo e raggi</h3>
        ${STYLE_TEXTS.map(n => `<div style="font-size: var(${n})">${esc(n)} · ${esc(value(n))} — Cataloghi PDF in CSV</div>`).join("")}
        <div class="row mt-m">${STYLE_RADII.map(n => `<span class="swatch"><i style="--c: var(--color-accent-soft); border-radius: var(${n})"></i>
          <code>${esc(n)}</code></span>`).join("")}</div>
      </div>
    </div>

    <div class="panel"><h3>Componenti</h3>
      <h4 class="subhead">Pulsanti</h4>
      <div class="row">
        <button type="button">Principale</button>
        <button class="secondary" type="button">Secondario</button>
        <button class="gemini" type="button">Usa Gemini</button>
        <button class="danger" type="button">Elimina</button>
        <button type="button" disabled>Disattivato</button>
        <button class="secondary small" type="button">Piccolo</button>
        <a class="linkbtn secondary small" href="#/stile">Collegamento</a>
      </div>
      <h4 class="subhead">Badge, chip e collezioni</h4>
      <div class="row">
        <span class="badge">info</span><span class="badge ok">fatto</span><span class="badge warn">da rivedere</span>
        <span class="badge error">errore</span><span class="badge tag">tag</span>
        <span class="chip">filtro</span><span class="chip on">filtro attivo <span class="small">3</span></span>
        ${["dati", "esempio", "indice", "legenda", "disegni"].map(t => pageTagChip(t, t)).join("")}
      </div>
      <h4 class="subhead">Passi del progetto</h4>
      <div class="row">${[["①", "fatto"], ["②", "in corso"], ["③", "da rivedere"], ["④", "da fare"], ["⑤", "facoltativo"]]
        .map(([num, state]) => stepDot(num, { state }) + `<span class="small muted">${esc(state)}</span>`).join("")}</div>
      <h4 class="subhead">Avvisi</h4>
      <div class="note">Informazione: il prossimo passo è la prova.</div>
      <div class="note warn">Avviso: regole cambiate dopo l'indicizzazione.</div>
      <div class="note error">Errore: richiesta rifiutata da Gemini.</div>
      <div class="next-step row"><span><strong>Prossimo passo:</strong> Verifica i risultati</span><span class="spacer"></span>
        <a class="linkbtn small" href="#/stile">Vai &rarr;</a></div>
      <h4 class="subhead">Campi</h4>
      <div class="grid2">
        <div><label>Testo</label><input type="text" placeholder="es. una riga per ogni codice">
          <label>Menu</label><select><option>prima scelta</option></select></div>
        <div><label>Area di testo</label><textarea>Guida all'indicizzazione…</textarea>
          <label class="row check"><input type="checkbox" checked> casella con etichetta</label>
          <p class="hint">Suggerimento sotto un campo.</p></div>
      </div>
      <h4 class="subhead">Tabella, selezione e avanzamento</h4>
      <div class="selbar"><label class="small inline"><input type="checkbox"> tutte</label>
        <button class="secondary small" type="button">Va bene così</button><span class="small muted">2 scelte</span></div>
      ${table(["MOTORE", "CODICE", "PAGINA_PDF"], [{ MOTORE: "MX 450/S", CODICE: "RC001", PAGINA_PDF: 2 },
                                                  { MOTORE: "MX 100", CODICE: "RC002", PAGINA_PDF: 3 }])}
      <div class="progress mt-m"><div style="width: ${60}%"></div></div>
      <div class="proposal panel mt-m"><h4 class="mt-0">Proposta di Gemini</h4><blockquote>Testo proposto da rivedere.</blockquote></div>
    </div>`;
}
