/* La Tabella del progetto: cosa il progetto deve produrre, decisa dall'utente.
 *
 * - columnsEditor: editor delle colonne (nome, descrizione, dato di intestazione, chiave, ordine), usato
 *   sia nella creazione del progetto (guided.js) sia nel passo ① Tabella;
 * - renderSettings: schermata #/p/<id>/settings (① Tabella), sempre modificabile. Accanto alle
 *   colonne la copertura nei PDF del progetto, ricavata dai loro "dati presenti" nella
 *   biblioteca (letti in diretta: sono descrittivi).
 *
 * Usa le utilità di app.js e library.js; viene caricato prima, le funzioni si chiamano dopo l'avvio.
 */
"use strict";

const normName = s => String(s || "").trim().replace(/\s+/g, " ").toLowerCase();

const HEADER_HELP = "Dato di intestazione: un valore che di solito compare una volta sola nella pagina o nella " +
  "sezione (es. il modello del motore nel titolo) e vale per tutte le righe; se una pagina non lo ripete, " +
  "viene preso dalla pagina precedente.";

const KEY_HELP = "Colonna chiave: identifica la riga (es. il modello del motore). Serve alle verifiche del " +
  "passo ⑤ (elenco di riferimento, doppioni, valori vuoti, contenuto sulla pagina); se le chiavi sono più di una, " +
  "conta la loro combinazione. Non cambia l'estrazione: si può segnare anche dopo l'indicizzazione.";

// Le colonne che il programma aggiunge a ogni riga (core/projects.py AUTO_COLUMNS): Gemini non le compila
// e non conosce il nome del file.
const AUTO_COLUMNS = [["PAGINA_PDF", "numero di pagina nel PDF"], ["FILE_ORIGINE", "nome del file PDF, così com'è"]];

/** Avviso per una colonna che chiede ciò che il programma aggiunge già (nome del file, pagina del PDF). */
function autoColumnWarning(c) {
  const name = normName(c.name).replace(/[\s_.-]+/g, " "), text = `${name} ${normName(c.description)}`;
  if (AUTO_COLUMNS.some(([n]) => normName(n).replace(/_/g, " ") === name)) {
    return "Questo nome è riservato: la colonna la aggiunge già il programma.";
  }
  if (/^(pdf|file|nome file|filename|file name|nome pdf|catalogo|nome catalogo|documento)$/.test(name) ||
      /(nome|name) (del |dello |di )?(file|pdf|catalogo|documento)/.test(text)) {
    return "Gemini non riceve il nome del file, quindi questa colonna resterebbe vuota: il nome esatto del PDF " +
      "lo aggiunge già il programma (FILE_ORIGINE).";
  }
  if (/^(pagina|pag|page|n pagina|numero pagina|pagina pdf)$/.test(name)) {
    return "Il numero di pagina del PDF lo aggiunge già il programma (PAGINA_PDF): tieni questa colonna solo se " +
      "vuoi il numero stampato sulla pagina, e scrivilo nella descrizione.";
  }
  return "";
}

/** Editor di colonne. onChange viene chiamato a ogni modifica; badge(col) aggiunge un'etichetta. */
function columnsEditor(container, columns, { onChange = () => {}, badge = () => "", readonly = false } = {}) {
  const draw = () => {
    container.innerHTML = (columns.length ? `<div class="col-head small muted"><span>Nome</span><span>Descrizione</span>
        <span title="${esc(HEADER_HELP)}">Intestazione ⓘ</span><span title="${esc(KEY_HELP)}">Chiave ⓘ</span></div>`
      + columns.map((c, i) => `
      <div class="col-row">
        <input type="text" data-gcname="${i}" value="${esc(c.name)}" placeholder="nome (es. CODICE_RICAMBIO)" ${readonly ? "disabled" : ""}>
        <input type="text" data-gcdesc="${i}" value="${esc(c.description || "")}" placeholder="descrizione (cosa contiene, formato)" ${readonly ? "disabled" : ""}>
        <label class="col-header" title="${esc(HEADER_HELP)}"><input type="checkbox" data-gchead="${i}" ${c.header ? "checked" : ""} ${readonly ? "disabled" : ""}></label>
        <label class="col-header" title="${esc(KEY_HELP)}"><input type="checkbox" data-gckey="${i}" ${c.key ? "checked" : ""} ${readonly ? "disabled" : ""}></label>
        <span data-gcbadge="${i}">${badge(c)}</span>
        <button class="secondary small" data-gcup="${i}" type="button" title="Sposta su" ${i && !readonly ? "" : "disabled"}>&uarr;</button>
        <button class="secondary small" data-gcdel="${i}" type="button" title="Togli" ${readonly ? "disabled" : ""}>&times;</button></div>
      <p class="note warn small col-warn" data-gcwarn="${i}" ${autoColumnWarning(c) ? "" : "hidden"}>${esc(autoColumnWarning(c))}</p>`).join("")
      : `<p class="muted small">Nessuna colonna tua: aggiungine almeno una.</p>`)
      + `<p class="small muted col-auto-title">Aggiunte dal programma a ogni riga, sempre (Gemini non le compila: non
          conosce il nome del file):</p>`
      + AUTO_COLUMNS.map(([name, desc]) => `
      <div class="col-row col-auto" title="La aggiunge il programma a ogni riga: non serve chiederla a Gemini">
        <input type="text" value="${esc(name)}" disabled><input type="text" value="${esc(desc)}" disabled>
        <span></span><span></span><span></span><span></span><span></span></div>`).join("");
    // mentre scrivi si aggiornano solo avviso e copertura della riga: i campi non vengono ridisegnati,
    // così passare dal nome alla descrizione non perde il clic né il testo
    const refreshRow = i => {
      const c = columns[i], warning = autoColumnWarning(c), warn = $(`[data-gcwarn="${i}"]`, container);
      warn.textContent = warning;
      warn.hidden = !warning;
      $(`[data-gcbadge="${i}"]`, container).innerHTML = badge(c);
    };
    $$("[data-gcname]", container).forEach(el => el.addEventListener("input", () => {
      columns[+el.dataset.gcname].name = el.value; refreshRow(+el.dataset.gcname); onChange();
    }));
    $$("[data-gcdesc]", container).forEach(el => el.addEventListener("input", () => {
      columns[+el.dataset.gcdesc].description = el.value; refreshRow(+el.dataset.gcdesc); onChange();
    }));
    $$("[data-gchead]", container).forEach(el => el.addEventListener("change", () => {
      columns[+el.dataset.gchead].header = el.checked; onChange();
    }));
    $$("[data-gckey]", container).forEach(el => el.addEventListener("change", () => {
      columns[+el.dataset.gckey].key = el.checked; onChange();
    }));
    $$("[data-gcup]", container).forEach(b => b.addEventListener("click", () => {
      const i = +b.dataset.gcup; [columns[i - 1], columns[i]] = [columns[i], columns[i - 1]]; draw(); onChange();
    }));
    $$("[data-gcdel]", container).forEach(b => b.addEventListener("click", () => {
      columns.splice(+b.dataset.gcdel, 1); draw(); onChange();
    }));
  };
  draw();
  return {
    add(name = "", description = "") {
      if (name && columns.some(c => normName(c.name) === normName(name))) { toast("Questa colonna c'è già."); return; }
      columns.push({ name, description, header: false, key: false }); draw(); onChange();
      if (!name) $(`[data-gcname="${columns.length - 1}"]`, container).focus();
    },
    redraw: draw,
    get: () => columns.filter(c => c.name.trim())
      .map(c => ({ name: c.name.trim(), description: (c.description || "").trim(), header: !!c.header, key: !!c.key })),
  };
}

/** Controllo prima di salvare o inviare una tabella: messaggio d'errore, oppure "". */
function tableProblem(row, columns) {
  if (!row.trim()) return "Scrivi cosa rappresenta una riga.";
  if (!columns.length) return "Aggiungi almeno una colonna.";
  const names = columns.map(c => normName(c.name));
  const dupe = names.find((n, i) => names.indexOf(n) !== i);
  return dupe ? `La colonna "${dupe}" compare due volte.` : "";
}

// ------------------------------------------------------------------ ① Tabella
async function renderSettings(ctx) {
  const { project, pid, box } = ctx;
  const docs = project.documents;
  const index = new Map();               // dato (normalizzato) -> { name, docs: Set }
  docs.forEach(d => (d.library ? d.library.data : []).forEach(name => {
    const k = normName(name);
    if (!index.has(k)) index.set(k, { name, docs: new Set() });
    index.get(k).docs.add(d.id);
  }));
  const withoutData = docs.filter(d => !d.library || !d.library.data.length);
  const columns = project.fields.map(f => ({ name: f.name, description: f.description || "", header: !!f.header,
                                              key: !!f.key }));
  const indexed = project.progress && (project.progress.done || project.progress.stale.length);

  box.innerHTML = `
    <div class="grid2 wide-left">
      <div class="panel">
        <h3>La tabella del progetto</h3>
        <p class="hint">Cosa vuoi ottenere: è la stessa per tutti i PDF del progetto e, insieme alla guida di ogni
          catalogo e alle note dei singoli PDF, forma le regole che Gemini segue pagina per pagina.
          ${indexed ? "<strong>Cambiarla rende da rifare le pagine già indicizzate</strong> (e la prova)." : ""}</p>
        <label for="s-name">Nome del progetto</label>
        <input type="text" id="s-name">
        <label for="s-desc">Descrizione <span class="muted small">(facoltativa: a cosa serve l'indice)</span></label>
        <textarea id="s-desc" rows="2" placeholder="es. trovare un ricambio partendo dal motore"></textarea>
        <label for="s-row">Cosa rappresenta una riga</label>
        <input type="text" id="s-row" placeholder="es. una riga per ogni codice ricambio di ogni motore">
        <label>Colonne <span class="muted small">(nell'ordine del CSV; in fondo le due che aggiunge sempre il programma)</span></label>
        <div id="s-cols"></div>
        <div class="row mt-s"><button class="secondary small" id="s-add" type="button">+ Aggiungi colonna</button></div>
        <label for="s-instr">Altre indicazioni <span class="muted small">(facoltative, valgono per tutti i PDF)</span></label>
        <textarea id="s-instr" rows="3" placeholder="es. se manca il codice OEM lascia vuoto; codici senza spazi"></textarea>
        <div class="row mt-m"><span class="spacer"></span><button id="s-save" type="button">Salva la tabella</button></div>
      </div>
      <div class="panel">
        <h3>Dati presenti nei PDF</h3>
        <p class="hint">Dalle schede della biblioteca. Clic su un dato per aggiungerlo come colonna; il numero dice in
          quanti PDF del progetto compare (il confronto è per nome).</p>
        ${index.size ? `<div class="chips">${[...index.values()].sort((a, b) => b.docs.size - a.docs.size || a.name.localeCompare(b.name))
          .map(x => `<button type="button" class="chip" data-addcol="${esc(x.name)}" title="${esc(docs.filter(d => x.docs.has(d.id)).map(d => d.title).join(", "))}">
            + ${esc(x.name)} <span class="small">${x.docs.size}/${docs.length}</span></button>`).join("")}</div>`
          : `<p class="muted small">Nessun dato presente nelle schede dei PDF.</p>`}
        ${withoutData.length ? `<p class="hint">Senza dati presenti: ${withoutData.map(d =>
          `<a href="#/biblioteca/c/${enc(d.id)}">${esc(d.title)}</a>`).join(", ")}. Puoi elencarli nella loro scheda,
          anche con l'analisi di Gemini.</p>` : ""}
      </div>
    </div>`;

  $("#s-name").value = project.name;
  $("#s-row").value = project.row || "";
  const desc = $("#s-desc"), instr = $("#s-instr");
  desc.value = project.description || ""; desc.dataset.original = desc.value;
  instr.value = project.instructions || ""; instr.dataset.original = instr.value;

  const coverage = name => { const x = index.get(normName(name)); return x ? x.docs.size : 0; };
  const badge = c => {
    if (!c.name.trim()) return "";
    const n = coverage(c.name);
    return n === docs.length ? `<span class="badge ok" title="Presente in tutti i PDF">${n}/${docs.length}</span>`
      : n ? `<span class="badge warn" title="Presente solo in alcuni PDF: negli altri resterà vuota (o va spiegata nelle note)">${n}/${docs.length}</span>`
      : `<span class="badge" title="Nessun PDF lo elenca tra i dati presenti (forse con un altro nome)">0/${docs.length}</span>`;
  };
  const editor = columnsEditor($("#s-cols"), columns, { badge });
  $("#s-add").addEventListener("click", () => editor.add());
  $$("[data-addcol]").forEach(b => b.addEventListener("click", () => editor.add(b.dataset.addcol)));
  $("#s-save").addEventListener("click", async e => {
    const cols = editor.get();
    const problem = tableProblem($("#s-row").value, cols);
    if (problem) { toast(problem); return; }
    if (indexed) {
      const ok = await confirmDialog({ title: "Salvare la tabella?", ok: "Salva", html: `
        <p>Il progetto ha già pagine indicizzate: se cambiano riga, colonne, descrizione o altre indicazioni,
          andranno rifatte (al passo ④ te lo chiederà). Cambiare solo il nome o le colonne chiave non rifà nulla.</p>` });
      if (!ok) return;
    }
    await busy(e.target, async () => {
      await api("PUT", `/api/projects/${enc(pid)}/settings`, {
        name: $("#s-name").value, description: desc.value, row: $("#s-row").value, instructions: instr.value,
        columns: cols,
      });
      desc.dataset.original = desc.value; instr.dataset.original = instr.value;
      toast("Tabella salvata.");
      ctx.refresh();
    });
  });
}
