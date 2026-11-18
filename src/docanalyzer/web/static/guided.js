/* Creazione di un progetto, sempre a partire dalla scheda di un catalogo.
 *
 * Schermate (indirizzo dopo il #):
 *   #/guidato/nuovo/<doc>   la Tabella (compilata a mano) e la ricerca dei cataloghi simili
 *   #/guidato/<id>          report di Gemini: catalogo di partenza, candidati, crea il progetto
 * Nella scheda del catalogo c'è il pannello con il pulsante e le ricerche precedenti (renderGuidedPanel).
 *
 * Usa le utilità di app.js, library.js e settings.js; viene caricato prima, le funzioni si chiamano dopo l'avvio.
 */
"use strict";

const guidedDate = iso => String(iso || "").replace("T", " ").slice(0, 16);

/** Caselle per scegliere le sezioni (collezioni) di un PDF da indicizzare. */
function sectionsPicker(docId, collections, checked) {
  if (!collections.length) return `<p class="muted small">Nessuna collezione nella scheda: si indicizzerà tutto il PDF
    (le pagine si possono cambiare nel progetto, al passo ②).</p>`;
  return `<div class="coll-pick">${[...collections].sort((x, y) => (y.tag === "dati") - (x.tag === "dati") || x.start - y.start).map(c => `
    <label class="row check">
      <input type="checkbox" data-sec="${esc(docId)}" value="${esc(c.id)}" ${checked.includes(c.id) ? "checked" : ""}>
      ${pageTagChip(c.tag, c.label)} <span>${c.start === c.end ? `pagina ${c.start}` : `pagine ${c.start}-${c.end}`}</span>
      ${c.comment ? `<span class="muted small">— ${esc(c.comment)}</span>` : ""}</label>`).join("")}</div>`;
}

// ------------------------------------------------------------------ pannello nella scheda del catalogo
async function renderGuidedPanel(c) {
  const box = $("#guided-panel");
  if (!box) return;
  const runs = await api("GET", `/api/library/catalogs/${enc(c.id)}/guided`);
  if (!$("#guided-panel")) return;
  box.innerHTML = `
    <div class="row"><h3 class="m-0">Crea progetto</h3><span class="spacer"></span>
      <a class="linkbtn" href="#/guidato/nuovo/${enc(c.id)}">Crea progetto da questo catalogo…</a></div>
    ${helpBlock("card-project", "Scrivi la tabella che vuoi ottenere; Gemini può cercare i cataloghi simili.",
      `<p>Cosa rappresenta una riga e le colonne; poi, se vuoi, Gemini cerca tra i cataloghi analizzati della biblioteca
        quelli che possono produrre righe della stessa tabella.</p>`)}
    ${c.analyzed && c.guide ? "" : `<p class="note warn small">${c.analyzed ? "" : "Questo catalogo non è ancora analizzato. "}${c.guide
      ? "" : "Senza guida all'indicizzazione Gemini legge ogni pagina senza sapere com'è fatto il catalogo."}</p>`}
    ${runs.length ? `<details><summary class="small">Ricerche precedenti (${runs.length})</summary><ul class="small">
      ${runs.map(r => `<li><a href="#/guidato/${enc(r.id)}">${esc(guidedDate(r.created_at))}${r.name ? ` · ${esc(r.name)}` : ""}</a> ·
        ${r.status === "valida" ? `${r.candidates} candidat${r.candidates === 1 ? "o" : "i"}` : `<span class="badge error">non valida</span>`}
        ${r.project ? ` · progetto <a href="#/p/${enc(r.project.id)}">${esc(r.project.name)}</a>` : ""}</li>`).join("")}
      </ul></details>` : ""}`;
}

// ------------------------------------------------------------------ la Tabella e la ricerca
async function renderGuidedNew(docId) {
  const [c, info, overview] = await Promise.all([api("GET", `/api/library/catalogs/${enc(docId)}`),
    api("GET", "/api/library/guided-prompt"), api("GET", "/api/library/catalogs")]);
  const draftKey = `guided:${docId}`, instrKey = "guided-instructions";
  let draft = {};
  try { draft = JSON.parse(drafts.get(draftKey) || "{}"); } catch { draft = {}; }
  const columns = (draft.columns || []).map(x => ({ name: x.name || "", description: x.description || "", header: !!x.header,
                                                       key: !!x.key }));
  const analyzed = overview.catalogs.filter(x => x.id !== docId && x.analyzed).length;
  const notAnalyzed = overview.catalogs.filter(x => x.id !== docId && !x.analyzed).length;

  view.innerHTML = `
    <p class="small"><a href="#/biblioteca/c/${enc(docId)}">&larr; ${esc(c.title)}</a></p>
    <h1>Nuovo progetto da ${esc(c.title)}</h1>
    <p class="muted">Un progetto produce <strong>una tabella</strong> (un CSV) da uno o più cataloghi. Scrivi qui la
      tabella che vuoi: è tua, Gemini non la cambia. Potrai modificarla anche dopo, al passo ① del progetto.</p>
    <div id="job"></div>
    <div class="panel">
      <h3>La tabella</h3>
      <label for="g-name">Nome del progetto</label>
      <input type="text" id="g-name" placeholder="es. Ricambi motori diesel">
      <label for="g-desc">Descrizione <span class="muted small">(facoltativa: a cosa serve l'indice)</span></label>
      <textarea id="g-desc" rows="2" placeholder="es. trovare un ricambio partendo dal motore"></textarea>
      <label for="g-row">Cosa rappresenta una riga</label>
      <input type="text" id="g-row" placeholder="es. una riga per ogni codice ricambio di ogni motore">
      <label>Colonne <span class="muted small">(nell'ordine del CSV; in fondo le due che aggiunge sempre il programma)</span></label>
      <div id="g-cols"></div>
      <div class="row mt-xs"><button class="secondary small" id="g-add" type="button">+ Aggiungi colonna</button>
        ${c.fields.length ? `<span class="small muted">dai dati presenti:</span> ${c.fields.map(f =>
          `<button type="button" class="chip" data-gadd="${esc(f.name)}" data-gdesc="${esc(f.description)}">+ ${esc(f.name)}</button>`).join(" ")}` : ""}</div>
      <label for="g-instr-table">Altre indicazioni <span class="muted small">(facoltative, valgono per tutti i PDF)</span></label>
      <textarea id="g-instr-table" rows="2" placeholder="es. se manca il codice OEM lascia vuoto; codici senza spazi"></textarea>
    </div>
    <div class="panel">
      <h3>Cataloghi simili</h3>
      ${helpBlock("new-similar", `Gemini confronta la tabella con <strong>${analyzed} catalog${analyzed === 1
          ? "o analizzato" : "hi analizzati"}</strong> e dice quali possono produrre le stesse righe.`,
        `<p>Riceve la tabella, la scheda di <strong>${esc(c.title)}</strong> e quelle degli altri cataloghi analizzati
          (descrizione, dati presenti, collezioni: solo testo, niente PDF) e indica anche con quali pagine.${notAnalyzed
          ? ` ${notAnalyzed} catalog${notAnalyzed === 1 ? "o non analizzato è escluso" : "hi non analizzati sono esclusi"}.` : ""}</p>`)}
      <details><summary class="small">Indicazioni per Gemini (come valutare i cataloghi)</summary>
        <p class="hint">Il formato della risposta è fisso: lo aggiunge il programma dopo le tue indicazioni e prevale su
          qualsiasi richiesta diversa; se la risposta non lo rispetta è scartata come <em>non valida</em>.</p>
        <textarea id="g-instr" rows="7"></textarea>
        <div class="row">
          <button class="secondary small" id="g-save-default" type="button">Salva come mio predefinito</button>
          <button class="secondary small" id="g-reset" type="button">Ripristina quello di fabbrica</button>
          <span class="hint" id="g-state"></span>
        </div></details>
      <div class="row mt-m">
        <button class="secondary" id="g-direct" type="button">Crea il progetto solo con questo catalogo</button>
        <span class="spacer"></span>
        <button class="secondary" id="g-preview" type="button">Vedi il prompt</button>
        <button class="gemini" id="g-send" type="button">Cerca i cataloghi simili</button></div>
    </div>`;

  const name = $("#g-name"), desc = $("#g-desc"), row = $("#g-row"), tinstr = $("#g-instr-table"), instr = $("#g-instr");
  name.value = draft.name || c.title; desc.value = draft.description || ""; row.value = draft.row || "";
  tinstr.value = draft.instructions || "";
  instr.value = drafts.get(instrKey) || info.effective;
  const save = () => drafts.set(draftKey, JSON.stringify({ name: name.value, description: desc.value, row: row.value,
                                                           instructions: tinstr.value, columns }));
  const editor = columnsEditor($("#g-cols"), columns, { onChange: save });
  const body = () => ({ name: name.value, description: desc.value, row: row.value, instructions: tinstr.value,
                        columns: editor.get(), gemini_instructions: instr.value });
  const check = () => {
    const problem = !name.value.trim() ? "Dai un nome al progetto." : tableProblem(row.value, editor.get());
    if (problem) toast(problem);
    return !problem;
  };
  const state = () => {
    $("#g-state").textContent = instr.value.trim() === (info.custom || info.factory).trim()
      ? (info.custom ? "Indicazioni: il tuo predefinito." : "Indicazioni: quelle di fabbrica.")
      : "Indicazioni modificate (valgono per questo invio).";
  };
  [name, desc, row, tinstr].forEach(el => el.addEventListener("input", save));
  instr.addEventListener("input", () => { drafts.set(instrKey, instr.value); state(); });
  $("#g-add").addEventListener("click", () => editor.add());
  $$("[data-gadd]").forEach(b => b.addEventListener("click", () => editor.add(b.dataset.gadd, b.dataset.gdesc)));
  $("#g-save-default").addEventListener("click", e => busy(e.target, async () => {
    Object.assign(info, await api("PUT", "/api/library/guided-prompt", { text: instr.value }));
    toast("Indicazioni salvate come tuo predefinito."); state();
  }));
  $("#g-reset").addEventListener("click", async e => {
    const ok = await confirmDialog({ title: "Ripristinare le indicazioni di fabbrica?", ok: "Ripristina",
      html: "<p>Il tuo predefinito personale (se c'è) viene cancellato e la casella torna al testo originale.</p>" });
    if (!ok) return;
    await busy(e.target, async () => {
      Object.assign(info, await api("PUT", "/api/library/guided-prompt", { text: "" }));
      instr.value = info.factory; drafts.clear(instrKey); state();
    });
  });
  $("#g-preview").addEventListener("click", e => {
    if (!check()) return;
    return busy(e.target, async () => {
      const p = await api("POST", `/api/library/catalogs/${enc(docId)}/guided/preview`, body());
      showText("Prompt per Gemini", p.prompt, `${p.candidates} cataloghi analizzati confrontati.`);
    });
  });
  $("#g-direct").addEventListener("click", async e => {
    if (!check()) return;
    const ok = await confirmDialog({ title: "Creare il progetto?", ok: "Crea progetto", html: `
      <p>Progetto <strong>${esc(name.value.trim())}</strong> con il solo <strong>${esc(c.title)}</strong>: le sue
        pagine <em>dati</em> e la sua guida all'indicizzazione vengono copiate nel progetto. Altri PDF si possono
        aggiungere dopo, al passo ②.</p>` });
    if (!ok) return;
    await busy(e.target, async () => {
      const r = await api("POST", `/api/library/catalogs/${enc(docId)}/guided/direct`, body());
      drafts.clear(draftKey);
      toast("Progetto creato.");
      location.hash = `#/p/${enc(r.project.id)}`;
    });
  });
  const done = j => { if (jobSucceeded(j)) location.hash = `#/guidato/${enc(j.result.run_id)}`; };
  $("#g-send").addEventListener("click", async e => {
    if (!check()) return;
    const p = await busy(e.target, () => api("POST", `/api/library/catalogs/${enc(docId)}/guided/preview`, body()));
    if (!p) return;
    const ok = await confirmDialog({ title: "Cercare i cataloghi simili con Gemini?", ok: "Invia a Gemini", html: `
      <p><strong>1 richiesta</strong> a Gemini con la tabella, la scheda di <strong>${esc(c.title)}</strong> e
        quelle di <strong>${p.candidates === 1 ? "1 catalogo analizzato" : `${p.candidates} cataloghi analizzati`}</strong> (solo testo, circa ${Math.max(1, Math.round(p.chars / 1000))} mila caratteri).</p>
      ${p.candidates > 150 ? `<p class="note warn">Sono molti cataloghi: la richiesta è grande e può richiedere qualche minuto.
        Se Gemini la rifiuta, l'errore verrà mostrato.</p>` : ""}
      <p class="hint">La risposta diventa un report: niente viene creato finché non lo decidi tu.</p>` });
    if (!ok) return;
    await busy(e.target, async () => {
      const job = await api("POST", `/api/library/catalogs/${enc(docId)}/guided`, body());
      watchJob($("#job"), job, done);
      $("#job").scrollIntoView({ block: "start", behavior: "smooth" });
    });
  });

  state();
  const running = await api("GET", `/api/library/catalogs/${enc(docId)}/guided-job`);
  if (running && running.status === "in_corso") watchJob($("#job"), running, done);
}

// ------------------------------------------------------------------ report
async function renderGuidedReport(runId) {
  const run = await api("GET", `/api/library/guided/${enc(runId)}`);
  const cat = id => run.catalogs[id] || { id, title: id, missing: true, collections: [], data: [] };
  const seed = cat(run.seed);
  const req = run.request;
  const head = `
    <p class="small"><a href="#/biblioteca/c/${enc(run.seed)}">&larr; ${esc(seed.title)}</a></p>
    <h1>Cataloghi simili a ${esc(seed.title)}</h1>
    <p class="muted small">${esc(guidedDate(run.created_at))} · ${run.candidates.length === 1 ? "1 catalogo analizzato confrontato"
      : `${run.candidates.length} cataloghi analizzati confrontati`}</p>`;
  if (run.status !== "valida") {
    view.innerHTML = `${head}
      <div class="panel note error"><strong>Risposta non valida</strong>: Gemini non ha rispettato il formato richiesto,
        quindi il report non è stato usato. Puoi <a href="#/guidato/nuovo/${enc(run.seed)}">riprovare</a> (la tabella
        che avevi scritto è ancora lì).
        <ul class="small">${run.problems.map(p => `<li>${esc(p)}</li>`).join("")}</ul></div>
      <details class="panel"><summary>Risposta ricevuta</summary><pre>${esc(JSON.stringify(run.raw, null, 2))}</pre></details>`;
    return;
  }
  const r = run.result;
  const created = !!run.project;
  const dataIds = id => cat(id).collections.filter(x => x.tag === "dati").map(x => x.id);
  const covered = { [run.seed]: r.seed_covered };
  r.candidates.forEach(x => { covered[x.document] = x.covered; });
  const guideBadge = k => k.missing ? "" : k.has_guide ? `<span class="badge ok" title="Ha la guida all'indicizzazione">guida</span>`
    : `<span class="badge warn" title="Senza guida all'indicizzazione: analizzalo nella biblioteca">senza guida</span>`;

  view.innerHTML = `${head}
    ${created ? `<div class="note"><strong>Progetto creato:</strong> <a href="#/p/${enc(run.project.id)}">${esc(run.project.name)} →</a></div>` : ""}
    ${run.problems.length ? `<details class="note warn small"><summary>${run.problems.length} correzion${run.problems.length === 1 ? "e" : "i"} alla
      risposta di Gemini</summary><ul>${run.problems.map(p => `<li>${esc(p)}</li>`).join("")}</ul></details>` : ""}
    ${r.notes ? `<div class="panel proposal"><h4 class="mt-0">Osservazioni di Gemini</h4><blockquote>${esc(r.notes)}</blockquote></div>` : ""}
    <div class="panel">
      <h3>La tabella</h3>
      ${helpBlock("report-table", "Quella che hai scritto: si modifica nel progetto, al passo ①.",
        `<p>Accanto a ogni colonna: in quanti PDF scelti si ricava, secondo Gemini.</p>`)}
      <label for="r-name">Nome del progetto</label><input type="text" id="r-name">
      ${req.description ? `<p class="small"><strong>Descrizione:</strong> ${esc(req.description)}</p>` : ""}
      <p class="small"><strong>Ogni riga rappresenta:</strong> ${esc(req.row)}</p>
      <div id="r-cols"></div>
      ${req.instructions ? `<p class="small"><strong>Altre indicazioni:</strong> ${esc(req.instructions)}</p>` : ""}
    </div>
    <div class="panel">
      <h3>Catalogo di partenza: <a href="#/biblioteca/c/${enc(run.seed)}">${esc(seed.title)}</a> ${guideBadge(seed)}</h3>
      <p class="small">Colonne che si ricavano: ${r.seed_covered.length ? tagBadges(r.seed_covered) : "—"}
        ${r.seed_missing.length ? `<br>Non si ricavano: ${r.seed_missing.map(n => `<span class="badge warn">${esc(n)}</span>`).join(" ")}` : ""}</p>
      ${r.seed_notes ? `<p class="small muted">${esc(r.seed_notes)}</p>` : ""}
      <label>Pagine da indicizzare</label>
      ${sectionsPicker(run.seed, seed.collections, r.seed_collections.length ? r.seed_collections : dataIds(run.seed))}
    </div>
    <div class="panel">
      <h3>Cataloghi candidati (${r.candidates.length})</h3>
      ${r.candidates.length ? `<p class="hint">Spunta i cataloghi da mettere nel progetto e le loro sezioni da indicizzare
        (i <em>compatibili</em> sono già spuntati).</p>` + r.candidates.map(x => {
        const k = cat(x.document);
        return `<div class="panel cand list-item">
          <label class="row m-0">
            <input type="checkbox" data-cand="${esc(x.document)}" ${x.verdict === "compatibile" && !k.missing ? "checked" : ""} ${k.missing ? "disabled" : ""}>
            ${k.missing ? `${esc(x.document)} <span class="badge error">eliminato</span>`
              : `<a href="#/biblioteca/c/${enc(x.document)}">${esc(k.title)}</a>`}
            <span class="badge ${x.verdict === "compatibile" ? "ok" : "warn"}">${esc(x.verdict)}</span> ${guideBadge(k)}
            <span class="small muted">${esc(k.folder || "Biblioteca")}</span></label>
          <p class="small my-xs">${esc(x.reason)}</p>
          <p class="small my-xs">Colonne che si ricavano: ${x.covered.length ? tagBadges(x.covered) : "—"}</p>
          ${k.missing ? "" : `<details ${x.verdict === "compatibile" ? "open" : ""}><summary class="small">Pagine da indicizzare</summary>
            ${sectionsPicker(x.document, k.collections, x.collections.length ? x.collections : dataIds(x.document))}</details>`}
        </div>`;
      }).join("") : `<p class="muted">Gemini non ha trovato altri cataloghi adatti: puoi creare il progetto con il solo catalogo
        di partenza, e aggiungere PDF più avanti.</p>`}
    </div>
    <div class="row"><span class="spacer"></span>
      <button id="r-create" type="button" ${created ? "disabled" : ""}>Crea progetto</button></div>`;

  $("#r-name").value = req.name || seed.title;
  const included = () => [run.seed, ...$$("[data-cand]:checked").map(b => b.dataset.cand)];
  const badge = col => {
    const ids = included();
    const n = ids.filter(id => (covered[id] || []).some(x => normName(x) === normName(col.name))).length;
    const cls = n === ids.length ? "ok" : n ? "warn" : "";
    return `<span class="badge ${cls}" title="PDF scelti in cui si ricava, secondo Gemini">${n}/${ids.length}</span>`;
  };
  const editor = columnsEditor($("#r-cols"), req.columns.map(c => ({ ...c })), { badge, readonly: true });
  const updateButton = () => {
    $("#r-create").textContent = created ? "Progetto già creato" : `Crea progetto (${included().length} PDF)`;
    editor.redraw();
  };
  $$("[data-cand]").forEach(b => b.addEventListener("change", updateButton));
  updateButton();
  if (created) $$("#view input, #view textarea, #view select").forEach(el => { el.disabled = true; });

  $("#r-create").addEventListener("click", async e => {
    const ids = included();
    if (!$("#r-name").value.trim()) { toast("Dai un nome al progetto."); return; }
    const noGuide = ids.filter(id => !cat(id).has_guide);
    const ok = await confirmDialog({ title: "Creare il progetto?", ok: "Crea progetto", html: `
      <p>Progetto <strong>${esc($("#r-name").value.trim())}</strong> con ${ids.length} PDF:
        ${ids.map(id => esc(cat(id).title)).join(", ")}.</p>
      <p class="hint">Le sezioni spuntate diventano le pagine da indicizzare; la guida all'indicizzazione di ogni catalogo
        viene copiata nel progetto.</p>
      ${noGuide.length ? `<p class="note warn">Senza guida: ${noGuide.map(id => esc(cat(id).title)).join(", ")}. Puoi
        analizzarli nella biblioteca anche dopo e poi usare <em>Aggiorna dalla biblioteca</em> nel progetto.</p>` : ""}` });
    if (!ok) return;
    await busy(e.target, async () => {
      const r2 = await api("POST", `/api/library/guided/${enc(runId)}/project`, {
        name: $("#r-name").value,
        documents: ids.map(id => ({ id, collections: $$(`[data-sec="${CSS.escape(id)}"]:checked`).map(b => b.value) })),
      });
      drafts.clear(`guided:${run.seed}`);
      toast("Progetto creato: prosegui con il prossimo passo.");
      location.hash = `#/p/${enc(r2.project.id)}`;
    });
  });
}
