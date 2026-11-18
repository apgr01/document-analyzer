/* Interfaccia di docanalyzer: JavaScript semplice, senza librerie.
 *
 * La pipeline: BIBLIOTECA (cataloghi in cartelle, analisi con Gemini: scheda e guida
 * all'indicizzazione) → PROGETTO creato dalla scheda di un catalogo → 6 passi → CSV unico.
 *
 * Schermate (indirizzo dopo il #):
 *   #/                       elenco dei progetti (si creano dalla scheda di un catalogo)
 *   #/p/<id>                 il progetto, aperto sul prossimo passo da fare
 *   #/p/<id>/settings        ① Tabella: cosa vuoi ottenere (riga, colonne)
 *   #/p/<id>/docs            ② PDF e pagine: pagine da indicizzare, guide e note per PDF
 *   #/p/<id>/test            ③ Prova: poche pagine per catalogo, con le regole vere
 *   #/p/<id>/index           ④ indicizzazione di tutti i PDF
 *   #/p/<id>/verify          ⑤ Verifiche ed elaborazione: controlli, correzioni, pagine da rifare (verifiche.js)
 *   #/p/<id>/results         ⑥ CSV unico, anomalie, pagina di ricerca
 *   #/biblioteca...          biblioteca (library.js), #/guidato/... creazione del progetto (guided.js)
 *   #/stile                  variabili del tema e componenti, per chi crea un tema (stile.js)
 *
 * Regole di sicurezza per l'utente:
 *   - ogni azione che usa Gemini (pulsanti con la stellina) chiede conferma e dice quante
 *     richieste partiranno, quanto pesano e quanto dureranno; il tasto Invio non invia mai nulla;
 *   - nessun limite preventivo: se Gemini rifiuta una richiesta, l'errore viene mostrato;
 *   - i testi che scrivi restano bozze salvate nel browser finché non li salvi o li invii;
 *   - prima di inviare puoi vedere il prompt esatto;
 *   - modifiche manuali non salvate: conferma prima di cambiare pagina.
 */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const view = $("#view");
let pollTimer = null;

// ------------------------------------------------------------------ utilità
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const enc = encodeURIComponent;

async function api(method, url, body, isForm = false) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) options.body = body;
    else { options.body = JSON.stringify(body); options.headers["Content-Type"] = "application/json"; }
  }
  const response = await fetch(url, options);
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!response.ok) {
    const error = new Error((data && data.detail) || `Errore ${response.status}`);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

function toast(message, ms = 3500) {
  const t = $("#toast");
  t.textContent = message;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), ms);
}

function showError(error) {
  console.error(error);
  toast(error.message || String(error), 6000);
}

/** Dialogo di conferma: restituisce true se l'utente conferma. */
function confirmDialog({ title, html, ok = "Conferma", danger = false }) {
  const dialog = $("#confirm-dialog");
  $("#confirm-title").textContent = title;
  $("#confirm-body").innerHTML = html;
  const okButton = $("#confirm-ok");
  okButton.textContent = ok;
  okButton.className = danger ? "danger" : "";
  dialog.returnValue = "cancel";
  dialog.showModal();
  okButton.focus();
  return new Promise(resolve => dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true }));
}

function showText(title, text, note = "") {
  $("#text-title").textContent = title;
  $("#text-note").textContent = note;
  $("#text-body").textContent = text;
  $("#text-dialog").showModal();
}

function showPage(docId, page, title = "") {
  $("#image-title").textContent = `${title ? title + " — " : ""}pagina ${page}`;
  $("#image-body").src = `/api/documents/${enc(docId)}/page/${page}`;
  $("#image-pdf").href = `/api/documents/${enc(docId)}/pdf#page=${page}`;
  $("#image-dialog").showModal();
}

/** Esegue un'azione disabilitando il pulsante, per evitare doppi clic. */
async function busy(button, action) {
  if (button) button.disabled = true;
  try { return await action(); }
  catch (e) { showError(e); }
  finally { if (button) button.disabled = false; }
}

// Bozze salvate nel browser (obiettivo, correzioni): non si perdono ricaricando la pagina.
const drafts = {
  get: key => { try { return localStorage.getItem("docanalyzer:" + key) || ""; } catch { return ""; } },
  set: (key, value) => { try { localStorage.setItem("docanalyzer:" + key, value); } catch { /* ignorato */ } },
  clear: key => { try { localStorage.removeItem("docanalyzer:" + key); } catch { /* ignorato */ } },
};

/** "1-3, 5" -> [1,2,3,5]; lancia un errore con messaggio leggibile. */
function parsePages(text, total) {
  const result = new Set();
  for (const raw of String(text || "").split(",")) {
    const part = raw.trim();
    if (!part) continue;
    const m = part.match(/^(\d*)\s*-\s*(\d*)$/);
    let start, end;
    if (m) { start = m[1] ? +m[1] : 1; end = m[2] ? +m[2] : total; }
    else if (/^\d+$/.test(part)) { start = end = +part; }
    else throw new Error(`"${part}" non è valido (esempio: 1-4, 10, 38-41)`);
    if (start < 1 || end > total || start > end) throw new Error(`"${part}" è fuori dal documento (1-${total})`);
    for (let p = start; p <= end; p++) result.add(p);
  }
  return [...result].sort((a, b) => a - b);
}

function formatPages(pages) {
  const sorted = [...new Set(pages)].sort((a, b) => a - b);
  const parts = [];
  for (let i = 0; i < sorted.length; i++) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j] + 1) j++;
    parts.push(i === j ? `${sorted[i]}` : `${sorted[i]}-${sorted[j]}`);
    i = j;
  }
  return parts.join(", ");
}

/** Tabella; con pageColumn/fileColumn le righe aprono la pagina del PDF corrispondente. */
function table(columns, rows, { hide = [], pageColumn = null, fileColumn = null, files = {}, docId = null } = {}) {
  const cols = columns.filter(c => !hide.includes(c));
  const head = cols.map(c => `<th>${esc(c)}</th>`).join("");
  const body = rows.map(r => {
    const page = pageColumn ? r[pageColumn] : null;
    const doc = fileColumn ? files[r[fileColumn]] : docId;
    const attrs = page && doc ? ` class="clickable" data-doc="${esc(doc)}" data-page="${esc(page)}" title="Clic: mostra la pagina"` : "";
    return `<tr${attrs}>${cols.map(c => `<td>${esc(r[c])}</td>`).join("")}</tr>`;
  }).join("");
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function bindPageClicks(root, titles = {}) {
  $$("[data-page][data-doc]", root).forEach(el => el.addEventListener("click", e => {
    e.stopPropagation();
    showPage(el.dataset.doc, el.dataset.page, titles[el.dataset.doc] || "");
  }));
}

// ------------------------------------------------------------------ barra di stato
async function refreshStatus() {
  try {
    const s = await api("GET", "/api/status");
    const parts = [`modello ${esc(s.model)}`];
    if (s.simulated) parts.unshift(`<span class="sim">MODALITÀ SIMULATA</span>`);
    else if (!s.keys) parts.unshift(`<span class="bad">nessuna chiave API nel file .env</span>`);
    else parts.unshift(`${s.keys} chiav${s.keys === 1 ? "e" : "i"} API`);
    if (s.usage && s.usage.requests) parts.push(esc(s.usage.text));
    $("#status").innerHTML = parts.join(" · ");
  } catch { $("#status").textContent = "server non raggiungibile"; }
}

// ------------------------------------------------------------------ lavori in corso
function stopPolling() { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; } }

function elapsed(startedAt) {
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(startedAt)) / 1000));
  return seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}

/** Messaggi di servizio del lavoro (sovraccarico di Gemini, quote, rallentamenti), dal più recente. */
function jobEvents(events) {
  if (!events.length) return "";
  const latest = events[events.length - 1];
  const waiting = /sovraccarico|quota|rallento|errore temporaneo/i.test(latest.text);
  return `
    ${waiting ? `<div class="note warn small mt-m"><strong>${esc(latest.time)}</strong> ${esc(latest.text)}<br>
      <span class="muted">Il programma riprova da solo; puoi aspettare oppure premere <em>Ferma</em>.</span></div>` : ""}
    <details class="mt-s"><summary class="small">Messaggi (${events.length})</summary>
      <ul class="small muted my-2xs">${events.slice().reverse().map(e =>
        `<li><strong>${esc(e.time)}</strong> ${esc(e.text)}</li>`).join("")}</ul></details>`;
}

// ------------------------------------------------------------------ mini gioco durante l'attesa
// il gioco durante l'attesa è nascosto finché l'utente non lo apre ("Gioca mentre aspetti"); la scelta resta
const SNAKE_SHOWN_KEY = "docanalyzer:snake-shown";
let activeGame = null;

function snakeHidden() { try { return localStorage.getItem(SNAKE_SHOWN_KEY) !== "1"; } catch { return true; } }
function setSnakeHidden(v) { try { localStorage.setItem(SNAKE_SHOWN_KEY, v ? "0" : "1"); } catch { /* ignorato */ } }
function stopGame() { if (activeGame) { activeGame.destroy(); activeGame = null; } }
function jobSucceeded(j) { return j.status === "completato" && !(j.result && j.result.stopped_reason); }

/** Testi dell'animazione finale secondo il tipo di lavoro. */
function finaleTexts(j) {
  if (j.kind === "index") return {};                                   // quelli predefiniti
  if (j.kind === "guided") return { title: "Report pronto!", text: "I cataloghi simili ti aspettano ✦",
                                    labels: ["cataloghi", "sezioni", "progetto"] };
  if (j.kind === "analysis") return { title: "Analisi pronta!", text: "Scheda e guida da rivedere ✦",
                                      labels: ["descrizione", "pagine", "guida"] };
  if (j.kind === "guide") return { title: "Guida pronta!", text: "La nuova guida ti aspetta ✦",
                                   labels: ["struttura", "convenzioni", "guida"] };
  if (j.kind === "test") return { title: "Prova finita!", text: "Le prime righe sono pronte ✦",
                                  labels: ["righe", "pagine", "prova"] };
  return { title: "Gemini ha finito!", text: "Risultati appena sfornati ✦", labels: ["dati", "pagine", "righe"] };
}

/** Carica snake.js se la pagina non l'ha già fatto (es. index.html vecchia nella cache). */
function loadSnake() {
  if (window.GeminiSnake) return Promise.resolve(true);
  return new Promise(resolve => {
    const script = document.createElement("script");
    script.src = "/static/snake.js";
    script.onload = () => resolve(!!window.GeminiSnake);
    script.onerror = () => resolve(false);
    document.head.appendChild(script);
  });
}

/** Mostra un lavoro in corso e lo segue fino alla fine; poi chiama onDone(job).
 *  Durante l'attesa c'è Gemini Snake (si può nascondere). Se il lavoro finisce bene e il
 *  gioco è in corso (o finale=true, per l'indicizzazione), il serpente "produce" i risultati
 *  ed esplode: onDone viene chiamato solo alla fine dell'animazione. */
function watchJob(container, job, onDone, { finale = false } = {}) {
  stopPolling();
  stopGame();
  // struttura fissa: lo stato si aggiorna ogni secondo, il gioco resta com'è
  container.innerHTML = `
    <div class="panel">
      <div class="row"><strong id="job-label"></strong><span class="spacer"></span>
        <button class="secondary" id="job-game-toggle" type="button"></button>
        <button class="secondary" id="job-cancel" type="button">Ferma</button></div>
      <div id="job-status"></div>
      <div id="job-game"></div>
    </div>`;
  const status = $("#job-status", container), gameBox = $("#job-game", container);
  const toggle = $("#job-game-toggle", container);
  let current = job;

  const showGame = visible => {
    gameBox.hidden = !visible;
    toggle.textContent = visible ? "Nascondi il gioco" : "Gioca mentre aspetti";
    if (visible && !activeGame) {
      loadSnake().then(ok => {
        if (!ok || activeGame || gameBox.hidden || !gameBox.isConnected) return;
        activeGame = GeminiSnake.mount(gameBox);
        activeGame.setProgress(current.done, current.total);
      });
    }
  };
  toggle.addEventListener("click", () => { setSnakeHidden(!gameBox.hidden); showGame(gameBox.hidden); });
  showGame(!snakeHidden());

  $("#job-cancel", container).addEventListener("click", async () => {
    const ok = await confirmDialog({ title: "Fermare l'operazione?",
      html: `<p>Le attese in corso (sovraccarico di Gemini, quote) si interrompono subito; le richieste già
             inviate terminano, le altre non partono. Il lavoro fatto resta salvato e si può riprendere.</p>`,
      ok: "Ferma", danger: true });
    if (ok) await busy(null, () => api("POST", `/api/jobs/${current.id}/cancel`));
  });

  const render = j => {
    current = j;
    const pct = j.total ? Math.round(100 * j.done / j.total) : 0;
    const messagesOpen = !!(status.querySelector("details") || {}).open;   // si aggiorna ogni secondo
    $("#job-label", container).textContent = j.label;
    $("#job-cancel", container).disabled = !!j.cancel_requested;
    status.innerHTML = `
      <p class="muted small">${esc(j.message || "")}${j.total ? ` — ${j.done}/${j.total} pagine` : ""}
        · ${elapsed(j.started_at)}</p>
      <div class="progress ${j.total ? "" : "indeterminate"}"><div style="width:${pct}%"></div></div>
      ${jobEvents(j.events || [])}`;
    const details = status.querySelector("details");
    if (details) details.open = messagesOpen;
    if (activeGame) activeGame.setProgress(j.done, j.total);
  };
  const end = j => {
    container.innerHTML = "";
    stopGame();
    refreshStatus();
    if (j.status === "errore") toast(`Operazione non riuscita: ${j.error}`, 8000);
    else if (j.status === "annullato") toast("Operazione fermata. Il lavoro fatto è salvato.");
    onDone(j);
  };
  const tick = async () => {
    try {
      const j = await api("GET", `/api/jobs/${job.id}`);
      if (j.status === "in_corso") { render(j); pollTimer = setTimeout(tick, 1000); return; }
      const game = activeGame;
      if (jobSucceeded(j) && game && !gameBox.hidden && game.state !== "done" && (finale || game.playing)) {
        render(j);
        $("#job-cancel", container).disabled = true;
        toggle.disabled = true;
        game.finish(() => { if (activeGame === game) end(j); }, finaleTexts(j));
      } else end(j);
    } catch (e) { showError(e); }
  };
  render(job);
  pollTimer = setTimeout(tick, 700);
}

// ------------------------------------------------------------------ modifiche non salvate
function hasUnsavedEdits() {
  return $$("textarea[data-original]").some(t => t.value !== t.dataset.original);
}
window.addEventListener("beforeunload", e => { if (hasUnsavedEdits()) { e.preventDefault(); e.returnValue = ""; } });
let lastHash = location.hash;

// ------------------------------------------------------------------ router
async function route() {
  if (hasUnsavedEdits() && !window.confirm("Ci sono modifiche non salvate (descrizioni, guida o note). Uscire e perderle?")) {
    history.replaceState(null, "", lastHash);
    return;
  }
  lastHash = location.hash;
  stopPolling();
  stopGame();
  const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  try {
    $$(".nav a").forEach(a => a.classList.toggle("active",
      a.dataset.nav === (["biblioteca", "guidato"].includes(parts[0]) ? "library" : "projects")));
    if (parts[0] === "p" && parts[1]) await renderProject(parts[1], parts[2] || null);
    else if (parts[0] === "biblioteca" && parts[1] === "c" && parts[2]) await renderCatalog(parts[2]);
    else if (parts[0] === "stile") await renderStyleGuide();
    else if (parts[0] === "biblioteca") await renderLibrary(parts.slice(1).join("/"));
    else if (parts[0] === "guidato" && parts[1] === "nuovo" && parts[2]) await renderGuidedNew(parts[2]);
    else if (parts[0] === "guidato" && parts[1]) await renderGuidedReport(parts[1]);
    else await renderHome();
  } catch (e) {
    view.innerHTML = `<div class="panel note error">${esc(e.message)}</div><p><a href="#/">Torna all'elenco</a></p>`;
  }
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------------ HOME
async function renderHome() {
  const projects = await api("GET", "/api/projects");
  view.innerHTML = `
    <div class="row"><h1>Progetti di indicizzazione</h1><span class="spacer"></span>
      <button id="new-project" type="button">Nuovo progetto…</button></div>
    ${helpBlock("home", "Un progetto produce un'unica tabella (un CSV) da uno o più cataloghi della biblioteca.",
      `<p>Si parte da un catalogo: scrivi la tabella che vuoi e, se vuoi, Gemini cerca nella biblioteca i cataloghi
        simili. Conviene partire da un catalogo già analizzato: la scheda e la guida all'indicizzazione rendono più
        precisa l'estrazione e permettono di trovare i cataloghi simili.</p>`)}
    <div class="panel">
      <h3>Progetti</h3>
      ${projects.length ? `<div class="table-wrap"><table>
        <thead><tr><th>Progetto</th><th>PDF</th><th>Passi</th><th>Prossimo passo</th><th>Indicizzate</th><th></th></tr></thead>
        <tbody>${projects.map(p => `<tr class="clickable" data-open="${esc(p.id)}">
            <td><strong>${esc(p.name)}</strong>${p.job ? `<br><span class="badge warn">${esc(p.job.label)}…</span>` : ""}</td>
            <td>${p.documents.length}</td>
            <td class="nowrap">${PROJECT_STEPS.map(([k, , num]) => stepDot(num, p.steps[k])).join("")}</td>
            <td class="small">${esc(p.next.text)}</td>
            <td>${p.progress ? `${p.progress.done}/${p.progress.to_index}` : "—"}</td>
            <td><button class="secondary small" data-delete="${esc(p.id)}" type="button">Elimina</button></td></tr>`).join("")}
        </tbody></table></div>` : `<p class="muted">Nessun progetto.</p>`}
    </div>
    <p class="page-footer small muted"><a href="#/stile">Stile dell'interfaccia</a> · temi e componenti</p>`;

  $("#new-project").addEventListener("click", e => busy(e.target, async () => {
    const [id] = await pickCatalogs({ title: "Nuovo progetto: catalogo di partenza", ok: "Continua", multiple: false,
      hint: "Dopo scrivi la tabella che vuoi ottenere; potrai aggiungere altri cataloghi in seguito." });
    if (id) location.hash = `#/guidato/nuovo/${enc(id)}`;
  }));
  $$("[data-open]").forEach(tr => tr.addEventListener("click", e => {
    if (e.target.closest("button")) return;
    location.hash = `#/p/${enc(tr.dataset.open)}`;
  }));
  $$("[data-delete]").forEach(b => b.addEventListener("click", async () => {
    const p = projects.find(x => x.id === b.dataset.delete);
    const ok = await confirmDialog({ title: "Eliminare il progetto?", danger: true, ok: "Elimina",
      html: `<p>Verrà eliminato il progetto <strong>${esc(p.name)}</strong> con la sua tabella e la prova. I suoi
             ${p.documents.length} PDF restano nella biblioteca, con le schede e i CSV già esportati.</p>` });
    if (ok) await busy(b, async () => { await api("DELETE", `/api/projects/${enc(p.id)}`); route(); });
  }));
}

// ------------------------------------------------------------------ PROGETTO
async function renderProject(pid, tab) {
  const project = await api("GET", `/api/projects/${enc(pid)}`);
  tab = tab || project.next.tab;                       // senza scheda: si apre il prossimo passo
  view.innerHTML = `
    <p class="small"><a href="#/">&larr; Progetti</a></p>
    <h1>${esc(project.name)}</h1>
    <p class="muted small">${project.documents.length} PDF · ${project.page_count} pagine ·
      ${project.fields.length} colonne${project.row ? ` · Tabella: ${esc(project.row)}` : ""}</p>
    <nav class="tabs steps-nav">${stepsNav(project, tab)}</nav>
    <div class="next-step row">${nextStep(project, tab)}</div>
    <div id="job"></div>
    <div id="tab"></div>`;
  const ctx = {
    project, pid, jobBox: $("#job"), box: $("#tab"),
    titles: Object.fromEntries(project.documents.map(d => [d.id, d.title])),
    files: Object.fromEntries(project.documents.map(d => [d.source_filename, d.id])),
  };
  ctx.refresh = () => renderProject(pid, tab);
  // aggiorna solo i passi e il prossimo passo (senza ridisegnare la scheda, che resta dov'è)
  ctx.updateSteps = async () => {
    try {
      const p = await api("GET", `/api/projects/${enc(pid)}`);
      const nav = $(".steps-nav"), bar = $(".next-step");
      if (nav && bar) { nav.innerHTML = stepsNav(p, tab); bar.innerHTML = nextStep(p, tab); }
    } catch { /* non essenziale */ }
  };

  const job = await api("GET", `/api/projects/${enc(pid)}/job`);
  if (job && job.status === "in_corso") {
    ctx.box.innerHTML = `<p class="muted">Attendi la fine dell'operazione in corso…</p>`;
    // pagina riaperta durante un lavoro: a indicizzazione finita si va alle verifiche, a prova finita alla prova
    watchJob(ctx.jobBox, job, j => {
      if (j.kind === "index" && jobSucceeded(j) && tab !== "verify") location.hash = `#/p/${enc(pid)}/verify`;
      else if (j.kind === "test") location.hash = `#/p/${enc(pid)}/test`;
      else ctx.refresh();
    }, { finale: job.kind === "index" });
    return;
  }
  if (!project.has_table && tab !== "settings" && tab !== "docs") {
    ctx.box.innerHTML = `<div class="panel note">Prima completa la <a href="#/p/${enc(pid)}/settings">tabella</a>
      (passo ①): cosa rappresenta una riga e le colonne.</div>`;
    return;
  }
  if (tab === "test") await renderTest(ctx);
  else if (tab === "index") await renderIndex(ctx);
  else if (tab === "verify") await renderVerify(ctx);
  else if (tab === "results") await renderResults(ctx);
  else if (tab === "docs") renderDocs(ctx);
  else await renderSettings(ctx);
}

// ------------------------------------------------------------------ i 6 passi del progetto
const PROJECT_STEPS = [["settings", "Tabella", "①"], ["docs", "PDF e pagine", "②"], ["test", "Prova", "③"],
                       ["index", "Indicizzazione", "④"], ["verify", "Verifiche", "⑤"], ["results", "Risultati", "⑥"]];
const STEP_STYLE = { "fatto": "ok", "in corso": "run", "da rivedere": "warn", "da fare": "todo", "facoltativo": "opt" };

function stepsNav(project, tab) {
  return PROJECT_STEPS.map(([k, label, num]) => {
    const st = project.steps[k];
    return `<a href="#/p/${enc(project.id)}/${k}" class="${k === tab ? "active" : ""}" title="${esc(st.state)}${st.note ? ": " + esc(st.note) : ""}">
      ${stepDot(num, st)} ${label}${st.note ? `<small>${esc(st.note)}</small>` : ""}</a>`;
  }).join("");
}

function nextStep(project, tab) {
  const next = project.next;
  return `<span><strong>Prossimo passo:</strong> ${esc(next.text)}</span><span class="spacer"></span>
    ${next.tab !== tab ? `<a class="linkbtn small" href="#/p/${enc(project.id)}/${next.tab}">Vai &rarr;</a>` : ""}`;
}

function stepDot(num, step) {
  const cls = STEP_STYLE[step.state] || "todo";
  const mark = { ok: "✓", run: "●", warn: "!", todo: "", opt: "" }[cls];
  return `<span class="step-dot ${cls}" title="${esc(step.state)}">${num}${mark ? `<b>${mark}</b>` : ""}</span>`;
}

/** "1 pagina", "3 pagine". */
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** Durata leggibile di una stima in secondi. */
function durationText(seconds) {
  if (seconds < 90) return `circa ${Math.max(10, Math.round(seconds / 10) * 10)} secondi`;
  return `circa ${Math.round(seconds / 60)} minuti`;
}

// ------------------------------------------------------------------ ② PDF E PAGINE
function guideState(d, change) {
  if (change && change.guide_changed) return `<span class="badge warn" title="La guida nella biblioteca è diversa da quella copiata nel progetto">guida cambiata nella biblioteca</span>`;
  if (d.settings.guide) return `<span class="badge ok">guida</span>`;
  return `<span class="badge warn" title="Senza guida Gemini legge ogni pagina senza sapere com'è fatto il catalogo">senza guida</span>`;
}

function renderDocs(ctx) {
  const { project, pid, box } = ctx;
  const changes = project.library_changes || [];
  const changeOf = id => changes.find(c => c.doc_id === id);
  box.innerHTML = `
    ${changes.length ? `<div class="panel note warn">
      <strong>La biblioteca è cambiata</strong> per ${changes.length} PDF: pagine o guida nel progetto non coincidono più
      con la scheda.
      <ul class="small">${changes.map(c => `<li><strong>${esc(c.title)}</strong>:
        ${c.pages_changed ? `pagine nel progetto ${esc(c.pages || "—")}, nella biblioteca ${c.library_pages ? esc(c.library_pages) : "<em>nessuna</em>"}
          ${c.missing ? ` (${c.missing} collezion${c.missing === 1 ? "e eliminata" : "i eliminate"})` : ""}` : ""}
        ${c.pages_changed && c.guide_changed ? " · " : ""}
        ${c.guide_changed ? (c.library_has_guide ? "la guida è cambiata" : "la guida è stata tolta dalla scheda") : ""}</li>`).join("")}</ul>
      <div class="row"><span class="hint">Pagine e guida fanno parte delle regole: aggiornandole, i PDF già indicizzati
        andranno rifatti.</span><span class="spacer"></span><button id="lib-update" type="button">Aggiorna dalla biblioteca</button></div>
    </div>` : ""}
    <div class="panel">
      <div class="row"><h3 class="m-0">PDF del progetto</h3><span class="spacer"></span>
        <button class="secondary" id="from-library" type="button">Aggiungi PDF dalla biblioteca…</button></div>
      ${helpBlock("docs", "Per ogni PDF: pagine da indicizzare, guida e note.",
        `<p>Le <strong>pagine da indicizzare</strong> sono di solito le collezioni <em>dati</em> della scheda. La
          <strong>guida all'indicizzazione</strong> è copiata dalla biblioteca: si cambia lì e poi si aggiorna qui. Le
          <strong>note</strong> sono istruzioni in più valide solo per quel PDF. Le colonne restano le stesse per tutti.</p>`)}
      ${project.documents.map(d => `
        <div class="panel list-item">
          <div class="row">
            <img src="/api/documents/${enc(d.id)}/thumb/1" alt="" class="doc-thumb" data-doc="${esc(d.id)}" data-page="1">
            <div class="grow"><a href="#/biblioteca/c/${enc(d.id)}" title="Apri la scheda nella biblioteca"><strong>${esc(d.title)}</strong></a>
              <br><span class="small muted">${esc(d.source_filename)} · ${d.page_count} pagine · da indicizzare ${d.to_index}
              ${d.done ? ` · indicizzate ${d.done}/${d.to_index}` : ""}${d.failed ? ` · <span class="badge error">${d.failed} fallite</span>` : ""}</span>
              ${d.library && d.library.data.length ? `<br><span class="small muted">Dati presenti:</span> ${tagBadges(d.library.data)}` : ""}</div>
            <span class="spacer"></span>
            ${guideState(d, changeOf(d.id))}
            ${d.settings.notes ? '<span class="badge">note</span>' : ""}${d.settings.pages ? `<span class="badge" title="${d.settings.collections.length ? "Dalle collezioni della biblioteca" : "Scritte a mano"}">pagine ${esc(d.settings.pages)}${d.settings.collections.length ? " 📚" : ""}</span>` : `<span class="badge warn" title="Nessuna pagina scelta: si indicizza tutto il PDF">tutte le pagine</span>`}
            ${d.settings.guide ? `<button class="secondary" data-guide="${esc(d.id)}" type="button">Guida</button>` : ""}
            <button class="secondary" data-edit="${esc(d.id)}" type="button">Note e pagine</button>
            <button class="secondary" data-remove="${esc(d.id)}" type="button" ${project.documents.length === 1 ? "disabled title=\"È l'unico PDF del progetto\"" : ""}>Togli</button>
          </div>
          <div id="edit-${esc(d.id)}" hidden>
            <label>Note per questo PDF</label>
            <textarea data-notes="${esc(d.id)}" rows="3" placeholder="Istruzioni in più valide solo per questo PDF (es. la versione è sotto il nome del motore)"></textarea>
            <label>Pagine da indicizzare</label>
            ${d.library && d.library.collections.length ? `<p class="hint">Spunta le collezioni della
              <a href="#/biblioteca/c/${enc(d.id)}">scheda</a> da indicizzare (di solito quelle <em>Dati</em>): le loro pagine vengono
              copiate nel progetto.</p>
            <div class="coll-pick">${[...d.library.collections].sort((x, y) => (y.tag === "dati") - (x.tag === "dati") || x.start - y.start).map(c => `
              <label class="row check">
                <input type="checkbox" data-coll="${esc(d.id)}" value="${esc(c.id)}" data-start="${c.start}" data-end="${c.end}"
                  ${d.settings.collections.includes(c.id) ? "checked" : ""}>
                ${pageTagChip(c.tag, c.label)} <span>${c.start === c.end ? `pagina ${c.start}` : `pagine ${c.start}-${c.end}`}</span>
                ${c.comment ? `<span class="muted small">— ${esc(c.comment)}</span>` : ""}</label>`).join("")}</div>
            <label class="small fw-normal">…oppure scrivile a mano <span class="muted">(vuoto = tutto il PDF)</span></label>`
            : `<p class="hint">La <a href="#/biblioteca/c/${enc(d.id)}">scheda</a> non ha collezioni: scrivi le pagine a mano (vuoto = tutto il PDF).</p>`}
            <input type="text" data-pages="${esc(d.id)}" placeholder="es. 5-">
            <div class="row mt-s"><span class="spacer"></span>
              <button data-save="${esc(d.id)}" type="button">Salva</button></div>
          </div>
        </div>`).join("")}
    </div>`;
  bindPageClicks(box, ctx.titles);
  if ($("#lib-update")) $("#lib-update").addEventListener("click", async e => {
    const indexed = changes.filter(c => (project.documents.find(d => d.id === c.doc_id) || {}).done);
    const ok = await confirmDialog({ title: "Aggiornare dalla biblioteca?", ok: "Aggiorna", html: `
      <p>Pagine e guida di ${changes.map(c => `<strong>${esc(c.title)}</strong>`).join(", ")} verranno ricopiate dalla
        biblioteca (le collezioni eliminate vengono tolte).</p>
      ${indexed.length ? `<p class="note warn">Già indicizzati, andranno rifatti: ${indexed.map(c => esc(c.title)).join(", ")}
        (solo questi PDF, al passo ④).</p>` : ""}` });
    if (!ok) return;
    await busy(e.target, async () => {
      const r = await api("POST", `/api/projects/${enc(pid)}/library-update`, { docs: changes.map(c => c.doc_id) });
      toast(`Aggiornati ${r.updated.length} PDF.`);
      ctx.refresh();
    });
  });
  $("#from-library").addEventListener("click", async () => {
    const ids = await pickFromLibrary(project.documents.map(d => d.id));
    if (!ids.length) return;
    await busy(null, async () => {
      const r = await api("POST", `/api/projects/${enc(pid)}/documents/from-library`, { ids });
      toast(`${r.added.length} PDF aggiunti dalla biblioteca, con pagine dati e guida.`);
      ctx.refresh();
    });
  });
  $$("[data-guide]").forEach(b => b.addEventListener("click", () => {
    const d = project.documents.find(x => x.id === b.dataset.guide);
    showText(`Guida all'indicizzazione — ${d.title}`, d.settings.guide,
      "La copia usata dal progetto. Si modifica nella scheda della biblioteca, poi qui con Aggiorna dalla biblioteca.");
  }));
  for (const d of project.documents) {
    const area = $(`[data-notes="${CSS.escape(d.id)}"]`), pages = $(`[data-pages="${CSS.escape(d.id)}"]`);
    area.value = d.settings.notes || "";
    area.dataset.original = area.value;
    pages.value = d.settings.pages || "";
    const boxes = $$(`[data-coll="${CSS.escape(d.id)}"]`);
    const chosen = () => boxes.filter(b => b.checked);
    // spuntare le collezioni scrive le pagine; scriverle a mano toglie le spunte
    boxes.forEach(b => b.addEventListener("change", () => {
      const list = [];
      chosen().forEach(x => { for (let p = +x.dataset.start; p <= +x.dataset.end; p++) list.push(p); });
      pages.value = formatPages(list);
    }));
    pages.addEventListener("input", () => boxes.forEach(b => { b.checked = false; }));
    $(`[data-edit="${CSS.escape(d.id)}"]`).addEventListener("click", () => {
      const panel = $(`#edit-${CSS.escape(d.id)}`);
      panel.hidden = !panel.hidden;
    });
    $(`[data-save="${CSS.escape(d.id)}"]`).addEventListener("click", e => busy(e.target, async () => {
      const collections = chosen().map(b => b.value);
      if (!collections.length && pages.value.trim()) parsePages(pages.value, d.page_count);
      await api("PUT", `/api/projects/${enc(pid)}/documents/${enc(d.id)}/settings`,
        { notes: area.value, pages: pages.value, collections });
      area.dataset.original = area.value;
      toast(d.done ? "Salvato. Se note o pagine sono cambiate, questo PDF andrà reindicizzato (passo ④)." : "Salvato.");
      ctx.refresh();
    }));
    $(`[data-remove="${CSS.escape(d.id)}"]`).addEventListener("click", async e => {
      const ok = await confirmDialog({ title: "Togliere il PDF dal progetto?", danger: true, ok: "Togli",
        html: `<p><strong>${esc(d.title)}</strong> verrà tolto dal progetto. Il PDF resta nella biblioteca.</p>` });
      if (ok) await busy(e.target, async () => { await api("DELETE", `/api/projects/${enc(pid)}/documents/${enc(d.id)}`); ctx.refresh(); });
    });
  }
}

// ------------------------------------------------------------------ come inviare le pagine (③ e ④)
/** Richieste a Gemini per mandare queste pagine di un PDF, secondo la modalità del progetto. */
function requestsFor(project, pages) {
  if (!pages) return 0;
  if (project.send_mode !== "insieme") return pages;
  return project.pages_per_request ? Math.ceil(pages / project.pages_per_request) : 1;
}

function sendModeText(project) {
  if (project.send_mode !== "insieme") return "una pagina per richiesta";
  return project.pages_per_request
    ? `le pagine di ogni PDF insieme, al massimo ${project.pages_per_request} per richiesta`
    : "tutte le pagine di ogni PDF insieme, una richiesta per PDF";
}

/** Pannello "Come inviare le pagine a Gemini": vale per la prova e per l'indicizzazione. */
function sendModePanel(ctx) {
  const p = ctx.project, together = p.send_mode === "insieme";
  const html = `
    <details class="panel send-mode" ${ctx.sendOpen ? "open" : ""}>
      <summary><strong>Come inviare le pagine a Gemini:</strong> ${esc(sendModeText(p))}</summary>
      <label class="row send-option"><input type="radio" name="send-mode" value="pagina" ${together ? "" : "checked"}>
        <span><strong>Una pagina per richiesta</strong>: ogni pagina da sola (immagine e testo). È il modo più preciso sulle
          pagine molto dense, ma fa una richiesta per pagina.</span></label>
      <label class="row send-option"><input type="radio" name="send-mode" value="insieme" ${together ? "checked" : ""}>
        <span><strong>Tutte le pagine di un PDF insieme</strong>: un estratto ritagliato dal PDF originale con solo le sue
          pagine da indicizzare, in una richiesta per PDF (i PDF non si mescolano mai). Molte meno richieste: utile con le
          quote giornaliere. Se la risposta è troppo lunga, il programma divide da solo le pagine in più richieste dello
          stesso PDF.</span></label>
      <div class="row send-max" ${together ? "" : "hidden"}>
        <label for="send-max" class="inline">Al massimo</label>
        <input type="number" id="send-max" min="1" class="input-number" value="${esc(p.pages_per_request || "")}">
        <span class="small">pagine per richiesta</span>
        <span class="hint">vuoto = tutte; utile se Gemini rifiuta richieste troppo grandi</span></div>
      <p class="hint">Vale per la prova e per l'indicizzazione. Non cambia le regole: le pagine già fatte restano valide, e
        puoi rifare in un modo le pagine fallite nell'altro.</p>
    </details>`;
  const bind = root => {
    const save = () => busy(null, async () => {
      const mode = $('input[name="send-mode"]:checked', root).value;
      const max = $("#send-max", root).value.trim();
      ctx.project = await api("PUT", `/api/projects/${enc(ctx.pid)}/send`,
                              { mode, pages_per_request: mode === "insieme" && max ? +max : null });
      toast(`Invio: ${sendModeText(ctx.project)}.`);
      ctx.sendOpen = true;
      ctx.rerender();
    });
    $$('input[name="send-mode"]', root).forEach(r => r.addEventListener("change", save));
    $("#send-max", root).addEventListener("change", save);
  };
  return { html, bind };
}

// ------------------------------------------------------------------ ③ PROVA
async function renderTest(ctx) {
  const { project, pid, box } = ctx;
  const data = await api("GET", `/api/projects/${enc(pid)}/prova`);
  const docs = project.documents;
  const tested = Object.fromEntries(data.documents.map(d => [d.id, d]));
  const planKey = `prova:${pid}`;
  let saved = {};
  try { saved = JSON.parse(drafts.get(planKey) || "{}"); } catch { saved = {}; }
  const plan = { ...data.plan, ...(saved.plan || {}) };
  const include = new Set(saved.include || docs.map(d => d.id));
  const anyStale = data.documents.some(d => d.stale);
  const send = sendModePanel(ctx);
  ctx.rerender = () => renderTest(ctx);

  box.innerHTML = `
    ${send.html}
    <div class="panel">
      <h3>Prova su poche pagine</h3>
      ${helpBlock("test", "Poche pagine per catalogo, con le regole vere: vedi subito se tabella e guida funzionano.",
        `<p>Se cambi qualcosa, rifai la prova. Le pagine provate non si pagano due volte: se le regole non cambiano,
          contano già come indicizzate.</p>
        <p><em>Proponi le pagine</em> sceglie prima le pagine d'esempio della scheda che sono anche da indicizzare, poi
          pagine distribuite nel resto; <em>Altre pagine</em> ne propone di non ancora provate. Puoi anche scriverle a mano.</p>`)}
      <div class="row">
        <label for="t-count" class="m-0">Pagine per catalogo</label>
        <input type="number" id="t-count" min="1" value="${esc(saved.count || data.default_count)}" class="input-number">
        <button class="secondary small" id="t-sample" type="button">Proponi le pagine</button>
        <button class="secondary small" id="t-more" type="button" title="Pagine non ancora provate">Altre pagine</button>
      </div>
      <div class="table-wrap full"><table>
        <thead><tr><th></th><th>PDF</th><th>Pagine da provare</th><th>Da indicizzare</th><th>Ultima prova</th></tr></thead>
        <tbody>${docs.map(d => `<tr>
          <td><input type="checkbox" data-tinc="${esc(d.id)}" ${include.has(d.id) ? "checked" : ""}></td>
          <td><strong>${esc(d.title)}</strong> ${guideState(d, null)}</td>
          <td><input type="text" data-tpages="${esc(d.id)}" value="${esc(plan[d.id] || "")}" class="input-pages"></td>
          <td class="small">${plural(d.to_index, "pagina", "pagine")}</td>
          <td class="small">${tested[d.id] ? `${esc(formatPages(tested[d.id].pages))}
            ${tested[d.id].stale ? '<span class="badge warn">regole cambiate</span>' : '<span class="badge ok">attuale</span>'}` : "—"}</td>
        </tr>`).join("")}</tbody></table></div>
      <div class="row mt-m"><span class="hint" id="t-info"></span><span class="spacer"></span>
        <button class="gemini" id="t-run" type="button">Fai la prova</button></div>
    </div>
    <div id="t-results"></div>`;
  send.bind(box);

  const count = $("#t-count");
  const readPlan = () => {
    const out = {};
    for (const d of docs) {
      if (!$(`[data-tinc="${CSS.escape(d.id)}"]`).checked) continue;
      const text = $(`[data-tpages="${CSS.escape(d.id)}"]`).value.trim();
      if (text) out[d.id] = text;
    }
    return out;
  };
  const remember = () => {
    const p = {};
    docs.forEach(d => { p[d.id] = $(`[data-tpages="${CSS.escape(d.id)}"]`).value; });
    drafts.set(planKey, JSON.stringify({ count: count.value, plan: p,
      include: docs.filter(d => $(`[data-tinc="${CSS.escape(d.id)}"]`).checked).map(d => d.id) }));
    const chosen = readPlan();
    let n = 0, requests = 0;
    try {
      for (const d of docs) {
        if (!chosen[d.id]) continue;
        const k = parsePages(chosen[d.id], d.page_count).length;
        n += k; requests += requestsFor(ctx.project, k);
      }
      $("#t-info").textContent = `${plural(n, "pagina", "pagine")} in ${Object.keys(chosen).length} PDF: ` +
        `${plural(requests, "richiesta", "richieste")} a Gemini (${sendModeText(ctx.project)}).`;
    } catch (e) { $("#t-info").textContent = `⚠ ${e.message}`; }
  };
  $$("[data-tinc], [data-tpages]").forEach(el => el.addEventListener("input", remember));
  $$("[data-tinc]").forEach(el => el.addEventListener("change", remember));
  count.addEventListener("input", remember);
  const resample = more => busy(null, async () => {
    const ids = docs.filter(d => $(`[data-tinc="${CSS.escape(d.id)}"]`).checked).map(d => d.id);
    const r = await api("POST", `/api/projects/${enc(pid)}/prova/plan`, { count: +count.value || 4, docs: ids, more });
    for (const id of ids) $(`[data-tpages="${CSS.escape(id)}"]`).value = r.plan[id] || "";
    if (more && ids.some(id => !r.plan[id])) toast("Per alcuni PDF non restano pagine da indicizzare non ancora provate.");
    remember();
  });
  $("#t-sample").addEventListener("click", () => resample(false));
  $("#t-more").addEventListener("click", () => resample(true));
  $("#t-run").addEventListener("click", async e => {
    const chosen = readPlan();
    let pages = 0, requests = 0;
    try {
      for (const d of docs) {
        if (!chosen[d.id]) continue;
        const k = parsePages(chosen[d.id], d.page_count).length;
        pages += k; requests += requestsFor(ctx.project, k);
      }
    } catch (err) { toast(err.message); return; }
    if (!pages) { toast("Scegli almeno un PDF e almeno una pagina."); return; }
    const noGuide = docs.filter(d => chosen[d.id] && !d.settings.guide);
    const ok = await confirmDialog({ title: "Fare la prova?", ok: "Fai la prova", html: `
      <p><strong>${plural(requests, "richiesta", "richieste")}</strong> a Gemini per ${plural(pages, "pagina", "pagine")}
        di ${Object.keys(chosen).length} PDF (${esc(sendModeText(ctx.project))}).</p>
      ${noGuide.length ? `<p class="note warn">Senza guida all'indicizzazione: ${noGuide.map(d => esc(d.title)).join(", ")}.</p>` : ""}
      <p class="hint">Sostituisce la prova precedente dei PDF scelti; quella degli altri resta.</p>` });
    if (!ok) return;
    await busy(e.target, async () => {
      const job = await api("POST", `/api/projects/${enc(pid)}/prova`, { plan: chosen });
      box.innerHTML = "";
      watchJob(ctx.jobBox, job, () => ctx.refresh());
    });
  });
  remember();

  // risultati dell'ultima prova
  const res = $("#t-results");
  if (!data.available) { res.innerHTML = `<div class="panel"><p class="muted">Nessuna prova ancora.</p></div>`; return; }
  res.innerHTML = `
    ${anyStale ? `<div class="panel note warn">Per alcuni PDF tabella, guida o note sono cambiate dopo la prova: i risultati
      qui sotto sono stati ottenuti con le regole precedenti. Rifai la prova per vedere l'effetto delle modifiche.</div>` : ""}
    <div class="row mb-s"><span class="muted small">Ultima prova: ${esc((data.created_at || "").replace("T", " ").slice(0, 16))}</span>
      <span class="spacer"></span>${data.csv ? `<a class="linkbtn secondary small" href="/api/projects/${enc(pid)}/prova.csv">Scarica il CSV di prova</a>` : ""}</div>
    ${data.documents.map(d => {
      const rows = d.rows.length;
      const failed = Object.entries(d.failed);
      const errors = d.anomalies.filter(a => a.level !== "info");
      return `<div class="panel">
        <div class="row"><h3 class="m-0">${esc(d.title)}</h3>
          ${d.stale ? '<span class="badge warn">regole cambiate dopo la prova</span>' : ""}
          <span class="spacer"></span><span class="badge ${rows ? "ok" : "warn"}">${plural(rows, "riga", "righe")}</span>
          ${errors.length ? `<span class="badge warn">${errors.length} segnalazioni</span>` : ""}</div>
        <p class="small">${d.pages.map(p => `<span class="badge clickable" data-doc="${esc(d.id)}" data-page="${p}"
            title="${esc(d.summaries[p] || "")}">p. ${p}: ${plural(d.rows.filter(r => String(r[data.page_column]) === String(p)).length, "riga", "righe")}</span>`).join(" ")}</p>
        ${failed.length ? `<div class="note error small">Pagine non riuscite: ${failed.map(([k, v]) => `${esc(k)} (${esc(v)})`).join("; ")}</div>` : ""}
        ${Object.keys(d.notes).length ? `<details class="small"><summary>Note di Gemini (${Object.keys(d.notes).length})</summary>
          <ul>${Object.entries(d.notes).map(([p, n]) => `<li>p. ${esc(p)}: ${esc(n)}</li>`).join("")}</ul></details>` : ""}
        ${rows ? table(d.columns, d.rows, { pageColumn: data.page_column, docId: d.id })
          : `<div class="note warn">Nessuna riga estratta: controlla tabella, guida e pagine scelte.</div>`}
        ${errors.length ? `<details class="small"><summary>${errors.length} segnalazioni dei controlli</summary>
          <ul>${errors.map(a => `<li>${a.page ? `p. ${a.page}` : ""}${a.row ? `, riga ${a.row}` : ""}${a.column ? `, ${esc(a.column)}` : ""}: ${esc(a.problem)}${a.value ? ` (“${esc(a.value)}”)` : ""}</li>`).join("")}</ul></details>` : ""}
      </div>`;
    }).join("")}
    <p class="hint">Non ti convince? Correggi la <a href="#/p/${enc(pid)}/settings">tabella</a>, la guida del catalogo
      nella biblioteca o le <a href="#/p/${enc(pid)}/docs">note del PDF</a>, poi rifai la prova.</p>`;
  bindPageClicks(res, ctx.titles);
}

// ------------------------------------------------------------------ ④ INDICIZZAZIONE
async function renderIndex(ctx) {
  const { pid, box } = ctx;
  let plan;
  try { plan = await api("GET", `/api/projects/${enc(pid)}/index/plan`); }
  catch (e) {
    box.innerHTML = `<div class="panel note warn">${esc(e.message)}</div>`;
    return;
  }
  const changed = plan.spec_changed;
  const noGuide = plan.documents.filter(d => !d.has_guide);
  const together = plan.send_mode === "insieme";
  const send = sendModePanel(ctx);
  ctx.rerender = () => renderIndex(ctx);
  const big = plan.biggest_request;
  const anyFromTest = plan.documents.some(d => d.from_prova);
  box.innerHTML = `
    ${send.html}
    <div class="panel">
      <h3>Indicizzazione di tutti i PDF</h3>
      ${helpBlock("index", `Gemini legge le pagine da fare: ${esc(sendModeText(ctx.project))}.`,
        `<p>Ogni pagina arriva con la tabella del progetto, la guida del catalogo e le note del PDF. Il lavoro è
          riprendibile: le pagine fatte (anche dalla prova) non si rifanno, quelle fallite si ritentano a ogni avvio.</p>`)}
      <div class="table-wrap"><table><thead><tr><th>PDF</th><th>Pagine da indicizzare</th><th>Fatte</th>
          ${anyFromTest ? "<th>Dalla prova</th>" : ""}<th>Da fare</th><th>Richieste</th><th></th></tr></thead><tbody>
        ${plan.documents.map(d => `<tr><td><strong>${esc(d.title)}</strong>${d.has_notes ? ' <span class="badge">note</span>' : ""}
            ${d.has_guide ? "" : ' <span class="badge warn">senza guida</span>'}</td>
          <td>${d.pages} <span class="small muted">(${esc(d.pages_text)})</span></td><td>${d.done}</td>
          ${anyFromTest ? `<td>${d.from_prova || "—"}</td>` : ""}<td>${d.todo}</td>
          <td>${d.requests || "—"}</td>
          <td class="nowrap">${d.spec_changed ? '<span class="badge warn">regole cambiate: da rifare</span>'
            : d.failed ? `<span class="badge error" title="${esc(d.failed_reason)}">${d.failed} fallite</span>`
            : d.todo ? "" : '<span class="badge ok">completo</span>'}
            ${d.done || d.failed ? `<button class="secondary small" data-restart="${esc(d.id)}" type="button"
              title="Cancella i risultati di questo PDF e rifà tutte le sue pagine">Rifai da capo</button>` : ""}</td></tr>`).join("")}
      </tbody></table></div>
      ${plan.documents.some(d => d.failed) ? `<div class="note error small"><strong>Pagine fallite</strong> (si ritentano con
        <em>Avvia l'indicizzazione</em>):<ul class="my-2xs">${plan.documents.filter(d => d.failed).map(d =>
          `<li><strong>${esc(d.title)}</strong>: ${plural(d.failed, "pagina", "pagine")} — ${esc(d.failed_reason)}</li>`).join("")}</ul>
        ${together ? `Se il motivo è una richiesta troppo grande o una quota esaurita, imposta un massimo di pagine per richiesta
          qui sopra (per esempio 50).` : ""}</div>` : ""}
      <p class="mt-m"><span class="badge ok">${plan.done} pagine fatte</span>
        ${plan.from_prova ? `<span class="badge ok">${plan.from_prova} dalla prova</span>` : ""}
        <span class="badge">${plan.todo} da fare</span></p>
      ${changed.length ? `<div class="note warn">Per ${changed.length} PDF tabella, guida, note o pagine sono cambiate dopo
        l'indicizzazione: per non mescolare risultati ottenuti con regole diverse, quelle pagine vanno rifatte.</div>` : ""}
      ${noGuide.length ? `<div class="note warn small">Senza guida all'indicizzazione: ${noGuide.map(d => esc(d.title)).join(", ")}.
        Puoi analizzarli nella biblioteca e poi usare <em>Aggiorna dalla biblioteca</em> (passo ②).</div>` : ""}
      ${plan.todo ? `<p>${plural(plan.requests, "richiesta", "richieste")} a Gemini per ${plural(plan.todo, "pagina", "pagine")},
          circa <strong>${plural(plan.estimate_minutes, "minuto", "minuti")}</strong> (stima; si adatta alle quote API).
          Puoi chiudere la pagina: il lavoro continua finché il server è acceso, e si riprende se lo fermi.</p>
        ${together && big ? `<p class="hint">La richiesta più grande ha ${plural(big.pages, "pagina", "pagine")}, circa
          ${Math.round(big.tokens / 1000)} mila token in ingresso (stima). Se Gemini la rifiuta perché troppo grande, imposta
          un massimo di pagine per richiesta qui sopra.</p>` : ""}
        <div class="row"><span class="spacer"></span>
          <button class="gemini" id="start" type="button">Avvia l'indicizzazione (${plan.todo} pagine)</button></div>`
      : plan.from_prova ? `<p>Restano solo le ${plan.from_prova} pagine della prova: vengono riusate, senza chiamare Gemini.</p>
        <div class="row"><span class="spacer"></span>
          <button id="start" type="button">Completa con le pagine della prova</button></div>`
      : `<div class="note">Tutte le pagine sono indicizzate. <a href="#/p/${enc(pid)}/verify">Vai alle verifiche</a>
          (passo ⑤), dove puoi anche rifare singole pagine.</div>`}
      ${plan.done || plan.documents.some(d => d.failed) ? `<div class="row mt-s"><span class="spacer"></span>
        <button class="secondary" id="restart-all" type="button" title="Cancella tutti i risultati e rifà tutte le pagine">
          Rifai tutto da capo…</button></div>` : ""}
    </div>`;
  send.bind(box);
  const runIndex = (button, body) => busy(button, async () => {
    const job = await api("POST", `/api/projects/${enc(pid)}/index`, body);
    box.innerHTML = "";
    watchJob(ctx.jobBox, job, j => {
      if (jobSucceeded(j)) location.hash = `#/p/${enc(pid)}/verify`;
      else { if (j.result && j.result.stopped_reason) toast(j.result.stopped_reason, 8000); ctx.refresh(); }
    }, { finale: true });
  });
  const restart = async (button, docs) => {
    const all = docs.length === plan.documents.length;
    const pages = docs.reduce((n, d) => n + d.pages, 0);
    const requests = docs.reduce((n, d) => n + d.restart_requests, 0);
    const ok = await confirmDialog({ title: all ? "Rifare tutto da capo?" : `Rifare da capo ${docs[0].title}?`, danger: true,
      ok: "Rifai da capo", html: `
      <p>Verranno <strong>cancellati i risultati</strong> di ${all ? "tutti i PDF" : docs.map(d => `<strong>${esc(d.title)}</strong>`).join(", ")}
        e rifatte ${pages === 1 ? "la sua unica pagina" : `tutte le ${pages} pagine`}: ${plural(requests, "richiesta", "richieste")} a Gemini
        (${esc(sendModeText(ctx.project))})${all ? `, circa ${plural(plan.restart.minutes, "minuto", "minuti")}` : ""}.</p>
      <p class="hint">Le pagine della prova non vengono riusate. Se il lavoro si ferma (quote, <em>Ferma</em>), le pagine non
        ancora rifatte restano da fare: i risultati precedenti non tornano.</p>` });
    if (ok) await runIndex(button, { restart: all ? true : docs.map(d => d.id), force: changed.length > 0 });
  };
  $$("[data-restart]", box).forEach(b => b.addEventListener("click", () =>
    restart(b, plan.documents.filter(d => d.id === b.dataset.restart))));
  if ($("#restart-all")) $("#restart-all").addEventListener("click", e => restart(e.target, plan.documents));
  const start = $("#start");
  if (start) start.addEventListener("click", async () => {
    const ok = await confirmDialog({ title: "Avviare l'indicizzazione?", ok: "Avvia",
      html: `<p>${plan.todo ? `${plural(plan.requests, "richiesta", "richieste")} a Gemini per ${plural(plan.todo, "pagina", "pagine")}
               di ${plan.documents.filter(d => d.todo).length} PDF (${esc(sendModeText(ctx.project))}), circa
               ${plural(plan.estimate_minutes, "minuto", "minuti")}.` : "Nessuna richiesta a Gemini."}</p>
             ${plan.from_prova ? `<p>${plan.from_prova} pagine della prova vengono riusate senza chiamare Gemini.</p>` : ""}
             ${changed.length ? `<p><strong>I risultati precedenti di ${changed.map(id => esc(ctx.titles[id] || id)).join(", ")} verranno sostituiti.</strong></p>` : ""}` });
    if (!ok) return;
    await runIndex(start, { force: changed.length > 0 });
  });
}

// ------------------------------------------------------------------ ⑥ RISULTATI
async function renderResults(ctx) {
  const { pid, box } = ctx;
  let res;
  try { res = await api("GET", `/api/projects/${enc(pid)}/results`); }
  catch (e) { box.innerHTML = `<div class="panel note warn">${esc(e.message)}</div>`; return; }
  if (!res.available) {
    box.innerHTML = `<div class="panel note">Nessun risultato: <a href="#/p/${enc(pid)}/index">avvia l'indicizzazione</a>.</div>`;
    return;
  }
  const s = res.stats;
  const levels = res.anomalies_by_level;
  box.innerHTML = `
    <div class="panel">
      <h3>CSV unico del progetto</h3>
      <p><span class="badge ok">${plural(s.righe_finali, "riga", "righe")}</span>
        <span class="badge">${s.documenti_indicizzati}/${s.documenti_totali} PDF</span>
        ${s.pagine_da_elaborare ? `<span class="badge warn">${s.pagine_da_elaborare} pagine non ancora elaborate</span>` : ""}
        ${res.corrections ? `<span class="badge">${plural(res.corrections, "correzione", "correzioni")} applicate</span>` : ""}</p>
      ${res.not_indexed.length ? `<div class="note warn">Non ancora indicizzati: ${res.not_indexed.map(id => esc(ctx.titles[id] || id)).join(", ")}.
        <a href="#/p/${enc(pid)}/index">Indicizzali</a>.</div>` : ""}
      ${res.stale.length ? `<div class="note warn">Regole cambiate dopo l'indicizzazione per: ${res.stale.map(id => esc(ctx.titles[id] || id)).join(", ")}.
        <a href="#/p/${enc(pid)}/index">Rifalli</a>.</div>` : ""}
      <div class="row">
        <a class="linkbtn" href="/api/projects/${enc(pid)}/download/csv">Scarica il CSV unico</a>
        <a class="linkbtn secondary" href="/api/projects/${enc(pid)}/search" target="_blank" rel="noopener">Apri la pagina di ricerca</a>
        <span class="spacer"></span>
        <button class="secondary" id="regen" type="button">Rigenera (senza Gemini)</button>
      </div>
      ${helpBlock("results", "Le righe si vedono e si correggono al passo ⑤ Verifiche; qui si scaricano.",
        `<p>CSV e pagina di ricerca contengono già le correzioni del passo ⑤. La pagina di ricerca è salvata anche come
          file autonomo in <code>data/exports/${esc(pid)}/ricerca.html</code>: si apre con un doppio clic, senza server.
          <em>Rigenera</em> ricostruisce CSV e pagina di ricerca dai risultati salvati, senza chiamare Gemini.</p>`)}
    </div>
    <div class="panel"><h3>Per PDF</h3>
      <div class="table-wrap"><table><thead><tr><th>PDF</th><th>Righe</th><th>Errori</th><th>Avvisi</th><th></th></tr></thead><tbody>
        ${res.documents.map(d => `<tr><td><strong>${esc(d.title)}</strong>${d.stale ? ' <span class="badge warn">regole cambiate</span>' : ""}</td>
          <td>${d.rows}</td><td>${d.errors}</td><td>${d.warnings}</td>
          <td><a href="/api/projects/${enc(pid)}/download/documento?doc=${enc(d.id)}">CSV di questo PDF</a></td></tr>`).join("")}
      </tbody></table></div></div>
    ${res.anomalies_total ? `<details class="panel"><summary><strong>Anomalie</strong>
        <span class="small muted">${levels.errore} errori · ${levels.avviso} avvisi · ${levels.info} note di Gemini</span></summary>
      <div class="row mt-s"><span class="hint">Prima gli errori, poi gli avvisi, infine le note. Clic su una riga per vedere la pagina.</span>
        <span class="spacer"></span><a class="linkbtn secondary small" href="/api/projects/${enc(pid)}/download/anomalie">Scarica le anomalie</a></div>
      ${table(["file", "livello", "pagina", "riga", "colonna", "valore", "problema"],
        res.anomalies.map(a => ({ file: a.file, livello: a.level, pagina: a.page ?? "", riga: a.row ?? "", colonna: a.column ?? "", valore: a.value, problema: a.problem })),
        { pageColumn: "pagina", fileColumn: "file", files: ctx.files })}</details>` : ""}`;
  bindPageClicks(box, ctx.titles);
  $("#regen").addEventListener("click", e => busy(e.target, async () => { await renderResults(ctx); toast("CSV e pagina di ricerca rigenerati."); }));
}

// ------------------------------------------------------------------ avvio
refreshStatus();
setInterval(refreshStatus, 20000);
route();
