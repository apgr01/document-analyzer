/* ⑤ Verifiche/Elaborazione (#/p/<id>/verify): controlli sui risultati dell'indicizzazione e correzioni.
 *
 * Una schermata simile a Risultati: in alto i PDF (tutti, oppure uno solo con un clic) e la tabella
 * verifiche × PDF; sotto le segnalazioni della verifica aperta con le azioni (va bene così, apri la
 * pagina, rifai le pagine, modifica, elimina la riga, sostituisci tutte); poi le impostazioni, le righe
 * del CSV (corrette, modificabili) e l'elenco delle correzioni, che si possono sempre togliere.
 * Le verifiche senza Gemini danno subito l'esito; solo l'elenco di riferimento va letto con Gemini.
 *
 * Usa le utilità di app.js; viene caricato prima, le funzioni si chiamano dopo l'avvio.
 */
"use strict";

const VERIFY_HELP = {
  copertura: "Ogni pagina inviata ha almeno una riga (o esattamente una, nelle impostazioni); pagine fallite o mai elaborate.",
  testo: "I valori delle colonne scelte si trovano nel testo della pagina da cui viene la riga (il testo del PDF, senza " +
    "Gemini, confrontato senza spazi né simboli). Se no, su quale altra pagina stanno.",
  riferimento: "Gemini trascrive un elenco che riporta tutte le voci (indice, sommario, listino…) e il programma lo " +
    "confronta con il CSV: voci mancanti, voci solo nel CSV, pagine che non tornano. Una richiesta per PDF.",
  caratteri: "Caratteri rotti (�, quadratini, caratteri privati) e simboli rari in una colonna: si sostituiscono tutti " +
    "insieme o uno per uno.",
  vuoti: "Righe con una colonna chiave o da cercare nel testo vuota.",
  doppioni: "La stessa chiave su più righe, nello stesso PDF o in PDF diversi: spesso è legittimo (lo stesso motore in " +
    "due cataloghi), quindi è una segnalazione, non un errore.",
};
const COVERAGE_TEXT = {
  almeno: ["Almeno una riga", "una pagina inviata senza righe è da controllare"],
  esattamente: ["Esattamente una riga", "per le tabelle con una scheda per pagina: anche più righe sono da controllare"],
  nessuno: ["Nessun controllo sulle righe", "solo pagine fallite o non elaborate"],
};
const ROWS_PER_PAGE = 50;
const verifyUI = {};      // per progetto: PDF scelti, verifica aperta, filtri delle righe (restano cambiando scheda)

const vPage = (doc, page, label = null) =>
  `<a href="#" data-act="page" data-doc="${esc(doc)}" data-page="${page}" title="Mostra la pagina">${label ?? `p. ${page}`}</a>`;
const vChar = ch => `<code class="vchar">${esc(ch)}</code> <span class="small muted">U+${ch.codePointAt(0).toString(16).toUpperCase().padStart(4, "0")}</span>`;

function verifyCell(cell) {
  if (cell.state === "non indicizzato") return `<span class="muted small">non indicizzato</span>`;
  if (cell.state === "non eseguita") return `<span class="muted small">da eseguire</span>`;
  const accepted = cell.accepted ? ` <span class="small muted" title="Segnalazioni marcate &quot;va bene così&quot;">+${cell.accepted} ok</span>` : "";
  if (cell.state === "ok") return `<span class="badge ok">✓ nessun problema</span>${accepted}`;
  if (cell.state === "superata") {
    return `<span class="badge warn" title="Risultati, correzioni o impostazioni cambiati dopo la verifica: rieseguila">da rieseguire</span>`;
  }
  return `<span class="badge error">${cell.problems} da vedere</span>${accepted}`;
}

/** Valori di una riga; ``mark``: colonne da evidenziare (es. quelle non trovate nella pagina). */
function vValues(values, columns, mark = []) {
  const parts = columns.filter(c => String(values[c] ?? "") !== "").map(c => {
    const v = esc(values[c]);
    return `<span class="small muted">${esc(c)}:</span> ${mark.includes(c) ? `<mark>${v}</mark>` : v}`;
  });
  return parts.join(" · ") || `<span class="muted small">(riga vuota)</span>`;
}

/** Somma dei riepiloghi di più PDF (i numeri si sommano). */
function vSum(summaries) {
  const out = {};
  Object.values(summaries).forEach(({ summary }) => Object.entries(summary || {}).forEach(([k, v]) => {
    if (typeof v === "number" && k !== "scarto") out[k] = (out[k] || 0) + v;
    else if (!(k in out)) out[k] = v;
  }));
  return out;
}

function vSummaryText(check, detail, titles) {
  const s = vSum(detail.summaries);
  const n = (k, one, many) => plural(s[k] || 0, one, many);
  if (check === "copertura") {
    return `${n("pagine", "pagina inviata", "pagine inviate")}, ${n("problemi", "da controllare", "da controllare")}.`;
  }
  if (check === "testo") {
    return `${n("righe", "riga", "righe")}: ${s.confermata || 0} confermate, ${s.parziale || 0} parziali, ` +
      `${s["altra pagina"] || 0} su un'altra pagina, ${s["non trovata"] || 0} non trovate` +
      `${s["non verificabile"] ? `, ${s["non verificabile"]} su pagine senza testo (scansioni: controlla a vista)` : ""}` +
      `${s["senza valori"] ? `, ${s["senza valori"]} senza valori da cercare` : ""}.`;
  }
  if (check === "riferimento") {
    const offsets = Object.entries(detail.summaries).map(([doc, x]) => {
      const o = x.summary.scarto;
      return `${Object.keys(detail.summaries).length > 1 ? `${esc(titles[doc] || doc)}: ` : ""}${o === null || o === undefined
        ? "non determinato" : `pagina del PDF = pagina stampata ${o >= 0 ? "+" : "−"} ${Math.abs(o)}`}`;
    }).join("; ");
    return `${n("voci", "voce", "voci")} nell'elenco, ${s.trovate || 0} trovate nel CSV: ${s.mancanti || 0} mancanti,
      ${s.solo_csv || 0} solo nel CSV, ${s.pagine_sbagliate || 0} con la pagina che non torna. Scarto: ${offsets}.`;
  }
  if (check === "caratteri") return `${n("occorrenze", "valore", "valori")} con caratteri sospetti.`;
  if (check === "vuoti") return `${n("righe", "riga", "righe")}, ${n("problemi", "con valori vuoti", "con valori vuoti")}.`;
  if (check === "doppioni") return `${n("gruppi", "chiave ripetuta", "chiavi ripetute")}.`;
  return "";
}

/** Come mostrare una segnalazione: pagina, problema, valori, modifica e pagine da rifare. */
function vDescribe(check, it, ov, detail, titles) {
  const cols = ov.columns, keys = ov.key_columns;
  const row = it.position !== undefined ? { doc: it.doc, page: it.page, position: it.position } : null;
  const base = { page: it.page ? vPage(it.doc, it.page) : "", values: "", edit: "", row, redo: it.page ? [[it.doc, it.page]] : [] };
  if (check === "copertura") {
    const badge = it.problem === "fallita" ? "error" : "warn";
    return { ...base, problem: `<span class="badge ${badge}">${esc(it.problem)}</span> ${esc(it.detail || "")}`,
      values: it.summary ? `<span class="small muted">Gemini: ${esc(it.summary)}</span>` : "" };
  }
  if (check === "testo") {
    const text = {
      "non trovata": `<span class="badge error">non trovata sulla pagina</span>`,
      "parziale": `<span class="badge warn">in parte</span> <span class="small">non trovata: ${esc(it.missing.join(", "))}</span>`,
      "altra pagina": `<span class="badge warn">su un'altra pagina</span> <span class="small">trovata a
        ${it.elsewhere.map(p => vPage(it.doc, p)).join(", ")}</span>`,
      "non verificabile": `<span class="badge">pagina senza testo</span> <span class="small muted">controlla a vista</span>`,
    }[it.status] || esc(it.status);
    return { ...base, problem: text, values: vValues(it.values, cols, it.missing) };
  }
  if (check === "riferimento") {
    const scarto = (detail.summaries[it.doc] || {}).summary?.scarto;
    const printed = parseInt(String(it.printed || "").replace(/\D/g, ""), 10);
    const expected = it.expected ?? (Number.isFinite(printed) && scarto !== null && scarto !== undefined ? printed + scarto : null);
    const values = vValues(it.values, keys);
    if (it.kind === "mancante") {
      const similar = (it.similar || []).map(s => `${vValues(s.values, keys)} (${s.pages.map(p => vPage(it.doc, p)).join(", ")})`);
      return { ...base, values, page: expected ? vPage(it.doc, expected, `attesa p. ${expected}`) : "",
        redo: expected ? [[it.doc, expected]] : [],
        problem: `<span class="badge error">manca nel CSV</span> <span class="small">nell'elenco${it.printed ? ` a pag. ${esc(it.printed)}` : ""}</span>
          ${similar.length ? `<br><span class="small">simile nel CSV: ${similar.join("; ")}</span>` : ""}` };
    }
    if (it.kind === "pagina") {
      return { ...base, values, page: it.pages.map(p => vPage(it.doc, p)).join(", "), redo: [[it.doc, it.expected]],
        problem: `<span class="badge warn">pagina che non torna</span> <span class="small">elenco: pag. ${esc(it.printed)} →
          attesa ${vPage(it.doc, it.expected)}, nel CSV a ${it.pages.map(p => `p. ${p}`).join(", ")}</span>` };
    }
    return { ...base, values, page: it.pages.map(p => vPage(it.doc, p)).join(", "), redo: it.pages.map(p => [it.doc, p]),
      problem: `<span class="badge warn">solo nel CSV</span> <span class="small">non è nell'elenco (forse letta male, o
        l'elenco è incompleto)</span>`, find: Object.values(it.values).join(" ") };
  }
  if (check === "caratteri") {
    const marked = esc(it.value).replace(new RegExp(`[${it.chars.map(c => c.replace(/[\\\]^-]/g, "\\$&")).join("")}]`, "gu"),
      m => `<mark>${m}</mark>`);
    return { ...base, problem: it.chars.map(vChar).join(" "),
      values: `<span class="small muted">${esc(it.column)}:</span> ${marked}`,
      edit: `<span class="row v-edit"><input type="text" data-editcol="${esc(it.column)}" value="${esc(it.value)}">
        <button class="secondary small" data-act="save" type="button">Salva</button></span>` };
  }
  if (check === "vuoti") {
    return { ...base, problem: `<span class="badge warn">vuota: ${esc(it.empty.join(", "))}</span>`,
      values: vValues(it.values, cols),
      edit: `<span class="row v-edit">${it.empty.map(c => `<input type="text" data-editcol="${esc(c)}" placeholder="${esc(c)}">`).join("")}
        <button class="secondary small" data-act="save" type="button">Salva</button></span>` };
  }
  // doppioni
  const occ = it.occurrences.map(o => `<span class="row v-occ">${Object.keys(titles).length > 1 ? `${esc(titles[o.doc] || o.doc)} · ` : ""}
      ${vPage(o.doc, o.page)} <span class="small muted">riga ${o.position + 1}</span>
      <button class="secondary small" data-act="delete" data-doc="${esc(o.doc)}" data-page="${o.page}" data-pos="${o.position}"
        type="button" title="Togli questa riga dal CSV">Elimina</button></span>`).join("");
  return { ...base, page: "", row: null, redo: it.occurrences.map(o => [o.doc, o.page]),
    problem: `<strong>${vValues(it.key, keys)}</strong> <span class="small">${it.occurrences.length} righe
      ${it.same_pdf ? "nello stesso PDF" : "in PDF diversi"}</span>`, values: occ };
}

// ------------------------------------------------------------------ la schermata
async function renderVerify(ctx) {
  const { pid, box } = ctx;
  const ui = verifyUI[pid] || (verifyUI[pid] = { docs: null, check: null, showAccepted: false, settingsOpen: false,
                                                 rows: { q: "", page: "", doc: null, offset: 0 } });
  ctx.rerender = () => renderVerify(ctx);
  let ov;
  try { ov = await api("GET", `/api/projects/${enc(pid)}/verifiche`); }
  catch (e) { box.innerHTML = `<div class="panel note warn">${esc(e.message)}</div>`; return; }
  const indexed = ov.documents.filter(d => d.indexed);
  if (!indexed.length) {
    box.innerHTML = `<div class="panel note">Nessun PDF ancora indicizzato: <a href="#/p/${enc(pid)}/index">avvia
      l'indicizzazione</a> (passo ④), poi qui puoi verificare e correggere i risultati.</div>`;
    return;
  }
  if (ui.docs) ui.docs = ui.docs.filter(id => indexed.some(d => d.id === id));
  if (ui.docs && !ui.docs.length) ui.docs = null;
  const sel = ui.docs || indexed.map(d => d.id);
  const selDocs = ov.documents.filter(d => sel.includes(d.id));
  const titles = Object.fromEntries(selDocs.map(d => [d.id, d.title]));
  if (ui.check === null) {          // apre la prima verifica con qualcosa da vedere ("" = chiusa dall'utente)
    const first = ov.checks.find(c => selDocs.some(d => d.checks[c.id].state === "problemi"));
    ui.check = first ? first.id : null;
  }
  const docsParam = sel.join(",");
  const [detail, corrections] = await Promise.all([
    ui.check ? api("GET", `/api/projects/${enc(pid)}/verifiche/${ui.check}?docs=${enc(docsParam)}`) : null,
    api("GET", `/api/projects/${enc(pid)}/correzioni`),
  ]);
  // verifiche già eseguite sui PDF scelti: dopo una correzione si rifanno da sole (il confronto con l'elenco
  // di riferimento già letto non usa Gemini)
  const ran = ov.checks.filter(c => selDocs.some(d => !["non eseguita", "non indicizzato"].includes(d.checks[c.id].state)));
  const env = { ctx, ui, ov, sel, selDocs, titles, ran: ran.map(c => c.id) };

  box.innerHTML = `
    <div class="panel">
      <div class="row"><h3 class="m-0">Verifiche ed elaborazione</h3><span class="spacer"></span>
        <a class="small" href="/api/projects/${enc(pid)}/download/csv">Scarica il CSV (con le correzioni)</a>
        <button id="v-run-all" type="button" title="Copertura, contenuto sulla pagina, caratteri, vuoti, doppioni e il confronto con gli elenchi di riferimento già letti: subito, senza chiamare Gemini">
          Esegui le verifiche senza Gemini</button></div>
      <p class="hint">Controlli sui risultati dell'indicizzazione: non cambiano nulla da soli. Le correzioni (sostituzioni, celle
        modificate, righe eliminate) si applicano al CSV ogni volta che si genera, senza toccare ciò che ha letto Gemini, e
        si possono togliere.${ov.corrections ? ` <strong>${plural(ov.corrections, "correzione", "correzioni")}</strong> in uso.` : ""}</p>
      <div class="chips v-docs">
        <button type="button" class="chip ${ui.docs ? "" : "on"}" data-vdocs="all">Tutti i PDF <span class="small">${indexed.length}</span></button>
        ${ov.documents.map(d => `<button type="button" class="chip ${ui.docs && ui.docs.includes(d.id) ? "on" : ""}" data-vdoc="${esc(d.id)}"
          ${d.indexed ? "" : 'disabled title="Non ancora indicizzato"'}>${esc(d.title)}</button>`).join("")}
      </div>
      ${ov.documents.length > 1 ? `<p class="hint">Clic su un PDF per lavorare solo su quello; Ctrl (⌘ sul Mac) + clic per
        sceglierne più d'uno. Verifiche, righe e azioni valgono per i PDF scelti.</p>` : ""}
      <div class="table-wrap v-matrix"><table><thead><tr><th>Verifica</th>
          ${selDocs.map(d => `<th>${selDocs.length > 1 ? esc(d.title) : "Esito"}</th>`).join("")}<th></th></tr></thead><tbody>
        ${ov.checks.map(c => `<tr class="clickable ${c.id === ui.check ? "current" : ""}" data-vcheck="${c.id}">
          <td><strong>${esc(c.label)}</strong>${c.paid ? ' <span class="badge" title="Usa Gemini: una richiesta per PDF, la prima volta">✨ Gemini</span>' : ""}
            <br><span class="small muted">${esc(VERIFY_HELP[c.id])}</span></td>
          ${selDocs.map(d => `<td>${verifyCell(d.checks[c.id])}</td>`).join("")}
          <td class="nowrap"><button type="button" class="${c.paid ? "secondary gemini" : "secondary"} small" data-vrun="${c.id}">Esegui</button></td>
        </tr>`).join("")}
      </tbody></table></div>
    </div>
    <div id="v-detail"></div>
    <details class="panel" id="v-settings" ${ui.settingsOpen ? "open" : ""}></details>
    <div class="panel" id="v-rows"><p class="muted small">Caricamento delle righe…</p></div>
    <details class="panel" id="v-corr" ${ui.corrOpen || corrections.rules.length + corrections.edits.length + corrections.deletions.length ? "open" : ""}></details>`;

  $("#v-run-all", box).addEventListener("click", e => busy(e.target, () => vRun(env, "tutte")));
  $$("[data-vrun]", box).forEach(b => b.addEventListener("click", e => {
    e.stopPropagation();
    ui.check = b.dataset.vrun;
    busy(b, () => vRun(env, b.dataset.vrun));
  }));
  $$("[data-vcheck]", box).forEach(tr => tr.addEventListener("click", () => {
    ui.check = ui.check === tr.dataset.vcheck ? "" : tr.dataset.vcheck;
    ctx.rerender();
  }));
  $$("[data-vdocs]", box).forEach(b => b.addEventListener("click", () => { ui.docs = null; vResetRows(ui); ctx.rerender(); }));
  $$("[data-vdoc]", box).forEach(b => b.addEventListener("click", e => {
    const id = b.dataset.vdoc;
    if (e.ctrlKey || e.metaKey) {
      const cur = new Set(ui.docs || []);
      cur.has(id) ? cur.delete(id) : cur.add(id);
      ui.docs = cur.size ? [...cur] : null;
    } else ui.docs = ui.docs && ui.docs.length === 1 && ui.docs[0] === id ? null : [id];
    vResetRows(ui);
    ctx.rerender();
  }));
  vRenderDetail(env, detail);
  vRenderSettings(env);
  vRenderCorrections(env, corrections);
  if (ctx.updateSteps) ctx.updateSteps();
  await vLoadRows(env);
}

function vResetRows(ui) { ui.rows = { q: "", page: "", doc: null, offset: 0 }; }

/** Esegue una verifica (o "tutte" quelle senza Gemini) sui PDF scelti. */
async function vRun(env, check, extra = {}) {
  const { ctx, ui, sel, selDocs } = env;
  if (check === "riferimento") {
    const toRead = selDocs.filter(d => extra.reread || !d.reference);
    if (toRead.length) {
      const missing = toRead.filter(d => !d.reference_pages);
      if (missing.length) {
        ui.settingsOpen = true;
        toast(`Scegli le pagine dell'elenco di riferimento per: ${missing.map(d => d.title).join(", ")} (impostazioni qui sotto).`, 7000);
        ctx.rerender();
        return;
      }
      const ok = await confirmDialog({ title: "Leggere l'elenco di riferimento con Gemini?", ok: "Leggi con Gemini", html: `
        <p>${plural(toRead.length, "richiesta", "richieste")} a Gemini, una per PDF: trascrive l'elenco (voci e pagine) da</p>
        <ul>${toRead.map(d => `<li><strong>${esc(d.title)}</strong>: pagine ${esc(d.reference_pages)}</li>`).join("")}</ul>
        <p class="hint">Poi il confronto con il CSV si rifà senza Gemini. L'elenco letto si può vedere e correggere a mano.</p>` });
      if (!ok) return;
    }
  }
  const r = await api("POST", `/api/projects/${enc(ctx.pid)}/verifiche/${check}`, { docs: sel, ...extra });
  if (r.job) {
    ctx.box.innerHTML = "";
    watchJob(ctx.jobBox, r.job, () => ctx.rerender());
    return;
  }
  const skipped = Object.entries(r.skipped || {});
  if (skipped.length) toast(`Non eseguite: ${skipped.map(([c, why]) => `${c} (${why})`).join("; ")}`, 9000);
  else if (check === "tutte") toast("Verifiche eseguite.");
  if (check === "tutte" && !ui.check) ui.check = null;
  ctx.rerender();
}

/** Dopo una correzione: le verifiche già eseguite si rifanno (senza Gemini) e la schermata si aggiorna. */
async function vAfterChange(env, message = "") {
  if (env.ran.length) {
    await api("POST", `/api/projects/${enc(env.ctx.pid)}/verifiche/tutte`, { docs: env.sel, checks: env.ran });
  }
  if (message) toast(message);
  env.ctx.rerender();
}

// ------------------------------------------------------------------ segnalazioni della verifica aperta
function vRenderDetail(env, detail) {
  const { ctx, ui, ov, titles } = env;
  const el = $("#v-detail");
  if (!detail) { el.innerHTML = ""; return; }
  const check = detail.check;
  const all = detail.items;
  const accepted = all.filter(i => i.accepted).length;
  const items = ui.showAccepted ? all : all.filter(i => !i.accepted);
  const run = Object.keys(detail.summaries).length;
  const multi = env.selDocs.length > 1;
  const rows = items.map((it, i) => ({ it, i, d: vDescribe(check, it, ov, detail, titles) }));

  let groups = "";
  if (check === "caratteri" && items.length) {
    const byChar = new Map();
    items.forEach(it => it.chars.forEach(ch => {
      const g = byChar.get(ch) || { n: 0, columns: new Set() };
      g.n++; g.columns.add(it.column); byChar.set(ch, g);
    }));
    const oneDoc = ui.docs && ui.docs.length === 1 && ov.documents.length > 1 ? ui.docs[0] : null;
    groups = `<div class="v-groups">${[...byChar.entries()].map(([ch, g]) => {
      const column = g.columns.size === 1 ? [...g.columns][0] : null;
      return `<div class="row v-group" data-char="${esc(ch)}" data-column="${esc(column || "")}" data-doc="${esc(oneDoc || "")}">
        ${vChar(ch)} <span class="small">${plural(g.n, "valore", "valori")} in ${esc([...g.columns].join(", "))}</span>
        <span class="spacer"></span><span class="small">sostituisci con</span>
        <input type="text" class="v-repl input-short" placeholder="(niente: toglilo)">
        <button class="small" data-act="replace-all" type="button" title="Una regola: vale anche per le pagine indicizzate dopo">
          Sostituisci tutte</button>
        <span class="small muted">${column ? `in ${esc(column)}` : "in tutte le colonne"}, ${oneDoc ? "in questo PDF" : "in tutti i PDF"}</span>
      </div>`;
    }).join("")}</div>
    <p class="hint">Oppure correggi i valori uno per uno qui sotto. Per sostituire un testo più lungo di un carattere usa
      <em>Sostituisci tutte</em> nelle correzioni, in fondo.</p>`;
  }

  el.innerHTML = `<div class="panel">
    <div class="row"><h3 class="m-0">${esc(detail.label)}</h3><span class="spacer"></span>
      ${accepted ? `<label class="small inline"><input type="checkbox" id="v-show-acc" ${ui.showAccepted ? "checked" : ""}>
        mostra anche quelle che vanno bene (${accepted})</label>` : ""}</div>
    <p class="hint">${esc(VERIFY_HELP[check])}</p>
    ${run ? `<p>${vSummaryText(check, detail, titles)}</p>` : `<p class="muted">Non ancora eseguita sui PDF scelti: usa <em>Esegui</em>.</p>`}
    ${check === "riferimento" && run ? `<p class="hint">L'elenco letto da Gemini si vede e si corregge nelle impostazioni qui sotto.</p>` : ""}
    ${groups}
    ${items.length ? `
      <div class="selbar">
        <label class="small inline"><input type="checkbox" id="v-all"> tutte</label>
        <button class="secondary small" data-bulk="accept" type="button" title="La segnalazione resta, ma non conta più tra quelle da vedere">Va bene così</button>
        <button class="secondary small" data-bulk="unaccept" type="button" ${accepted ? "" : "hidden"}>Da rivedere</button>
        <button class="secondary small gemini" data-bulk="redo" type="button" title="Rifà con Gemini le pagine delle segnalazioni scelte">Rifai le pagine</button>
        <span class="small muted" id="v-count"></span>
      </div>
      <div class="table-wrap v-items"><table><thead><tr><th></th>${multi ? "<th>PDF</th>" : ""}<th>Pagina</th><th>Problema</th><th>Valori</th><th></th></tr></thead><tbody>
        ${rows.map(({ it, i, d }) => `<tr data-i="${i}" class="${it.accepted ? "accepted" : ""}">
          <td><input type="checkbox" data-pick="${i}"></td>
          ${multi ? `<td class="small">${check === "doppioni" ? "" : esc(titles[it.doc] || it.doc || "")}</td>` : ""}
          <td class="nowrap">${d.page}</td>
          <td>${d.problem}${it.accepted ? ' <span class="badge ok">va bene così</span>' : ""}</td>
          <td>${d.values}${d.edit ? `<div>${d.edit}</div>` : ""}</td>
          <td class="v-actions">
            ${d.row ? `<button class="secondary small" data-act="rows" type="button" title="Mostra la riga tra le righe del CSV, per modificarla">Modifica</button>
              <button class="secondary small" data-act="delete" data-doc="${esc(d.row.doc)}" data-page="${d.row.page}" data-pos="${d.row.position}" type="button" title="Togli la riga dal CSV">Elimina</button>` : ""}
            ${d.find ? `<button class="secondary small" data-act="find" type="button" title="Cerca tra le righe del CSV">Mostra</button>` : ""}
            ${d.redo.length ? `<button class="secondary small gemini" data-act="redo" type="button" title="Rifai con Gemini ${d.redo.length > 1 ? "queste pagine" : "questa pagina"}">Rifai</button>` : ""}
            <button class="secondary small" data-act="${it.accepted ? "unaccept" : "accept"}" type="button">${it.accepted ? "Da rivedere" : "Va bene così"}</button>
          </td></tr>`).join("")}
      </tbody></table></div>` : run ? `<div class="note">Nessuna segnalazione da vedere${accepted ? ` (${accepted} marcate come "va bene così")` : ""}.</div>` : ""}
  </div>`;

  const picks = () => $$("[data-pick]", el).filter(c => c.checked).map(c => rows[+c.dataset.pick]);
  const count = () => { const n = picks().length; $("#v-count", el) && ($("#v-count", el).textContent = n ? `${n} scelte` : ""); };
  $$("[data-pick]", el).forEach(c => c.addEventListener("change", count));
  if ($("#v-all", el)) $("#v-all", el).addEventListener("change", e => { $$("[data-pick]", el).forEach(c => { c.checked = e.target.checked; }); count(); });
  if ($("#v-show-acc", el)) $("#v-show-acc", el).addEventListener("change", e => { ui.showAccepted = e.target.checked; vRenderDetail(env, detail); });

  const accept = (list, value) => busy(null, async () => {
    await api("POST", `/api/projects/${enc(ctx.pid)}/verifiche/accetta`, { ids: list.map(r => r.it.id), accepted: value });
    ctx.rerender();
  });
  $$("[data-bulk]", el).forEach(b => b.addEventListener("click", () => {
    const list = picks();
    if (!list.length) { toast("Scegli prima qualche segnalazione (casella a sinistra)."); return; }
    if (b.dataset.bulk === "accept") accept(list, true);
    else if (b.dataset.bulk === "unaccept") accept(list, false);
    else vRedo(env, list.flatMap(r => r.d.redo));
  }));

  bindVerifyPages(el, titles);
  $$("tr[data-i]", el).forEach(tr => {
    const { it, d } = rows[+tr.dataset.i];
    $$("[data-act]", tr).forEach(b => b.addEventListener("click", e => {
      const act = b.dataset.act;
      if (act === "page") return;
      e.preventDefault();
      if (act === "accept" || act === "unaccept") accept([rows[+tr.dataset.i]], act === "accept");
      else if (act === "redo") vRedo(env, d.redo);
      else if (act === "rows") vShowRows(env, { doc: d.row.doc, page: d.row.page });
      else if (act === "find") vShowRows(env, { doc: it.doc, q: d.find });
      else if (act === "delete") vDeleteRow(env, b.dataset.doc, +b.dataset.page, +b.dataset.pos);
      else if (act === "save") vSaveCells(env, d.row, $$("[data-editcol]", tr), b);
    }));
    $$("[data-editcol]", tr).forEach(input => input.addEventListener("keydown", e => {
      if (e.key === "Enter") { e.preventDefault(); vSaveCells(env, d.row, $$("[data-editcol]", tr), null); }
    }));
  });
  $$(".v-group", el).forEach(g => $("[data-act=replace-all]", g).addEventListener("click", e => busy(e.target, async () => {
    await api("POST", `/api/projects/${enc(ctx.pid)}/correzioni/regola`, {
      find: g.dataset.char, replace: $(".v-repl", g).value, column: g.dataset.column || null, doc: g.dataset.doc || null });
    await vAfterChange(env, "Sostituzione aggiunta alle correzioni.");
  })));
}

function bindVerifyPages(root, titles) {
  $$("[data-act=page]", root).forEach(a => a.addEventListener("click", e => {
    e.preventDefault(); e.stopPropagation();
    showPage(a.dataset.doc, a.dataset.page, titles[a.dataset.doc] || "");
  }));
}

async function vSaveCells(env, row, inputs, button) {
  const changed = inputs.filter(i => i.value !== i.defaultValue);
  if (!changed.length) { toast("Nessun valore cambiato."); return; }
  await busy(button, async () => {
    for (const input of changed) {
      await api("POST", `/api/projects/${enc(env.ctx.pid)}/correzioni/cella`,
                { doc: row.doc, page: row.page, position: row.position, column: input.dataset.editcol, value: input.value });
    }
    await vAfterChange(env, changed.length > 1 ? "Valori corretti." : "Valore corretto.");
  });
}

async function vDeleteRow(env, doc, page, position) {
  const ok = await confirmDialog({ title: "Eliminare la riga?", ok: "Elimina", danger: true, html: `
    <p>La riga ${position + 1} della pagina ${page}${env.selDocs.length > 1 ? ` di <strong>${esc(env.titles[doc] || doc)}</strong>` : ""}
      non comparirà più nel CSV.</p>
    <p class="hint">È una correzione: ciò che ha letto Gemini resta, e la puoi ripristinare dall'elenco delle correzioni.</p>` });
  if (!ok) return;
  await busy(null, async () => {
    await api("POST", `/api/projects/${enc(env.ctx.pid)}/correzioni/riga`, { doc, page, position });
    await vAfterChange(env, "Riga eliminata dal CSV.");
  });
}

/** Rifà con Gemini alcune pagine: ``list`` = [[doc, pagina], ...]. */
async function vRedo(env, list) {
  const { ctx } = env;
  const pages = {};
  list.forEach(([doc, page]) => { if (doc && page) (pages[doc] = pages[doc] || new Set()).add(+page); });
  const docs = Object.keys(pages);
  if (!docs.length) { toast("Nessuna pagina da rifare tra quelle scelte."); return; }
  const n = docs.reduce((s, d) => s + pages[d].size, 0);
  const p = ctx.project;
  const asSet = docs.reduce((s, d) => s + requestsFor(p, pages[d].size), 0);
  const ok = await confirmDialog({ title: `Rifare ${plural(n, "pagina", "pagine")} con Gemini?`, ok: "Rifai", html: `
    <ul>${docs.map(d => `<li><strong>${esc(ctx.titles[d] || d)}</strong>: ${esc(formatPages([...pages[d]]))}</li>`).join("")}</ul>
    ${p.send_mode === "insieme" ? `
      <label class="row send-option"><input type="radio" name="redo-send" value="insieme" checked>
        <span>${esc(sendModeText(p))}: ${plural(asSet, "richiesta", "richieste")}</span></label>
      <label class="row send-option"><input type="radio" name="redo-send" value="pagina">
        <span>una pagina per richiesta (più preciso sulle pagine difficili): ${plural(n, "richiesta", "richieste")}</span></label>`
      : `<p>${plural(n, "richiesta", "richieste")} a Gemini, una per pagina.</p>`}
    <p class="hint">I risultati attuali di queste pagine vengono sostituiti. Le correzioni a mano sulle loro righe restano valide
      solo se il valore letto non cambia: altrimenti risultano "non più applicabili" tra le correzioni.</p>` });
  if (!ok) return;
  const choice = $('#confirm-body input[name="redo-send"]:checked');
  const body = { redo: Object.fromEntries(docs.map(d => [d, [...pages[d]]])) };
  if (choice) body.send = choice.value;
  await busy(null, async () => {
    const job = await api("POST", `/api/projects/${enc(ctx.pid)}/index`, body);
    ctx.box.innerHTML = "";
    watchJob(ctx.jobBox, job, async j => {
      if (j.result && j.result.stopped_reason) toast(j.result.stopped_reason, 8000);
      try { await vAfterChange(env, jobSucceeded(j) ? "Pagine rifatte: verifiche aggiornate." : ""); }
      catch (e) { showError(e); ctx.rerender(); }
    });
  });
}

// ------------------------------------------------------------------ impostazioni
function vRenderSettings(env) {
  const { ctx, ui, ov, selDocs } = env;
  const el = $("#v-settings");
  const checkCols = new Set(ov.check_columns);
  el.innerHTML = `
    <summary><strong>Impostazioni delle verifiche</strong> <span class="small muted">— copertura: ${esc(COVERAGE_TEXT[ov.coverage][0].toLowerCase())} ·
      testo: ${esc(ov.check_columns.join(", ") || "nessuna colonna")} · chiave: ${esc(ov.key_columns.join(" + ") || "nessuna")}</span></summary>
    <div class="grid2 mt-s">
      <div>
        <label>Copertura: quante righe deve avere ogni pagina inviata</label>
        ${Object.entries(COVERAGE_TEXT).map(([k, [label, help]]) => `<label class="row send-option my-2xs">
          <input type="radio" name="v-coverage" value="${k}" ${ov.coverage === k ? "checked" : ""}>
          <span><strong>${esc(label)}</strong>: ${esc(help)}</span></label>`).join("")}
        <label>Colonne chiave</label>
        <p class="small">${ov.key_columns.length ? `<strong>${esc(ov.key_columns.join(" + "))}</strong>` : '<span class="badge warn">nessuna</span>'}
          — identificano una riga; servono a elenco di riferimento, doppioni e valori vuoti. Si scelgono nella
          <a href="#/p/${enc(ctx.pid)}/settings">Tabella</a> (passo ①), senza dover rifare l'indicizzazione.</p>
      </div>
      <div>
        <label>Colonne da cercare nel testo della pagina</label>
        <div class="chips v-cols">${ov.columns.map(c => `<label class="chip"><input type="checkbox" data-vcol="${esc(c)}"
          ${checkCols.has(c) ? "checked" : ""}> ${esc(c)}</label>`).join("")}</div>
        <p class="hint">Nessuna scelta = le colonne chiave. Conviene scegliere colonne con valori stampati così come sono (codici,
          modelli, misure), non testi riassunti o tradotti da Gemini.</p>
      </div>
    </div>
    <label>Elenco di riferimento: le pagine di ogni PDF che elencano tutte le voci (indice, sommario, listino…)</label>
    <div class="table-wrap"><table><thead><tr><th>PDF</th><th>Pagine dell'elenco</th><th>Elenco letto</th><th></th></tr></thead><tbody>
      ${selDocs.map(d => `<tr><td><strong>${esc(d.title)}</strong></td>
        <td><input type="text" data-vref="${esc(d.id)}" value="${esc(d.reference_chosen || "")}"
          placeholder="${d.reference_pages ? `${esc(d.reference_pages)} (Indice nella scheda)` : "es. 3-4"}" class="input-medium"></td>
        <td class="small">${d.reference ? `${plural(d.reference.items, "voce", "voci")}${d.reference.edited ? ' <span class="badge">corretto a mano</span>' : ""}`
          : '<span class="muted">non ancora letto</span>'}</td>
        <td class="nowrap">${d.reference ? `<button class="secondary small" data-vrefedit="${esc(d.id)}" type="button">Vedi e correggi</button>` : ""}
          <button class="secondary small gemini" data-vreread="${esc(d.id)}" type="button">${d.reference ? "Rileggi" : "Leggi"} con Gemini</button></td></tr>`).join("")}
    </tbody></table></div>
    <p class="hint">Vuoto = le pagine segnate come <em>Indice</em> nella scheda del catalogo. Con più colonne chiave, una voce
      dell'elenco corrisponde a una riga quando coincidono tutte.</p>
    <div class="row mt-s"><span class="spacer"></span><button id="v-save-settings" type="button">Salva le impostazioni</button></div>`;
  el.addEventListener("toggle", () => { ui.settingsOpen = el.open; });
  $("#v-save-settings", el).addEventListener("click", e => busy(e.target, async () => {
    await api("PUT", `/api/projects/${enc(ctx.pid)}/verifiche/impostazioni`, {
      coverage: $('input[name="v-coverage"]:checked', el).value,
      check_columns: $$("[data-vcol]", el).filter(c => c.checked).map(c => c.dataset.vcol),
      reference_pages: Object.fromEntries($$("[data-vref]", el).map(i => [i.dataset.vref, i.value.trim()])),
    });
    ui.settingsOpen = true;
    await vAfterChange(env, "Impostazioni salvate: verifiche aggiornate.");
  }));
  $$("[data-vreread]", el).forEach(b => b.addEventListener("click", () => {
    const doc = ov.documents.find(d => d.id === b.dataset.vreread);
    const input = $(`[data-vref="${CSS.escape(doc.id)}"]`, el);
    if (input.value.trim() !== (doc.reference_chosen || "")) { toast("Salva prima le impostazioni (pagine dell'elenco cambiate)."); return; }
    ui.check = "riferimento";
    busy(b, () => vRun({ ...env, sel: [doc.id], selDocs: [doc] }, "riferimento", { reread: true }));
  }));
  $$("[data-vrefedit]", el).forEach(b => b.addEventListener("click", () => busy(b, () => vEditReference(env, b.dataset.vrefedit))));
}

/** L'elenco letto da Gemini, una voce per riga: si corregge a mano e il confronto si rifà. */
async function vEditReference(env, docId) {
  const { ctx } = env;
  const r = await api("GET", `/api/projects/${enc(ctx.pid)}/verifiche/riferimento/${enc(docId)}`);
  const keys = r.key_columns;
  const lines = r.reference.items.map(it => [...keys.map(k => it.values[k] || ""), it.page || ""].join(" | "));
  const ok = await confirmDialog({ title: `Elenco di riferimento — ${ctx.titles[docId] || docId}`, ok: "Salva l'elenco", html: `
    <p class="hint">Letto da Gemini dalle pagine ${esc(r.pages)}${r.reference.notes ? `. Note di Gemini: ${esc(r.reference.notes)}` : ""}.
      Una voce per riga: <code>${esc([...keys, "pagina stampata"].join(" | "))}</code> (la pagina si può lasciare vuota).</p>
    <textarea id="v-ref-text" class="mono tall">${esc(lines.join("\n"))}</textarea>` });
  if (!ok) return;
  const items = $("#v-ref-text").value.split("\n").map(l => l.trim()).filter(Boolean).map(l => {
    const parts = l.split("|").map(s => s.trim());
    return { values: Object.fromEntries(keys.map((k, i) => [k, parts[i] || ""])), page: parts.length > keys.length ? parts[keys.length] : "" };
  });
  await api("PUT", `/api/projects/${enc(ctx.pid)}/verifiche/riferimento/${enc(docId)}`, { items });
  env.ui.check = "riferimento";
  await api("POST", `/api/projects/${enc(ctx.pid)}/verifiche/riferimento`, { docs: [docId] });
  await vAfterChange(env, "Elenco salvato: confronto rifatto.");
}

// ------------------------------------------------------------------ righe del CSV (corrette, modificabili)
function vShowRows(env, { doc = null, page = "", q = "" }) {
  env.ui.rows = { q, page: page ? String(page) : "", doc, offset: 0 };
  vLoadRows(env).then(() => $("#v-rows").scrollIntoView({ behavior: "smooth", block: "start" }));
}

async function vLoadRows(env) {
  const { ctx, ui, sel, titles } = env;
  const el = $("#v-rows");
  if (!el) return;
  const f = ui.rows;
  const params = new URLSearchParams({ docs: (f.doc ? [f.doc] : sel).join(","), q: f.q, offset: f.offset, limit: ROWS_PER_PAGE });
  if (f.page) params.set("page", f.page);
  let r;
  try { r = await api("GET", `/api/projects/${enc(ctx.pid)}/righe?${params}`); }
  catch (e) { el.innerHTML = `<div class="note warn">${esc(e.message)}</div>`; return; }
  const multi = !f.doc && sel.length > 1;
  const from = r.total ? f.offset + 1 : 0, to = Math.min(f.offset + ROWS_PER_PAGE, r.total);
  const hadFocus = document.activeElement && document.activeElement.id;
  el.innerHTML = `
    <div class="row"><h3 class="m-0">Righe del CSV</h3><span class="small muted">come finiranno nel CSV, con le correzioni</span></div>
    <p class="hint">Clic su una cella per correggerla (Invio salva, Esc annulla); le celle corrette sono evidenziate. Clic sul numero
      di pagina per vederla.</p>
    <div class="row v-rows-bar">
      <input type="text" id="v-q" placeholder="Cerca nelle righe…" value="${esc(f.q)}" class="input-wide">
      <input type="number" id="v-pg" placeholder="pagina" min="1" value="${esc(f.page)}">
      ${f.doc ? `<span class="chip on">${esc(titles[f.doc] || ctx.titles[f.doc] || f.doc)}</span>` : ""}
      ${f.doc || f.page || f.q ? `<button class="secondary small" id="v-clear" type="button">Tutte le righe</button>` : ""}
      <span class="spacer"></span>
      <span class="small muted">${from}–${to} di ${r.total}</span>
      <button class="secondary small" id="v-prev" type="button" ${f.offset ? "" : "disabled"}>&lsaquo;</button>
      <button class="secondary small" id="v-next" type="button" ${to < r.total ? "" : "disabled"}>&rsaquo;</button>
    </div>
    ${r.rows.length ? `<div class="table-wrap"><table class="v-rows"><thead><tr>${multi ? "<th>PDF</th>" : ""}<th>Pagina</th>
        ${r.data_columns.map(c => `<th>${esc(c)}</th>`).join("")}<th></th></tr></thead><tbody>
      ${r.rows.map((row, i) => `<tr data-row="${i}">
        ${multi ? `<td class="small">${esc(row.title)}</td>` : ""}
        <td class="nowrap">${vPage(row.doc, row.page, String(row.page))} <span class="small muted">r. ${row.position + 1}</span></td>
        ${r.data_columns.map(c => `<td class="cell${row.changed.includes(c) ? " changed" : ""}" data-col="${esc(c)}"
          title="${row.changed.includes(c) ? "Corretto. " : ""}Clic per modificare">${esc(row.values[c])}</td>`).join("")}
        <td><button class="secondary small" data-del="${i}" type="button" title="Togli la riga dal CSV">&times;</button></td></tr>`).join("")}
    </tbody></table></div>` : `<p class="muted">Nessuna riga${f.q || f.page ? " con questi filtri" : ""}.</p>`}`;

  let timer = null;
  const reload = () => { f.offset = 0; vLoadRows(env); };
  $("#v-q", el).addEventListener("input", e => { clearTimeout(timer); timer = setTimeout(() => { f.q = e.target.value; reload(); }, 350); });
  $("#v-pg", el).addEventListener("change", e => { f.page = e.target.value.trim(); reload(); });
  if (hadFocus === "v-q") { const q = $("#v-q", el); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
  if ($("#v-clear", el)) $("#v-clear", el).addEventListener("click", () => { vResetRows(ui); vLoadRows(env); });
  $("#v-prev", el).addEventListener("click", () => { f.offset = Math.max(0, f.offset - ROWS_PER_PAGE); vLoadRows(env); });
  $("#v-next", el).addEventListener("click", () => { f.offset += ROWS_PER_PAGE; vLoadRows(env); });
  bindVerifyPages(el, ctx.titles);
  $$("[data-del]", el).forEach(b => b.addEventListener("click", () => {
    const row = r.rows[+b.dataset.del];
    vDeleteRow(env, row.doc, row.page, row.position);
  }));
  $$("td.cell", el).forEach(td => td.addEventListener("click", () => {
    if (td.querySelector("input")) return;
    const row = r.rows[+td.parentElement.dataset.row], column = td.dataset.col, before = row.values[column] ?? "";
    td.innerHTML = `<input type="text" value="${esc(before)}">`;
    const input = td.querySelector("input");
    input.focus(); input.select();
    let done = false;
    const finish = async save => {
      if (done) return;
      done = true;
      if (!save || input.value === before) { td.textContent = before; return; }
      td.textContent = input.value;
      try {
        await api("POST", `/api/projects/${enc(ctx.pid)}/correzioni/cella`,
                  { doc: row.doc, page: row.page, position: row.position, column, value: input.value });
        await vAfterChange(env, "Valore corretto.");
      } catch (e) { showError(e); td.textContent = before; }
    };
    input.addEventListener("keydown", e => {
      if (e.key === "Enter") { e.preventDefault(); finish(true); }
      else if (e.key === "Escape") finish(false);
    });
    input.addEventListener("blur", () => finish(true));
  }));
}

// ------------------------------------------------------------------ correzioni
function vRenderCorrections(env, corr) {
  const { ctx, ui, ov } = env;
  const el = $("#v-corr");
  const total = corr.rules.length + corr.edits.length + corr.deletions.length;
  const multi = ov.documents.length > 1;
  const gone = '<span class="badge warn" title="Dopo una reindicizzazione la riga non è più quella di prima: la correzione resta ma non si applica">non più applicabile</span>';
  const code = s => s === "" ? '<span class="muted small">(niente)</span>' : `<code>${esc(s)}</code>`;
  el.innerHTML = `
    <summary><strong>Correzioni</strong> <span class="small muted">(${total}) — applicate al CSV e alla pagina di ricerca ogni volta
      che si generano; ciò che ha letto Gemini resta intatto</span></summary>
    <h4>Sostituisci tutte</h4>
    <div class="row v-rule">
      <input type="text" id="c-find" placeholder="trova (es. §)">
      <span class="small">con</span>
      <input type="text" id="c-repl" placeholder="(niente: toglilo)">
      <select id="c-col"><option value="">in tutte le colonne</option>
        ${ov.columns.map(c => `<option value="${esc(c)}">in ${esc(c)}</option>`).join("")}</select>
      ${multi ? `<select id="c-doc"><option value="">in tutti i PDF</option>
        ${ov.documents.map(d => `<option value="${esc(d.id)}" ${ui.docs && ui.docs.length === 1 && ui.docs[0] === d.id ? "selected" : ""}>in ${esc(d.title)}</option>`).join("")}</select>` : ""}
      <button id="c-add" type="button">Sostituisci tutte</button>
    </div>
    <p class="hint">Distingue maiuscole e minuscole. Vale anche per le pagine indicizzate dopo; non tocca le celle corrette a mano.</p>
    ${corr.rules.length ? `<div class="table-wrap"><table><thead><tr><th>Trova</th><th>Sostituisci con</th><th>Colonna</th>${multi ? "<th>PDF</th>" : ""}<th>Celle cambiate</th><th></th></tr></thead><tbody>
      ${corr.rules.map(x => `<tr><td>${code(x.find)}</td><td>${code(x.replace)}</td><td>${esc(x.column || "tutte")}</td>
        ${multi ? `<td>${esc(x.doc_title || "tutti")}</td>` : ""}<td>${x.changed}</td>
        <td><button class="secondary small" data-cdel="${esc(x.id)}" type="button">Togli</button></td></tr>`).join("")}
    </tbody></table></div>` : ""}
    ${corr.edits.length ? `<h4>Celle corrette a mano</h4><div class="table-wrap"><table><thead><tr>${multi ? "<th>PDF</th>" : ""}<th>Pagina</th><th>Colonna</th><th>Letto da Gemini</th><th>Corretto</th><th></th></tr></thead><tbody>
      ${corr.edits.map(x => `<tr>${multi ? `<td class="small">${esc(x.doc_title)}</td>` : ""}
        <td class="nowrap">${vPage(x.doc, x.page)} <span class="small muted">r. ${x.position + 1}</span></td>
        <td>${esc(x.column)}</td><td>${code(x.original)}</td><td>${code(x.value)} ${x.applicable ? "" : gone}</td>
        <td><button class="secondary small" data-cdel="${esc(x.id)}" type="button" title="Torna al valore letto da Gemini">Togli</button></td></tr>`).join("")}
    </tbody></table></div>` : ""}
    ${corr.deletions.length ? `<h4>Righe eliminate</h4><div class="table-wrap"><table><thead><tr>${multi ? "<th>PDF</th>" : ""}<th>Pagina</th><th>Valori</th><th></th></tr></thead><tbody>
      ${corr.deletions.map(x => `<tr>${multi ? `<td class="small">${esc(x.doc_title)}</td>` : ""}
        <td class="nowrap">${vPage(x.doc, x.page)} <span class="small muted">r. ${x.position + 1}</span></td>
        <td>${vValues(x.original, Object.keys(x.original))} ${x.applicable ? "" : gone}</td>
        <td><button class="secondary small" data-cdel="${esc(x.id)}" type="button">Ripristina</button></td></tr>`).join("")}
    </tbody></table></div>` : ""}
    ${total ? "" : `<p class="muted small">Nessuna correzione.</p>`}`;
  el.addEventListener("toggle", () => { ui.corrOpen = el.open; });
  bindVerifyPages(el, ctx.titles);
  $("#c-add", el).addEventListener("click", e => {
    const find = $("#c-find", el).value;
    if (!find) { toast("Scrivi il testo da sostituire."); return; }
    busy(e.target, async () => {
      const view = await api("POST", `/api/projects/${enc(ctx.pid)}/correzioni/regola`, {
        find, replace: $("#c-repl", el).value, column: $("#c-col", el).value || null,
        doc: $("#c-doc", el) ? $("#c-doc", el).value || null : null });
      ui.corrOpen = true;
      const added = view.rules[view.rules.length - 1];
      await vAfterChange(env, added && added.changed ? `Sostituzione aggiunta: ${plural(added.changed, "cella cambiata", "celle cambiate")}.`
        : "Sostituzione aggiunta, ma per ora non cambia nessuna cella.");
    });
  });
  $$("[data-cdel]", el).forEach(b => b.addEventListener("click", () => busy(b, async () => {
    await api("DELETE", `/api/projects/${enc(ctx.pid)}/correzioni/${enc(b.dataset.cdel)}`);
    ui.corrOpen = true;
    await vAfterChange(env, "Correzione tolta.");
  })));
}
