// Mission Control slice. Read-only: renders backend data, never mutates
// mission state, locks nothing, and makes no provider calls (mock-free:
// exactly one GET of the mission view).
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
const errBox = document.getElementById("error");
let M = null;
let ITEMS = [];

function fail(message) { errBox.style.display = "block"; errBox.textContent = message; }

const GROUPS = ["Policy quotations", "Deterministic calculations", "Contradictions", "Hypotheses", "Open questions"];
let FILTER = "all";
let QUERY = "";

function buildItems() {
  const items = [];
  (M.constraint || []).forEach((q, i) => items.push({
    id: `policy-${i}`, kind: "policy", group: GROUPS[0],
    label: `Policy requirement ${i + 1}`,
    classification: "verified observation",
    source: `${q.doc_id} [${q.start}\u2013${q.end}]`,
    provenance: `Exact quotation verified against the source document at the stated character offsets.`,
    detail: `\u201c${q.quote}\u201d`,
  }));
  ((M.evidence || {}).calculations || []).forEach((c, i) => items.push({
    id: `metric-${i}`, kind: "metric", group: GROUPS[1],
    label: `${c.label}: ${c.value}`,
    classification: "deterministic calculation",
    source: c.source,
    provenance: `Rule: ${c.rule}. Denominator: ${c.denominator}. Computed by fixed backend rules; no AI judgment involved.`,
    detail: `${c.label} = ${c.value}`,
  }));
  ((M.evidence || {}).contradictions || []).forEach((k, i) => items.push({
    id: `contra-${i}`, kind: "contradiction", group: GROUPS[2],
    label: k.title,
    classification: "source-backed contradiction",
    source: "multiple evidence references",
    provenance: `Status: ${k.status || "unresolved"}. Each side is traceable to its cited source.`,
    detail: k.computed || k.title,
  }));
  (M.hypotheses || []).forEach((h, i) => items.push({
    id: `hyp-${i}`, kind: "hypothesis", group: GROUPS[3],
    label: h.text,
    classification: "unverified hypothesis",
    source: `basis: ${(h.basis || []).join("; ")}`,
    provenance: `Interpretation only (${h.status || "unverified"}). Never a confirmed failure on its own.`,
    detail: h.text,
  }));
  (((M.experiment || {}).definition || {}).hypotheses || []).forEach(h => items.push({
    id: `exp-${h.id}`, kind: "hypothesis", group: GROUPS[3],
    label: `${h.id} — experiment hypothesis`,
    classification: "unverified hypothesis",
    source: "EXP-001 definition",
    provenance: `Interpretation only. Tested only through a locked prediction, never assumed.`,
    detail: h.text,
  }));
  ((M.evidence || {}).unresolved_questions || []).forEach((q, i) => items.push({
    id: `ques-${i}`, kind: "question", group: GROUPS[4],
    label: q,
    classification: "open question",
    source: "evidence gap",
    provenance: `Explicitly unresolved in the backend record. Not evidence for any hypothesis.`,
    detail: q,
  }));
  return items;
}

function renderOverview() {
  const current = (M.stages.find(s => s.state === "current") || {}).stage || "complete";
  document.getElementById("mcStatus").innerHTML =
    `<span class="tag">active stage: ${esc(current)}</span>`;
  document.getElementById("mcBrief").textContent = M.brief;
  document.getElementById("mcSteps").innerHTML = M.stages.map(s =>
    `<li class="${s.state}">${esc(s.stage)}: ${esc(s.state)}</li>`).join("");
  const want = ["Eligible urgent cases", "Confirmed deadline misses", "Valid acknowledgment within 4 hours"];
  document.getElementById("mcHero").innerHTML = want.map(label => {
    const c = (M.evidence.calculations || []).find(x => x.label === label);
    if (!c) return "";
    return `<div class="card"><span class="figure">${esc(c.value)}</span><span class="caption">${esc(c.label)}</span></div>`;
  }).join("");
}

function renderSummary() {
  const find = (label) => ((M.evidence || {}).calculations || []).find(c => c.label === label);
  const cards = [
    ["7 eligible cases", find("Eligible urgent cases")],
    ["3 confirmed misses", find("Confirmed deadline misses")],
    ["1 valid acknowledgment", find("Valid acknowledgment within 4 hours")],
  ];
  document.getElementById("mcSummary").innerHTML = cards.map(([caption, c]) =>
    c ? `<div class="card"><span class="figure">${esc(c.value)}</span><span class="caption">${esc(caption)} · ${esc(c.denominator)}</span></div>` : "").join("");
}

function visibleItems() {
  const q = QUERY.trim().toLowerCase();
  return ITEMS.filter(it =>
    (FILTER === "all" || it.group === FILTER) &&
    (!q || `${it.label} ${it.detail}`.toLowerCase().includes(q)));
}

function renderFilters() {
  const box = document.getElementById("mcFilters");
  const counts = {};
  for (const it of ITEMS) counts[it.group] = (counts[it.group] || 0) + 1;
  const chips = [`<button data-filter="all" aria-pressed="${FILTER === "all"}">All (${ITEMS.length})</button>`]
    .concat(GROUPS.map(g =>
      `<button data-filter="${esc(g)}" aria-pressed="${FILTER === g}">${esc(g)} (${counts[g] || 0})</button>`));
  box.innerHTML = chips.join("");
}

function renderList(selectFirst) {
  const box = document.getElementById("mcList");
  document.getElementById("mcLoading").style.display = "none";
  renderFilters();
  const visible = visibleItems();
  if (!visible.length) {
    box.innerHTML = `<li><div class="card">No evidence matches this filter. Clear the search or choose another classification.</div></li>`;
    return;
  }
  const groups = FILTER === "all" ? GROUPS : [FILTER];
  box.innerHTML = groups.map(g => {
    const rows = visible.filter(it => it.group === g);
    if (!rows.length) return "";
    return `<li><h3 class="group-h">${esc(g)} (${rows.length})</h3><ul>` + rows.map(it =>
      `<li><button data-item="${esc(it.id)}" aria-current="false"><span class="tag">${esc(it.classification)}</span> ${esc(it.label.slice(0, 90))}</button></li>`).join("") + `</ul></li>`;
  }).join("");
  box.querySelectorAll("button[data-item]").forEach(b =>
    b.addEventListener("click", () => select(b.dataset.item)));
  if (selectFirst && visible.length) select(visible[0].id);
}

let SELECTED = null;

const VERIFICATION = {
  "verified observation": "verified (exact quotation)",
  "verified record": "verified (source record)",
  "deterministic calculation": "verified (deterministic computation)",
  "source-backed contradiction": "source-backed, unresolved",
  "unverified hypothesis": "unverified",
  "stakeholder report": "reported, not independently verified",
  "open question": "open",
};

function select(id) {
  const it = ITEMS.find(x => x.id === id);
  if (!it) return;
  SELECTED = id;
  const node = NODES.find(n => n.item === id);
  markNode(node ? node.id : null);
  document.querySelectorAll("#mcList button[data-item]").forEach(b =>
    b.setAttribute("aria-current", String(b.dataset.item === id)));
  document.getElementById("mcInspector").innerHTML =
    `<dl>`
    + `<div class="insp-row"><dt>Item</dt><dd>${esc(it.label)}</dd></div>`
    + `<div class="insp-row"><dt>Classification</dt><dd><span class="tag">${esc(it.classification)}</span></dd></div>`
    + `<div class="insp-row"><dt>Verification</dt><dd>${esc(VERIFICATION[it.classification] || "see provenance")}</dd></div>`
    + `<div class="insp-row"><dt>Source</dt><dd>${esc(it.source)}</dd></div>`
    + `<div class="insp-row"><dt>Provenance</dt><dd>${esc(it.provenance)}</dd></div>`
    + `<div class="insp-row"><dt>Detail</dt><dd>${esc(it.detail)}</dd></div>`
    + `</dl>`;
}

// ---- Evidence-backed graph (MC-002) ----
// Every edge names source, target, relationship type, supporting refs, and
// whether it is verified (deterministic derivation), reported (stakeholder
// assertion, not endorsed), or hypothesized (interpretive link).
const NODES = [
  {id: "policy", label: "Policy", x: 100, y: 70, item: "policy-0",
   classification: "verified observation", source: "policy.md (verified quotations)",
   provenance: "Exact 1-hour assignment and 4-hour acknowledgment rules with character offsets."},
  {id: "dispatcher", label: "Dispatcher report", x: 100, y: 210, item: null,
   classification: "stakeholder report", source: "dispatcher.md",
   provenance: "Reported overnight-backlog practice. Attributed, never independently verified."},
  {id: "manager", label: "Manager claim", x: 100, y: 350, item: null,
   classification: "stakeholder report", source: "manager.md",
   provenance: "Reported no-wait claim. Attributed, never independently verified."},
  {id: "events", label: "Events log", x: 340, y: 220, item: "metric-0",
   classification: "verified record", source: "events.csv (7 eligible urgent rows)",
   provenance: "Deterministic event log; all metrics derive from these rows."},
  {id: "misses", label: "3 confirmed misses", x: 340, y: 80, item: "metric-4",
   classification: "deterministic calculation", source: "events.csv measured against policy.md",
   provenance: "Computed against the 4-hour rule; incomplete windows excluded, never counted as misses."},
  {id: "hqueue", label: "H-QUEUE", x: 560, y: 140, item: "exp-H-QUEUE",
   classification: "unverified hypothesis", source: "EXP-001 definition",
   provenance: "Queue-handling interpretation. Tested only through locked prediction, never assumed."},
  {id: "hack", label: "H-ACK", x: 560, y: 290, item: "exp-H-ACK",
   classification: "unverified hypothesis", source: "EXP-001 definition",
   provenance: "Acknowledgment-bottleneck interpretation. Tested only through locked prediction, never assumed."},
];
const EDGES = [
  {s: "dispatcher", t: "manager", type: "conflicts-with", status: "verified",
   refs: ["dispatcher", "manager"],
   note: "The backlog admission and the no-wait claim cannot both hold. Verification covers the disagreement itself; it does not establish which statement is true."},
  {s: "policy", t: "misses", type: "measured-against", status: "verified",
   refs: ["policy", "events.csv"],
   note: "The 4-hour policy rule defines what counts as a confirmed miss."},
  {s: "events", t: "misses", type: "computed-from", status: "verified",
   refs: ["events.csv"],
   note: "Miss counts derive deterministically from event rows."},
  {s: "dispatcher", t: "hqueue", type: "asserts", status: "reported",
   refs: ["dispatcher", "events.csv"],
   note: "The dispatcher asserts backlog causes unassigned cases. A reported assertion, not an endorsed causal finding."},
  {s: "events", t: "hqueue", type: "relevant-to", status: "hypothesized",
   refs: ["events.csv"],
   note: "Unassigned rows are relevant to queue delays but do not prove them; relevance is not causation."},
  {s: "events", t: "hack", type: "relevant-to", status: "hypothesized",
   refs: ["events.csv", "case-003"],
   note: "Missing acknowledgment data is relevant to H-ACK but does not independently prove an acknowledgment was lost."},
];
const ILLUST_STEPS = ["Dashboard", "Queue Worker", "Gateway", "Acknowledgment"];

function nodeById(id) { return NODES.find(n => n.id === id); }

function renderGraph() {
  const svg = document.getElementById("mcGraph");
  const edgeEls = EDGES.map(e => {
    const a = nodeById(e.s), b = nodeById(e.t);
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    return `<g class="edge edge-${e.status}"><line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>`
      + `<text x="${mx}" y="${my - 5}">${esc(e.type)}</text></g>`;
  }).join("");
  const nodeEls = NODES.map(n =>
    `<g class="node" data-node="${esc(n.id)}" tabindex="0" role="button" aria-label="${esc(n.label)}">`
    + `<rect x="${n.x - 62}" y="${n.y - 20}" width="124" height="40" rx="10"/>`
    + `<text x="${n.x}" y="${n.y + 5}">${esc(n.label)}</text></g>`).join("");
  svg.innerHTML = edgeEls + nodeEls;
}

function renderIllust() {
  const svg = document.getElementById("mcIllust");
  const boxes = ILLUST_STEPS.map((s, i) => {
    const x = 20 + i * 155;
    const link = i < ILLUST_STEPS.length - 1
      ? `<line class="illust-link" x1="${x + 120}" y1="80" x2="${x + 155}" y2="80"/><text x="${x + 128}" y="72">uses</text>` : "";
    return `<g class="illust-node"><rect x="${x}" y="55" width="120" height="50" rx="10"/>`
      + `<text x="${x + 60}" y="83">${esc(s)}</text></g>` + link;
  }).join("");
  svg.innerHTML = boxes;
}

function markNode(id) {
  document.querySelectorAll("#mcGraph .node").forEach(g =>
    g.setAttribute("aria-current", String(g.dataset.node === id)));
}

function selectNode(id) {
  const node = nodeById(id);
  if (!node) return;
  markNode(id);
  if (node.item && ITEMS.some(it => it.id === node.item)) {
    select(node.item);
    return;
  }
  document.getElementById("mcInspector").innerHTML =
    `<dl>`
    + `<div class="insp-row"><dt>Node</dt><dd>${esc(node.label)}</dd></div>`
    + `<div class="insp-row"><dt>Classification</dt><dd><span class="tag">${esc(node.classification)}</span></dd></div>`
    + `<div class="insp-row"><dt>Verification</dt><dd>${esc(VERIFICATION[node.classification] || "see provenance")}</dd></div>`
    + `<div class="insp-row"><dt>Source</dt><dd>${esc(node.source)}</dd></div>`
    + `<div class="insp-row"><dt>Provenance</dt><dd>${esc(node.provenance)}</dd></div>`
    + EDGES.filter(e => e.s === id || e.t === id).map(e =>
      `<div class="insp-row"><dt>Relationship (${esc(e.status)})</dt>`
      + `<dd>${esc(e.s)} ${esc(e.type)} ${esc(e.t)} — refs: ${(e.refs || []).map(esc).join(", ")}. ${esc(e.note)}</dd></div>`).join("")
    + `</dl>`;
}

// ---- Hypothesis Lab (MC-003, read-only) ----
// Renders backend-supplied hypotheses, edge-derived relevance, bounding
// metrics, diagnostics, and diagnostic status. Never invents scores,
// never reveals withheld outcomes (the server omits them until reveal),
// never writes mission state.
const HYP_NODE = {"H-ACK": "hack", "H-QUEUE": "hqueue"};
const HYP_BOUNDS = {
  "H-QUEUE": ["Assigned within 1 hour"],
  "H-ACK": ["Valid acknowledgment within 4 hours",
            "Incomplete windows (insufficient evidence, not a confirmed miss)"],
};
const HYP_DIAG = {
  "H-QUEUE": [["feed-probe", "EXP-001 question names both hypotheses"],
              ["timestamp-audit", "procedure examines assignment timestamps against the 1-hour rule"]],
  "H-ACK": [["feed-probe", "EXP-001 question names both hypotheses"]],
};

function itemForRef(ref) {
  // Match record content (label, detail, provenance) but not the basis
  // attribution line, so stakeholder refs resolve to the contradiction
  // record that juxtaposes them instead of every interpretation citing them.
  const key = String(ref).toLowerCase();
  const hits = ITEMS.filter(it =>
    `${it.label} ${it.detail} ${it.provenance}`.toLowerCase().includes(key));
  return hits.length === 1 ? hits[0] : null;
}

function hypoPanel(h, def) {
  const node = nodeById(HYP_NODE[h.id]);
  const rels = EDGES.filter(e => e.s === node.id || e.t === node.id).map(e => {
    const other = nodeById(e.s === node.id ? e.t : e.s);
    const refBtns = (e.refs || []).map(r => {
      const it = itemForRef(r);
      return it ? `<button data-item="${esc(it.id)}">Inspect ${esc(it.label.slice(0, 40))}</button>`
                : `<span>ref: ${esc(r)}</span>`;
    }).join(" ");
    return `<li><span class="tag">${esc(e.type)} (${esc(e.status)})</span> `
      + `<strong>${esc(other.label)}</strong> — ${esc(e.note)}<br>${refBtns}</li>`;
  }).join("");
  const bounds = (HYP_BOUNDS[h.id] || []).map(label => {
    const c = ((M.evidence || {}).calculations || []).find(x => x.label === label);
    if (!c) return "";
    const it = ITEMS.find(x => x.kind === "metric" && x.label.startsWith(label));
    const btn = it ? ` <button data-item="${esc(it.id)}">Inspect calculation</button>` : "";
    return `<li><strong>${esc(c.label)}: ${esc(c.value)}</strong> (${esc(c.denominator)})${btn}</li>`;
  }).join("");
  const diags = (HYP_DIAG[h.id] || []).map(([id, basis]) => {
    const d = (M.diagnostics || []).find(x => x.id === id);
    if (!d) return "";
    const lock = d.needs_prediction ? "requires a locked prediction in the Field Mission" : "no prediction required";
    return `<li><strong>${esc(d.title)}</strong> — ${esc(basis)}; ${esc(lock)}.</li>`;
  }).join("");
  const vocab = ((def || {}).expected_findings || []).join(" / ");
  return `<div class="glass panel hyp-panel">`
    + `<h3>${esc(h.id)}</h3>`
    + `<p class="hyp-text">${esc(h.text)}</p>`
    + `<div class="insp-row"><dt>Status</dt><dd><span class="tag">unverified interpretation</span> No confidence score is assigned; agreement after testing would be support, not proof.</dd></div>`
    + `<h4>Relevant evidence</h4><ul class="rel-list">${rels}</ul>`
    + `<h4>Bounding calculations</h4><ul class="rel-list">${bounds}</ul>`
    + `<h4>Contradicting evidence</h4><p>None recorded in the backend record for this hypothesis.</p>`
    + `<h4>Diagnostic options</h4><ul class="rel-list">${diags}</ul>`
    + (vocab ? `<p class="refs">Prediction vocabulary: ${esc(vocab)} (options, not the result).</p>` : "")
    + `<p><button data-hyp="${esc(h.id)}">Inspect ${esc(h.id)} in context →</button></p>`
    + `</div>`;
}

function renderLab() {
  const def = (M.experiment || {}).definition || {};
  document.getElementById("mcLab").innerHTML =
    `<div class="hyp-grid">${((def.hypotheses) || []).map(h => hypoPanel(h, def)).join("")}</div>`;
  document.querySelectorAll("#mcLab button[data-hyp]").forEach(b =>
    b.addEventListener("click", () => selectNode(HYP_NODE[b.dataset.hyp])));
  document.querySelectorAll("#mcLab button[data-item]").forEach(b =>
    b.addEventListener("click", () => select(b.dataset.item)));
  const questions = (M.evidence || {}).unresolved_questions || [];
  document.getElementById("mcLabQuestions").innerHTML = questions.length
    ? `<ul>${questions.map(q => `<li>${esc(q)}</li>`).join("")}</ul>`
    : `<p>None recorded.</p>`;
  renderLabStatus();
}

function renderLabStatus() {
  const box = document.getElementById("mcLabStatus");
  const exp = M.experiment;
  if (!exp) {
    box.innerHTML = `<p>Diagnostic status unavailable: no experiment record in this response.</p>`;
    return;
  }
  const diagId = (M.mission || {}).diagnostic;
  const diag = (M.diagnostics || []).find(d => d.id === diagId);
  const pred = exp.prediction || null;
  const out = exp.outcome || null;
  const assess = exp.assessment || null;
  const steps = [
    ["Diagnostic selected", diag ? diag.title : "No diagnostic selected"],
    ["Prediction locked", pred
      ? `Locked ${pred.origin} prediction: ${pred.hypothesis_id} expects ${pred.expected_finding}`
      : "No prediction locked"],
    ["Outcome revealed", out
      ? `Revealed finding: ${out.finding}`
      : "Withheld — reveal only in the Field Mission after a prediction is locked"],
    ["Assessment", assess
      ? `Deterministic result: ${assess.result}`
      : "Not assessed"],
  ];
  const firstOpen = steps.findIndex((_, i) =>
    (i === 0 && !diag) || (i === 1 && !pred) || (i === 2 && !out) || (i === 3 && !assess));
  box.innerHTML = `<ol class="steps">` + steps.map(([title, detail], i) => {
    const cls = firstOpen === -1 ? "done" : (i < firstOpen ? "done" : (i === firstOpen ? "current" : "todo"));
    return `<li class="${cls}">${esc(title)}: ${esc(detail)}</li>`;
  }).join("") + `</ol>`
    + `<p class="refs">Read-only: locking, reveal, assessment, and approval happen in the Field Mission.</p>`;
}

// ---- Decision Room (MC-004, read-only) ----
// Status cards reflect live backend state. The proposal panel renders only
// what GET /api/mission/proposal returns (409 = no proposal yet); nothing
// is constructed client-side. No approval, reveal, or execution actions.
let P = null;

function decisionContext() {
  const diag = (M.diagnostics || []).find(d => d.id === (M.mission || {}).diagnostic);
  const exp = (M.experiment || {}).status || "unknown";
  const run = (M.mission || {}).mission_run_id || "unknown run";
  return `case-001 · run ${run} · diagnostic: ${diag ? diag.title : "none selected"} · experiment: ${exp}`;
}

function renderDecision() {
  document.getElementById("mcDecisionContext").textContent = decisionContext();
  const ev = M.evidence || {};
  const nCalc = (ev.calculations || []).length;
  const nContra = (ev.contradictions || []).length;
  const nOpen = (ev.unresolved_questions || []).length;
  const assess = (M.experiment || {}).assessment || null;
  const interven = (M.mission || {}).intervention || null;
  const contra = ITEMS.find(it => it.kind === "contradiction");
  const cards = [
    ["Evidence completeness",
     `${nCalc} deterministic calculations · ${nContra} contradictions · ${nOpen} open questions`,
     nOpen ? "open questions remain" : "no open questions recorded",
     (contra ? `<button data-room="${esc(contra.id)}">Inspect contradiction</button> ` : "")
     + `<button data-room-goto="view-investigation">Open evidence ledger →</button>`],
    ["Root-cause determination",
     assess ? `Deterministic assessment: ${assess.result}. ${assess.reason}` : "Not established — H-ACK and H-QUEUE remain competing interpretations",
     assess ? "single-case support, not an organization-wide root cause" : "no causal claim made",
     `<button data-room-goto="view-hypothesis">Compare hypotheses →</button>`],
    ["Human authorization",
     interven ? `${interven.decision} recorded on ${interven.proposal.proposal_id} ${interven.proposal.version} — executed: ${interven.executed}` : "No decision recorded",
     interven ? "decision bound to proposal version" : "approval happens in the Field Mission",
     `<a class="field-link" href="mission.html">Open the Field Mission →</a>`],
  ];
  document.getElementById("mcDecisionCards").innerHTML = cards.map(([title, body, state, nav]) =>
    `<div class="glass panel status-card"><h3>${esc(title)}</h3><p>${esc(body)}</p>`
    + `<p class="refs">${esc(state)}</p><p>${nav}</p></div>`).join("");
  renderProposal();
  renderVerify();
  renderHumanReview();
}

function openEvidence(id) {
  if (ITEMS.some(it => it.id === id)) {
    showView("view-investigation");
    select(id);
  }
}

function roomClick(event) {
  const go = event.target && event.target.closest ? event.target.closest("[data-room-goto]") : null;
  if (go) { showView(go.dataset.roomGoto); return; }
  const btn = event.target && event.target.closest ? event.target.closest("[data-room]") : null;
  if (btn) openEvidence(btn.dataset.room);
}

function asList(x) { return Array.isArray(x) ? x : [x]; }

function refChips(refs) {
  return (refs || []).map(r => {
    const it = itemForRef(r);
    return it ? `<button data-room="${esc(it.id)}">Inspect ${esc(it.label.slice(0, 40))}</button>`
              : `<span class="refs">ref: ${esc(r)}</span>`;
  }).join(" ");
}

function renderProposal() {
  const box = document.getElementById("mcProposal");
  if (!P) {
    box.innerHTML = `<p>No proposal exists yet. A proposal appears only after the assessment (feed probe) or the audit result, through the Field Mission.</p>`
      + `<p><button data-room-goto="view-investigation">Review evidence in the Investigation workspace →</button></p>`;
    return;
  }
  box.innerHTML = `<div class="insp-row"><dt>Proposal</dt><dd><strong>${esc(P.proposal_id)} ${esc(P.version)}</strong> — ${esc(P.text)}</dd></div>`
    + `<div class="insp-row"><dt>Scope</dt><dd>${esc(P.scope)}</dd></div>`
    + `<div class="insp-row"><dt>Risks</dt><dd><ul>${(P.risks || []).map(r => `<li>${esc(r)}</li>`).join("")}</ul></dd></div>`
    + `<div class="insp-row"><dt>Supporting evidence</dt><dd>${refChips((P.supporting_evidence || {}).refs)}</dd></div>`
    + `<div class="insp-row"><dt>Approval note</dt><dd>${esc(P.approval_note)}</dd></div>`;
}

function renderVerify() {
  const box = document.getElementById("mcVerify");
  if (!P) {
    box.innerHTML = `<p>Unavailable until a proposal exists. The standing rule: approval never executes anything; verify through the Field Mission report.</p>`;
    return;
  }
  box.innerHTML = `<div class="insp-row"><dt>Stop conditions</dt><dd><ul>${asList(P.stop_conditions || []).map(s => `<li>${esc(s)}</li>`).join("")}</ul></dd></div>`
    + `<div class="insp-row"><dt>Next role</dt><dd>${esc(P.next_role)}</dd></div>`
    + `<div class="insp-row"><dt>Other open problems</dt><dd><ul>${asList(P.other_open_problems || []).map(s => `<li>${esc(s)}</li>`).join("")}</ul></dd></div>`
    + `<div class="insp-row"><dt>Reversibility</dt><dd>${esc(P.reversible_basis)}</dd></div>`;
}

function renderHumanReview() {
  const box = document.getElementById("mcHumanReview");
  const interven = (M.mission || {}).intervention || null;
  if (!interven) {
    box.innerHTML = `<p>No decision recorded. Approve, reject, or defer with a stated rationale in the Field Mission.</p>`;
    return;
  }
  box.innerHTML = `<div class="insp-row"><dt>Decision</dt><dd><strong>${esc(interven.decision)}</strong> on ${esc(interven.proposal.proposal_id)} ${esc(interven.proposal.version)}</dd></div>`
    + `<div class="insp-row"><dt>Rationale</dt><dd>${esc(interven.note)}</dd></div>`
    + `<div class="insp-row"><dt>Executed</dt><dd>${esc(interven.executed)}</dd></div>`;
}

function showView(id) {
  document.querySelectorAll(".mcview").forEach(s => s.classList.toggle("active", s.id === id));
  document.querySelectorAll("button[data-view]").forEach(b =>
    b.setAttribute("aria-current", String(b.dataset.view === id)));
}
document.querySelectorAll("button[data-view]").forEach(b =>
  b.addEventListener("click", () => showView(b.dataset.view)));

async function boot() {
  let res;
  try {
    res = await fetch("/api/mission");
  } catch (e) {
    fail("Mission Control unavailable: the backend could not be reached. No data was loaded and nothing was changed.");
    document.getElementById("mcLoading").textContent = "Unavailable.";
    return;
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.stages) {
    fail(data.message || data.error || "Mission Control unavailable: unexpected backend response.");
    document.getElementById("mcLoading").textContent = "Unavailable.";
    return;
  }
  M = data;
  ITEMS = buildItems();
  try {
    const pres = await fetch("/api/mission/proposal");
    if (pres.ok) P = await pres.json().catch(() => null);
  } catch (e) {
    P = null;
  }
  renderOverview();
  renderSummary();
  renderGraph();
  renderIllust();
  renderLab();
  renderDecision();
  renderChaosFlow();
  renderChaosList();
  renderChaosTabs();
  renderList(true);
}

const CHAOS_SUMMARY_FILES = [
  "CHS-ASSIGN-01.baseline.json", "CHS-ASSIGN-01.injected.json",
  "CHS-ACK-01.baseline.json", "CHS-ACK-01.injected.json",
  "CHS-WINDOW-01.baseline.json", "CHS-WINDOW-01.injected.json",
];
const CHAOS_RECOVERY_FILES = [
  "CHS-ASSIGN-01.recovery.json", "CHS-ACK-01.recovery.json",
  "CHS-WINDOW-01.recovery.json",
];
const CHAOS_LOADED = {};

function renderChaosTabs() {
  document.querySelectorAll("#view-chaos button[data-ctab]").forEach(b =>
    b.addEventListener("click", () => showChaosTab(b.dataset.ctab)));
}

async function showChaosTab(name) {
  ["scenario", "results", "evaluation", "recovery"].forEach(n => {
    document.getElementById("ctab" + n[0].toUpperCase() + n.slice(1)).hidden =
      (n !== name);
  });
  document.querySelectorAll("#view-chaos button[data-ctab]").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.ctab === name)));
  if (name === "results" && !CHAOS_LOADED.results) {
    CHAOS_LOADED.results = true;
    await loadResultSummary();
  }
  if (name === "evaluation" && !CHAOS_LOADED.evaluation) {
    CHAOS_LOADED.evaluation = true;
    await loadEvalReport();
  }
  if (name === "recovery" && !CHAOS_LOADED.recovery) {
    CHAOS_LOADED.recovery = true;
    await loadRecoveryRecords();
  }
}

async function chaosArtifact(name) {
  try {
    const res = await fetch(`chaos-results/${name}`);
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

function metricText(numer, denom) {
  if (numer === null || numer === undefined || !denom) return "Not defined";
  return `${(numer / denom * 100).toFixed(1)}% (${esc(numer)} of ${esc(denom)})`;
}

async function loadResultSummary() {
  const box = document.getElementById("mcResultSummary");
  box.innerHTML = `<p class="refs">Loading…</p>`;
  const rows = [];
  for (const file of CHAOS_SUMMARY_FILES) {
    const r = await chaosArtifact(file);
    if (!r || r.schema !== "ChaosSimulationResultV1"
        || r.classification !== "synthetic simulation"
        || r.recovery !== "not-tested" || typeof r.run_id !== "string") {
      box.innerHTML = `<p>Artifact ${esc(file)} invalid — summary not displayed.</p>`;
      return;
    }
    const flagged = ((r.detector || {}).flagged || []).join(", ") || "nothing flagged";
    rows.push(`<tr><td>${esc(r.scenario_id)}</td><td>${esc(r.variant)}</td>`
      + `<td>${esc(flagged)}</td>`
      + `<td>${esc(r.expected_vs_observed ? r.expected_vs_observed.agreement : "?")}</td>`
      + `<td>${esc(r.run_id.slice(0, 12))}…</td></tr>`);
  }
  box.innerHTML = `<table class="ctable"><thead><tr><th>Scenario</th><th>Variant</th>`
    + `<th>Detector findings</th><th>Agreement</th><th>Run</th></tr></thead>`
    + `<tbody>${rows.join("")}</tbody></table>`
    + `<p class="refs">Previously generated results — viewing never executes a simulation. Recovery: not tested.</p>`;
}

function checkEvalReport(r) {
  if (!r || r.schema !== "ChaosEvaluationReportV1") return false;
  const c = r.confusion || {};
  if (!["true_positives", "false_positives", "true_negatives",
        "false_negatives"].every(k => Number.isInteger(c[k]))) return false;
  const m = r.metrics || {};
  for (const k of ["precision", "recall", "false_positive_rate",
                   "false_negative_rate"]) {
    if (!(typeof m[k] === "number" || m[k] === null)) return false;
    if (!Number.isInteger(m[`${k}_denominator`])) return false;
  }
  return Array.isArray(r.judgments) && typeof r.scope === "string";
}

async function loadEvalReport() {
  const box = document.getElementById("mcEvalReport");
  box.innerHTML = `<p class="refs">Loading…</p>`;
  const r = await chaosArtifact("chaos-eval-report.json");
  if (!checkEvalReport(r)) {
    box.innerHTML = `<p>Evaluation artifact invalid — not displayed.</p>`;
    return;
  }
  const c = r.confusion, m = r.metrics;
  const detail = (r.judgments || []).map(j =>
    `<details><summary>${esc(j.case)} — ${esc(j.status)} (${esc(j.rule || "no rule")})</summary>`
    + `<div class="insp-row"><dt>Expected</dt><dd>${esc(JSON.stringify(j.expected_flags !== undefined ? j.expected_flags : j.detail || ""))}</dd></div>`
    + `<div class="insp-row"><dt>Observed</dt><dd>${esc(JSON.stringify(j.observed_flags !== undefined ? j.observed_flags : ""))}</dd></div>`
    + `<div class="insp-row"><dt>References</dt><dd>${esc((j.refs || []).join(", "))}</dd></div>`
    + `</details>`).join("");
  const unavailable = (r.unavailable || []).map(u =>
    `<li>${esc(u.case)} — ${esc(u.reason)}</li>`).join("");
  const robustness = Object.entries(r.robustness || {}).map(([k, v]) =>
    `<li>${esc(k)}: ${esc(v)}</li>`).join("");
  box.innerHTML = `<p><span class="tag">Offline synthetic evaluation — previously generated report</span></p>`
    + `<p class="refs">Validated at creation, schema-checked at display. A content hash alone is not proof of authenticity. Passing here does not establish production reliability.</p>`
    + `<table class="ctable"><tbody>`
    + `<tr><th>True positives</th><td>${esc(c.true_positives)}</td></tr>`
    + `<tr><th>False positives</th><td>${esc(c.false_positives)}</td></tr>`
    + `<tr><th>True negatives</th><td>${esc(c.true_negatives)}</td></tr>`
    + `<tr><th>False negatives</th><td>${esc(c.false_negatives)}</td></tr>`
    + `<tr><th>Precision</th><td>${esc(m.precision === null ? "Not defined" : metricText(c.true_positives, m.precision_denominator))}</td></tr>`
    + `<tr><th>Recall</th><td>${esc(m.recall === null ? "Not defined" : metricText(c.true_positives, m.recall_denominator))}</td></tr>`
    + `<tr><th>False-positive rate</th><td>${esc(m.false_positive_rate === null ? "Not defined" : metricText(c.false_positives, m.false_positive_rate_denominator))}</td></tr>`
    + `<tr><th>False-negative rate</th><td>${esc(m.false_negative_rate === null ? "Not defined" : metricText(c.false_negatives, m.false_negative_rate_denominator))}</td></tr>`
    + `</tbody></table>`
    + `<div class="insp-row"><dt>Incomplete-window safety</dt><dd>${esc(r.safety.correct)} of ${esc(r.safety.cases)} correct</dd></div>`
    + `<div class="insp-row"><dt>Indeterminate cases</dt><dd>${esc(r.indeterminate)}</dd></div>`
    + `<div class="insp-row"><dt>Unavailable cases</dt><dd><ul>${unavailable}</ul></dd></div>`
    + `<div class="insp-row"><dt>Robustness controls</dt><dd><ul>${robustness}</ul></dd></div>`
    + `<h4>Per-case judgments</h4>${detail}`;
}

const CHAOS_RECOVERY_ALLOWLIST = {
  "CHS-ASSIGN-01": ["restore-assignments"],
  "CHS-ACK-01": ["reconcile-feed"],
  "CHS-WINDOW-01": ["none-available"],
};

function checkRecoveryRecord(r) {
  if (!r || r.schema !== "ChaosRecoveryResultV1") return false;
  if (!CHAOS_RECOVERY_ALLOWLIST[r.scenario_id]
      || !CHAOS_RECOVERY_ALLOWLIST[r.scenario_id].includes(r.repair_id)) return false;
  if (!["verified", "failed", "inconclusive", "not-tested"].includes(r.status)) return false;
  if (r.status === "verified") {
    if (r.target_resolved !== true) return false;
    const reg = r.regression || {};
    if (!Object.keys(reg).length || !Object.values(reg).every(Boolean)) return false;
  }
  if (r.status === "not-tested" && !r.note) return false;
  return typeof r.run_id === "string";
}

async function loadRecoveryRecords() {
  const box = document.getElementById("mcRecoveryRecords");
  box.innerHTML = `<p class="refs">Loading…</p>`;
  const panels = [];
  for (const file of CHAOS_RECOVERY_FILES) {
    const r = await chaosArtifact(file);
    if (!checkRecoveryRecord(r)) {
      box.innerHTML = `<p>Artifact ${esc(file)} invalid or contradictory — not displayed.</p>`;
      return;
    }
    const reg = Object.entries(r.regression || {}).map(([k, v]) =>
      `<li>${esc(k)}: ${esc(v)}</li>`).join("") || "<li>no regression checks (not tested)</li>";
    panels.push(`<div class="glass panel"><h3>${esc(r.scenario_id)} — ${esc(r.repair_id)}</h3>`
      + `<div class="insp-row"><dt>Status</dt><dd><span class="tag">${esc(r.status)}</span></dd></div>`
      + `<div class="insp-row"><dt>Fixture</dt><dd>${esc(r.fixture_id)}</dd></div>`
      + `<div class="insp-row"><dt>Repair</dt><dd>${esc((r.repair || {}).description || "")}<br>${esc(((r.repair || {}).changes || []).join("; "))}</dd></div>`
      + `<div class="insp-row"><dt>Pre-repair findings</dt><dd>${esc((r.pre_repair_flags || []).join(", ") || "none")}</dd></div>`
      + `<div class="insp-row"><dt>Post-repair findings</dt><dd>${esc((r.post_repair_flags || []).join(", ") || (r.status === "not-tested" ? "not measured" : "none"))}</dd></div>`
      + `<div class="insp-row"><dt>Target resolved</dt><dd>${esc(r.target_resolved)}</dd></div>`
      + `<div class="insp-row"><dt>Regression checks</dt><dd><ul>${reg}</ul></dd></div>`
      + (r.note ? `<div class="insp-row"><dt>Note</dt><dd>${esc(r.note)}</dd></div>` : "")
      + `<p class="refs">Run ${esc(r.run_id.slice(0, 12))}… · refs: ${esc((r.refs || []).join(", "))}</p>`
      + `</div>`);
  }
  box.innerHTML = panels.join("")
    + `<p class="refs">Verified means only: the specified synthetic repair passed its defined post-repair checks — never production recovery.</p>`;
}

document.getElementById("mcDecisionCards").addEventListener("click", roomClick);
document.getElementById("mcProposal").addEventListener("click", roomClick);

// ---- Chaos Lab (MC-005a, frontend-first, synthetic-only) ----
// A static catalog of fictional failure scenarios. Nothing here runs,
// measures, or verifies anything: every scenario is labeled synthetic,
// every result reads "Not run", and fixture-backed rows reuse the
// read-only evidence ledger for inspection only.
const CHAOS_FLOW = ["Intake", "Assignment", "Notification", "Acknowledgment"];
const CHAOS_SCENARIOS = [
  {id: "CHS-ASSIGN-01", title: "Assignment backlog",
   fault: "Urgent cases wait unassigned during queue spikes.",
   signal: "Eligible event rows with no assignment timestamp.",
   evidence: [{text: "Assigned within 1 hour (5 of 7 eligible)", metric: "Assigned within 1 hour"},
              {text: "Dispatcher/manager assignment contradiction", ref: "dispatcher"}],
   criterion: "Recompute the 1-hour rule over events.csv; backlog confirmed only if unassigned rows recur outside any single overnight window.",
   availability: "Not executable here. Related Field Mission diagnostic: timestamp-audit (human-gated, no prediction required).",
   preconds: "Fictional spike window plus complete observation windows for the affected cases.",
   test: "Reconcile assignment timestamps against the 1-hour policy rule.",
   falsify: "All eligible cases assigned within 1 hour would rule a general backlog out (single unassigned cases would remain unexplained).",
   safety: "Read-only arithmetic; no production contact."},
  {id: "CHS-ACK-01", title: "Missing acknowledgment in event feed",
   fault: "Acknowledgments recorded at the source never reach the events feed.",
   signal: "Assigned cases with complete windows but no acknowledgment.",
   evidence: [{text: "Valid acknowledgment within 4 hours (1 of 7 eligible)", metric: "Valid acknowledgment within 4 hours"},
              {text: "Confirmed deadline misses (3 cases)", metric: "Confirmed deadline misses"}],
   criterion: "A source-log entry with no feed counterpart, established through a locked prediction and authorized reveal.",
   availability: "Not executable here. Related Field Mission diagnostic: EXP-001 feed-probe (locked prediction required).",
   preconds: "An assigned case with a complete observation window and no feed acknowledgment.",
   test: "Source-log probe for the missing acknowledgment.",
   falsify: "A source log with no acknowledgment either would weaken a feed-gap claim for that case.",
   safety: "Read-only source check; no production contact."},
  {id: "CHS-NOTIFY-01", title: "Delayed notification delivery",
   fault: "Notifications about urgent referrals arrive late.",
   signal: "Notification timestamps later than the acknowledgment deadline.",
   evidence: [{text: "No notification timestamps exist in the case-001 fixtures — nothing to test against."}],
   criterion: "Unavailable: the fixtures record no notification events, so no verification criterion can be evaluated.",
   availability: "Not executable here — required evidence absent from fixtures.",
   preconds: "Notification event records, which do not exist here.",
   test: "No test can be constructed from the available evidence.",
   falsify: "Not applicable without evidence.",
   safety: "Nothing to run."},
  {id: "CHS-WINDOW-01", title: "Incomplete observation window",
   fault: "A case looks unacknowledged only because its window had not closed.",
   signal: "Eligible rows whose window closes before created_at + 4h.",
   evidence: [{text: "Open question: incomplete windows (case-005, case-006)", ref: "case-005"}],
   criterion: "window_close_at >= created_at + 4h before any miss may be counted; otherwise inconclusive.",
   availability: "Not executable here. Deterministic rule already applied in the evidence ledger.",
   preconds: "Eligible cases with truncated windows.",
   test: "Recompute window completeness per the 4-hour rule.",
   falsify: "A closed window with no acknowledgment moves the case to confirmed-miss candidacy, not to this scenario.",
   safety: "Read-only arithmetic; no production contact."},
  {id: "CHS-ORDER-01", title: "Inconsistent event ordering",
   fault: "Acknowledgment recorded before assignment indicates a feed or clock problem.",
   signal: "Rows where assigned_at < created_at or ack_at < assigned_at.",
   evidence: [{text: "Open question: case-008 anomaly needs a source check", ref: "case-008"}],
   criterion: "Anomalous sequences are flagged for source check and never counted as confirmed misses.",
   availability: "Not executable here. Deterministic rule already applied in the evidence ledger.",
   preconds: "Event rows with ordering anomalies.",
   test: "Flag anomalous sequences per the ordering rule.",
   falsify: "Consistent ordering across all rows would leave this scenario with no instances.",
   safety: "Read-only arithmetic; no production contact."},
];

function resolveChaosEvidence(e) {
  if (e.metric) {
    const it = ITEMS.find(x => x.kind === "metric" && x.label.startsWith(e.metric));
    return it ? {item: it} : null;
  }
  if (e.ref) {
    const it = itemForRef(e.ref);
    return it ? {item: it} : null;
  }
  return null;
}

function renderChaosFlow() {
  const svg = document.getElementById("mcChaosFlow");
  svg.innerHTML = CHAOS_FLOW.map((s, i) => {
    const x = 20 + i * 155;
    const link = i < CHAOS_FLOW.length - 1
      ? `<line class="chaos-link" x1="${x + 120}" y1="80" x2="${x + 155}" y2="80"/>` : "";
    return `<g class="chaos-node"><rect x="${x}" y="55" width="120" height="50" rx="10"/>`
      + `<text x="${x + 60}" y="83">${esc(s)}</text></g>` + link;
  }).join("");
}

function renderChaosList() {
  document.getElementById("mcScenarioList").innerHTML =
    `<ul class="rel-list">` + CHAOS_SCENARIOS.map(s =>
      `<li><button data-scn="${esc(s.id)}" aria-current="false"><span class="tag">Synthetic scenario</span> ${esc(s.id)} — ${esc(s.title)}</button></li>`).join("") + `</ul>`
    + `<p class="refs">Candidate demonstrations, not claims that failures occurred. No scenario executes here.</p>`;
  document.querySelectorAll("#mcScenarioList button[data-scn]").forEach(b =>
    b.addEventListener("click", () => selectScenario(b.dataset.scn)));
}

function selectScenario(id) {
  const s = CHAOS_SCENARIOS.find(x => x.id === id);
  if (!s) return;
  document.querySelectorAll("#mcScenarioList button[data-scn]").forEach(b =>
    b.setAttribute("aria-current", String(b.dataset.scn === id)));
  const rows = s.evidence.map(e => {
    const hit = resolveChaosEvidence(e);
    const link = hit
      ? ` <button data-item="${esc(hit.item.id)}">Inspect record</button> <span class="tag">Existing deterministic fixture</span>`
      : ` <span class="tag">No fixture record</span>`;
    return `<li>${esc(e.text)}${link}</li>`;
  }).join("");
  document.getElementById("mcScenarioDetail").innerHTML =
    `<h3>${esc(s.id)} — ${esc(s.title)} <span class="tag">Synthetic scenario</span></h3>`
    + `<div class="insp-row"><dt>Hypothesized failure</dt><dd>${esc(s.fault)}</dd></div>`
    + `<div class="insp-row"><dt>Preconditions</dt><dd>${esc(s.preconds)}</dd></div>`
    + `<div class="insp-row"><dt>Proposed test</dt><dd>${esc(s.test)}</dd></div>`
    + `<div class="insp-row"><dt>Expected observable signal</dt><dd>${esc(s.signal)}</dd></div>`
    + `<div class="insp-row"><dt>Falsification</dt><dd>${esc(s.falsify)}</dd></div>`
    + `<div class="insp-row"><dt>Safety boundaries</dt><dd>${esc(s.safety)}</dd></div>`
    + `<div class="insp-row"><dt>Availability</dt><dd>${esc(s.availability)}</dd></div>`
    + `<h4>Evidence needed</h4><ul class="rel-list">${rows}</ul>`
    + `<div class="insp-row"><dt>Verification criterion</dt><dd>${esc(s.criterion)}</dd></div>`
    + `<h4>Detection and recovery</h4>`
    + `<div class="insp-row"><dt>Detection condition</dt><dd>${esc(s.signal)}</dd></div>`
    + `<div class="insp-row"><dt>Observed detection</dt><dd>None — scenario not run.</dd></div>`
    + `<div class="insp-row"><dt>Recovery action</dt><dd>None proposed — nothing executed.</dd></div>`
    + `<div class="insp-row"><dt>Verified recovery evidence</dt><dd>None. Recovery not established.</dd></div>`;
  document.querySelectorAll("#mcScenarioDetail button[data-item]").forEach(b =>
    b.addEventListener("click", () => select(b.dataset.item)));
  renderChaosVariants(s);
}

function renderChaosVariants(s) {
  const box = document.getElementById("mcScenarioDetail");
  const wrap = document.createElement("div");
  wrap.innerHTML =
    `<h4>Previously generated result</h4>`
    + `<p><button data-variant="baseline" aria-pressed="false">Baseline result</button> `
    + `<button data-variant="injected" aria-pressed="false">Injected result</button></p>`
    + `<div id="mcChaosResult"><p class="refs">No variant selected. Viewing a result does not execute a simulation.</p></div>`;
  box.appendChild(wrap);
  wrap.querySelectorAll("button[data-variant]").forEach(b =>
    b.addEventListener("click", () => {
      CHAOS_RUN_SEL = {scn: s.id, variant: b.dataset.variant};
      selectChaosVariant(s.id, b.dataset.variant);
    }));
  const runRow = document.createElement("div");
  runRow.innerHTML =
    `<p><button data-chaos-run="1">Run this scenario now (synthetic, offline)</button></p>`
    + `<div id="mcChaosExecuted"><p class="refs">No run yet. Execution requires this explicit button — never page load or selection.</p></div>`;
  box.appendChild(runRow);
  runRow.querySelectorAll("[data-chaos-run]").forEach(b =>
    b.addEventListener("click", () => runChaosScenario(s.id)));
}

let CHAOS_RUN_SEL = null;

async function runChaosScenario(scnId) {
  const box = document.getElementById("mcChaosExecuted");
  const btn = document.querySelector(`#mcScenarioDetail [data-chaos-run]`);
  const sel = (CHAOS_RUN_SEL && CHAOS_RUN_SEL.scn === scnId) ? CHAOS_RUN_SEL.variant : null;
  if (!sel) {
    box.innerHTML = `<p>Choose Baseline or Injected first.</p>`;
    return;
  }
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "Running…";
  box.innerHTML = `<p>Running synthetic simulation…</p>`;
  let data = null;
  try {
    const res = await fetch("/api/chaos/run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({scenario_id: scnId, variant: sel}),
    });
    data = await res.json().catch(() => null);
    if (!res.ok || !data || data.ran !== true || !data.result) {
      throw new Error((data && data.error) || "rejected");
    }
  } catch (e) {
    box.innerHTML = `<p>Run rejected (${esc(e && e.message || e)}). Nothing was executed.</p>`;
    btn.disabled = false;
    btn.textContent = label;
    return;
  }
  const r = data.result;
  if (r.schema !== "ChaosSimulationResultV1" || r.scenario_id !== scnId
      || r.classification !== "synthetic simulation"
      || r.recovery !== "not-tested" || typeof r.run_id !== "string") {
    box.innerHTML = `<p>Returned result invalid — not displayed.</p>`;
    btn.disabled = false;
    btn.textContent = label;
    return;
  }
  let baseFlags = null, baseClass = null;
  if (sel === "injected") {
    try {
      const res = await fetch(`chaos-results/${scnId}.baseline.json`);
      if (res.ok) {
        const base = await res.json();
        if (base && base.scenario_id === scnId && base.detector) {
          baseFlags = base.detector.flagged || [];
          baseClass = {};
          Object.entries(base.observations || {}).forEach(([c, m]) => {
            baseClass[c] = m.classification;
          });
        }
      }
    } catch (e) {
      baseFlags = null;
    }
  }
  box.innerHTML = `<p><span class="tag">Newly executed synthetic run — not a historical artifact</span></p>`
    + `<p class="refs">Executed locally at ${esc(data.executed_at)} (server clock, informational). Recovery: not tested — not established.</p>`
    + chaosResultHtml(r, baseFlags, baseClass);
  btn.disabled = false;
  btn.textContent = label;
}

async function selectChaosVariant(scnId, variant) {
  document.querySelectorAll("#mcScenarioDetail button[data-variant]").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.variant === variant)));
  const box = document.getElementById("mcChaosResult");
  let result = null;
  try {
    const res = await fetch(`chaos-results/${scnId}.${variant}.json`);
    if (!res.ok) throw new Error("missing artifact");
    result = await res.json();
  } catch (e) {
    result = null;
  }
  if (!result || result.schema !== "ChaosSimulationResultV1"
      || result.scenario_id !== scnId
      || result.classification !== "synthetic simulation"
      || result.recovery !== "not-tested"
      || typeof result.run_id !== "string") {
    box.innerHTML = `<p>Artifact invalid — not displayed.</p>`;
    return;
  }
  let baseFlags = null, baseClass = null;
  if (variant === "injected") {
    try {
      const res = await fetch(`chaos-results/${scnId}.baseline.json`);
      if (res.ok) {
        const base = await res.json();
        if (base && base.scenario_id === scnId && base.detector) {
          baseFlags = base.detector.flagged || [];
          baseClass = {};
          Object.entries(base.observations || {}).forEach(([c, m]) => {
            baseClass[c] = m.classification;
          });
        }
      }
    } catch (e) {
      baseFlags = null;
    }
  }
  box.innerHTML = chaosResultHtml(result, baseFlags, baseClass);
}

function chaosResultHtml(r, baseFlags, baseClass) {
  const flagged = (r.detector && r.detector.flagged) || [];
  const obs = r.observations || {};
  const rows = Object.entries(obs).map(([c, m]) =>
    `<li><strong>${esc(c)}</strong> — ${esc(m.classification || "unclassified")}`
    + Object.entries(m).filter(([k]) => k !== "classification").map(([k, v]) =>
      ` · ${esc(k)}: ${esc(v)}`).join("") + `</li>`).join("");
  const baseRows = Object.entries(r.baseline || {}).map(([c, m]) =>
    `<li><strong>${esc(c)}</strong> — ${esc(JSON.stringify(m))}</li>`).join("");
  let attribution = "";
  if (baseFlags !== null) {
    const fresh = flagged.filter(c => !baseFlags.includes(c));
    const pre = flagged.filter(c => baseFlags.includes(c));
    const changed = Object.keys(obs).filter(c =>
      baseClass && baseClass[c] && baseClass[c] !== obs[c].classification);
    attribution = `<div class="insp-row"><dt>Newly introduced findings</dt>`
      + `<dd>${fresh.length ? esc(fresh.join(", ")) : "none"}</dd></div>`
      + `<div class="insp-row"><dt>Preexisting findings</dt>`
      + `<dd>${pre.length ? esc(pre.join(", ")) : "none"}</dd></div>`
      + `<div class="insp-row"><dt>Classification changes vs baseline</dt>`
      + `<dd>${changed.length ? esc(changed.map(c => `${c}: ${baseClass[c]} → ${obs[c].classification}`).join("; ")) : "none"}</dd></div>`;
  }
  const evo = r.expected_vs_observed || {};
  return `<p><span class="tag">Offline synthetic simulation — previously generated result</span></p>`
    + `<p class="refs">Validated at artifact generation. Viewing this result does not execute a simulation. A content hash alone is not proof of authenticity.</p>`
    + `<div class="insp-row"><dt>Variant</dt><dd>${esc(r.variant)} · run ${esc(r.run_id.slice(0, 12))}…</dd></div>`
    + `<div class="insp-row"><dt>Status</dt><dd>${esc(r.status)}</dd></div>`
    + `<div class="insp-row"><dt>Fixture</dt><dd>${esc(r.synthetic_fixture_id)} (digest ${esc(String(r.fixture_digest).slice(0, 12))}…)</dd></div>`
    + `<div class="insp-row"><dt>Injected fault</dt><dd>${esc((r.injected_fault || {}).fault || "none")}</dd></div>`
    + `<h4>Baseline measurements</h4><ul class="rel-list">${baseRows}</ul>`
    + `<h4>Simulated observations</h4><ul class="rel-list">${rows}</ul>`
    + `<div class="insp-row"><dt>Detector findings</dt>`
    + `<dd>${esc((r.detector || {}).name || "unknown")}: ${flagged.length ? esc(flagged.join(", ")) : "nothing flagged"}</dd></div>`
    + `<div class="insp-row"><dt>Expected vs observed</dt>`
    + `<dd>agreement: ${esc(evo.agreement)} — ${esc(evo.note || "")}</dd></div>`
    + attribution
    + `<div class="insp-row"><dt>Source references</dt>`
    + `<dd>${(r.refs || []).map(x => esc(x)).join(", ")} (synthetic chaos fixtures — not Field Mission evidence)</dd></div>`
    + `<div class="insp-row"><dt>Recovery verification</dt><dd>not tested — not established.</dd></div>`;
}

document.getElementById("mcGraph").addEventListener("click", (event) => {
  const node = event.target && event.target.closest ? event.target.closest("[data-node]") : null;
  if (node) selectNode(node.dataset.node);
});
document.getElementById("mcGraph").addEventListener("keydown", (event) => {
  const node = event.target && event.target.closest ? event.target.closest("[data-node]") : null;
  if (node && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    selectNode(node.dataset.node);
  }
});
document.querySelectorAll("button[data-gtab]").forEach(b =>
  b.addEventListener("click", () => {
    const illust = b.dataset.gtab === "illustrative";
    document.getElementById("gtabEvidence").style.display = illust ? "none" : "";
    document.getElementById("gtabIllustrative").style.display = illust ? "" : "none";
    document.querySelectorAll("button[data-gtab]").forEach(x =>
      x.setAttribute("aria-pressed", String(x === b)));
  }));

document.getElementById("mcFilters").addEventListener("click", (event) => {
  const button = event.target && event.target.closest ? event.target.closest("button[data-filter]") : null;
  if (!button) return;
  FILTER = button.dataset.filter;
  renderList(true);
});
document.getElementById("mcSearch").addEventListener("input", (event) => {
  QUERY = event.target.value;
  renderList(false);
  const visible = visibleItems();
  if (visible.length && !visible.some(it => it.id === SELECTED)) {
    select(visible[0].id);
  }
});

boot();
