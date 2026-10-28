// Field-mission UI. No findings hardcoded: everything renders from /api data.
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function refs(rs) { return `<div class="refs">refs: ${(rs || []).map(esc).join(", ")}</div>`; }
const errBox = document.getElementById("error");
let M = null;

function fail(message) { errBox.style.display = "block"; errBox.textContent = message; }
function clear() { errBox.style.display = "none"; }

async function api(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  return {ok: res.ok, data};
}

function renderSteps(stages) {
  document.getElementById("steps").innerHTML = stages.map(s =>
    `<li class="${s.state}">${esc(s.stage)}: ${esc(s.state)}</li>`).join("");
}

function renderBrief() {
  const first = M.brief.split(/(?<=\.)\s/)[0];
  document.getElementById("brief").innerHTML =
    `<span class="tag">mission ${esc(M.mission_id)}</span> ${esc(first)}`
    + `<details class="ref"><summary>Full mission brief</summary><div>${esc(M.brief)}</div></details>`;
}

function renderStatus() {
  const current = (M.stages.find(s => s.state === "current") || {}).stage || "complete";
  const decided = M.mission.intervention ? ` · decision: ${esc(M.mission.intervention.decision)}` : "";
  const diag = M.mission.diagnostic ? ` · diagnostic: ${esc(M.mission.diagnostic)}` : "";
  document.getElementById("missionStatus").innerHTML =
    `<span class="tag">active stage: ${esc(current)}</span>${diag}${decided}`;
}

function renderHero() {
  const want = ["Eligible urgent cases", "Confirmed deadline misses", "Valid acknowledgment within 4 hours"];
  const cards = [];
  for (const label of want) {
    const c = (M.evidence.calculations || []).find(x => x.label === label);
    if (!c) continue;
    const gold = label === "Confirmed deadline misses" ? " gold" : "";
    cards.push(`<div class="card"><span class="figure${gold}">${esc(c.value)}</span>`
      + `<span class="caption">${esc(c.label)} · ${esc(c.denominator)}</span></div>`);
  }
  document.getElementById("heroMetrics").innerHTML = cards.join("");
}

function renderTimeline() {
  document.getElementById("timeline").innerHTML = M.stages.map(s =>
    `<li class="${s.state}">${esc(s.stage)} — ${esc(s.state)}</li>`).join("");
}

function renderConstraint() {
  document.getElementById("constraint").innerHTML = M.constraint.map(q =>
    `<div class="card"><span class="tag">formal policy claim · ${esc(q.doc_id)} [${q.start}-${q.end}]</span> “${esc(q.quote)}”</div>`).join("");
}

function renderEvidence() {
  const e = M.evidence;
  const parts = ["<h3>Deterministic calculations (no AI judgment)</h3>", '<div class="metrics">'];
  for (const c of e.calculations) {
    parts.push(`<div class="card"><strong>${esc(c.label)}: ${esc(c.value)}</strong><div class="refs">denominator: ${esc(c.denominator)} · rule: ${esc(c.rule)} · source: ${esc(c.source)}</div></div>`);
  }
  parts.push("</div>");
  parts.push("<h3>Source-backed contradictions</h3>");
  for (const k of (e.contradictions || [])) {
    parts.push(`<div class="card"><strong>${esc(k.title)}</strong><div>${esc(k.computed || "")}</div><div class="refs">${esc(k.status || "")}</div></div>`);
  }
  parts.push("<h3>Unresolved questions</h3><ul>" + (e.unresolved_questions || []).map(q => `<li>${esc(q)}</li>`).join("") + "</ul>");
  if (e.reported_observation_only) {
    parts.push(`<h3>Reported observation only (not a root cause)</h3><div class="card">${esc(JSON.stringify(e.reported_observation_only))}</div>`);
  }
  document.getElementById("evidence").innerHTML = parts.join("\n");
}

function renderHypotheses() {
  const parts = M.hypotheses.map(h =>
    `<div class="card"><span class="tag">${esc(h.status || "unverified interpretation")}</span> ${esc(h.text)}<div class="refs">basis: ${(h.basis || []).map(esc).join("; ")}</div></div>`);
  for (const h of ((M.experiment.definition || {}).hypotheses || [])) {
    const cls = h.id === "H-ACK" ? "hyp-hack" : (h.id === "H-QUEUE" ? "hyp-hqueue" : "");
    parts.push(`<div class="card hyp ${cls}"><span class="hyp-id">${esc(h.id)}</span> <span class="tag">unverified</span> ${esc(h.text)}</div>`);
  }
  document.getElementById("hypotheses").innerHTML = parts.join("\n");
}

function renderDiagnostics() {
  const chosen = M.mission.diagnostic;
  const box = document.getElementById("diagnostics");
  box.innerHTML = M.diagnostics.map(d => {
    const dis = chosen ? "disabled" : "";
    const mark = chosen === d.id ? `<span class="tag">chosen</span> ` : "";
    return `<div class="card">${mark}<strong>${esc(d.title)}</strong><div>${esc(d.description)}</div>`
      + `<div class="refs">${d.needs_prediction ? "withheld outcome — prediction required before reveal" : "deterministic — no prediction required"}</div>`
      + `<button data-diag="${esc(d.id)}" ${dis}>Choose this diagnostic</button></div>`;
  }).join("");
  box.querySelectorAll("button[data-diag]").forEach(b =>
    b.addEventListener("click", async () => {
      clear();
      const r = await api("/api/mission/diagnostic", {method: "POST",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify({choice: b.dataset.diag})});
      if (!r.ok) { fail(r.data.message || r.data.error); return; }
      await refresh();
      await showDiagResult();
    }));
}

async function showDiagResult() {
  const box = document.getElementById("diagResult");
  if (!M.mission.diagnostic) { box.innerHTML = ""; return; }
  const r = await api("/api/mission/diagnostic/result");
  if (!r.ok) { box.innerHTML = `<div class="card">${esc(r.data.message || r.data.error)}</div>`; return; }
  const d = r.data;
  if (d.requires_prediction) {
    box.innerHTML = `<div class="card"><span class="tag">withheld</span> ${esc(d.note)} Use section 6 to lock a prediction, then reveal.</div>`;
  } else {
    box.innerHTML = `<div class="card"><span class="tag">deterministic result</span> ${esc(d.finding)}<div class="refs">source: ${esc(d.source)} · ${esc(d.status)}</div></div>`;
    await refresh();
  }
}

function renderExperiment() {
  const x = M.experiment;
  const d = x.definition || {};
  const parts = [`<div class="card"><span class="tag">${esc(x.status)}</span> <strong>${esc(d.title || "EXP-001")}</strong> — ${esc(d.question || "")}<div class="refs">${esc(d.procedure || "")}</div><div class="refs">${esc(d.criteria_info || "")}</div></div>`];
  if (x.prediction) {
    const p = x.prediction;
    parts.push(`<div class="card"><span class="tag">locked prediction · ${esc(p.origin || "")}</span> ${esc(p.hypothesis_id)} expects ${esc(p.expected_finding)} — ${esc(p.expected_observation)}<div class="refs">locked_at: ${p.locked_at} · hash: ${esc(p.hash)}</div></div>`);
  }
  if (x.outcome) {
    parts.push(`<div class="card"><span class="tag">revealed result</span> ${esc(x.outcome.finding)} — ${esc(x.outcome.detail)}</div>`);
  }
  if (x.assessment) {
    parts.push(`<div class="card"><span class="tag">${esc(x.assessment.result)} · audit · read-only</span> ${esc(x.assessment.reason)}<div class="refs">agreement is support, not proof</div></div>`);
  }
  const canPredict = M.mission.diagnostic === "feed-probe" && x.status === "proposed";
  parts.push(`<div class="card"><strong>Lock a prediction</strong> (feed-probe path only; locked text cannot be edited)`
    + `<label>Hypothesis: <select id="pHyp"><option>H-ACK</option><option>H-QUEUE</option></select></label>`
    + `<label>Expected finding: <select id="pFinding"><option>ack-found</option><option>no-ack</option></select></label>`
    + `<label>Expected observation: <input id="pObs" size="60" value="The source log holds a case-003 acknowledgment missing from the feed."></label>`
    + `<label>Criteria: <input id="pCrit" size="60" value="ack-found supports H-ACK; no-ack supports H-QUEUE for the assigned class."></label>`
    + `<label>Evidence refs (comma-separated): <input id="pRefs" size="40" value="case-003, events.csv"></label>`
    + `<div><button id="pLock" ${canPredict ? "" : "disabled"}>Lock prediction</button>`
    + `<button id="pReveal" ${x.status === "prediction locked" ? "" : "disabled"}>Reveal outcome</button>`
    + `<button id="pAssess" ${x.status === "result revealed" ? "" : "disabled"}>Assess prediction</button></div></div>`);
  document.getElementById("experiment").innerHTML = parts.join("\n");
  const lock = document.getElementById("pLock");
  if (lock) lock.addEventListener("click", async () => {
    clear();
    const r = await api("/api/experiment/predict", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify({
        hypothesis_id: document.getElementById("pHyp").value,
        expected_finding: document.getElementById("pFinding").value,
        expected_observation: document.getElementById("pObs").value,
        criteria: document.getElementById("pCrit").value,
        refs: document.getElementById("pRefs").value.split(",").map(s => s.trim()).filter(Boolean)})});
    if (!r.ok) { fail(r.data.message || r.data.error); return; }
    await refresh();
  });
  const rev = document.getElementById("pReveal");
  if (rev) rev.addEventListener("click", async () => {
    clear();
    const r = await api("/api/experiment/reveal", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify({})});
    if (!r.ok) { fail(r.data.message || r.data.error); return; }
    await refresh();
  });
  const ass = document.getElementById("pAssess");
  if (ass) ass.addEventListener("click", async () => {
    clear();
    const r = await api("/api/experiment/assess", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify({})});
    if (!r.ok) { fail(r.data.message || r.data.error); return; }
    await refresh();
  });
}

function renderReassess() {
  const x = M.experiment;
  const box = document.getElementById("reassess");
  if (x.assessment) {
    box.innerHTML = `<div class="card"><span class="tag">deterministic assessment</span> Prediction ${esc(x.assessment.result)}: ${esc(x.assessment.reason)}<div class="refs">A match supports the hypothesis; it does not prove a root cause. Alternatives remain open.</div></div>`;
  } else if (M.mission.diagnostic === "timestamp-audit" && M.mission.audit_viewed) {
    box.innerHTML = `<div class="card"><span class="tag">deterministic reassessment</span> Assignment timing reconciled above; the acknowledgment gap needs a feed-side explanation. See section 5 result.</div>`;
  } else {
    box.innerHTML = `<div class="card"><span class="tag">locked</span> Reassessment unlocks after the assessment (feed probe) or the audit result (timestamp audit).</div>`;
  }
}

let currentProposal = null;

async function renderProposal() {
  const box = document.getElementById("decideResult");
  const iv = M.mission.intervention;
  if (iv) {
    box.innerHTML = `<div class="card"><span class="tag">human decision: ${esc(iv.decision)} · audit · read-only</span> ${esc(iv.note || "")}<div class="refs">proposal: ${esc(iv.proposal.proposal_id)} ${esc(iv.proposal.version)} · executed: ${iv.executed} — approval alone changes nothing, deploys nothing, fixes nothing by itself.</div></div>`;
    for (const id of ["approveBtn", "rejectBtn", "deferBtn"]) {
      document.getElementById(id).disabled = true;
    }
    return;
  }
  const r = await api("/api/mission/proposal");
  if (!r.ok) {
    currentProposal = null;
    for (const id of ["approveBtn", "rejectBtn", "deferBtn"]) {
      document.getElementById(id).disabled = true;
    }
    if (box.innerHTML === "") {
      box.innerHTML = `<div class="card"><span class="tag">locked</span> The exact proposal appears here after the assessment or audit result. Decide only on that proposal.</div>`;
    }
    return;
  }
  currentProposal = r.data;
  const p = currentProposal;
  for (const id of ["approveBtn", "rejectBtn", "deferBtn"]) {
    document.getElementById(id).disabled = false;
  }
  box.innerHTML = `<div class="card"><span class="tag">proposed intervention ${esc(p.proposal_id)} ${esc(p.version)}</span> ${esc(p.text)}`
    + `<div class="refs">supporting evidence: ${(p.supporting_evidence.refs || []).map(esc).join(", ")}</div>`
    + `<div><strong>Risks:</strong> ${(p.risks || []).map(esc).join("; ") || "none recorded"}</div>`
    + `<div><strong>Scope:</strong> ${esc(p.scope)}</div>`
    + `<div><strong>Still open (competing problems):</strong> ${(p.other_open_problems || []).map(esc).join("; ")}</div>`
    + `<div><strong>Stop conditions:</strong> ${esc(p.stop_conditions || "")}</div>`
    + `<div><strong>Next responsible role:</strong> ${esc(p.next_role || "")}</div>`
    + `<div class="refs">reversible: ${p.reversible} (${esc(p.reversible_basis)})</div>`
    + `<div class="refs">${esc(p.approval_note)}</div>`
    + `<div class="refs">A rationale is required: approve, reject, or defer with a stated reason.</div></div>`;
}

function renderDecide() {
  renderProposal();
}

function renderGlossary() {
  document.getElementById("glossary").innerHTML = "<dl>" + Object.entries(M.glossary)
    .map(([k, v]) => `<dt><strong>${esc(k)}</strong></dt><dd>${esc(v)}</dd>`).join("") + "</dl>";
}

async function refresh() {
  const r = await api("/api/mission");
  if (!r.ok) { fail("Could not load mission."); return; }
  M = r.data;
  renderSteps(M.stages);
  renderStatus();
  renderHero();
  renderTimeline();
  renderBrief();
  renderConstraint();
  renderEvidence();
  renderHypotheses();
  renderDiagnostics();
  renderExperiment();
  renderReassess();
  renderDecide();
  renderGlossary();
}

document.getElementById("approveBtn").addEventListener("click", () => decide("approve"));
document.getElementById("rejectBtn").addEventListener("click", () => decide("reject"));
document.getElementById("deferBtn").addEventListener("click", () => decide("defer"));
async function decide(decision) {
  clear();
  if (!currentProposal) { fail("No proposal shown yet. Decide only on the displayed proposal."); return; }
  const note = document.getElementById("decNote").value;
  if (!note.trim()) { fail("A human rationale is required before deciding."); return; }
  const r = await api("/api/mission/intervention", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({decision, note: document.getElementById("decNote").value,
      proposal_id: currentProposal.proposal_id, proposal_version: currentProposal.version})});
  if (!r.ok) { fail(r.data.message || r.data.error); return; }
  await refresh();
}

document.getElementById("mockBtn").addEventListener("click", async () => {
  clear();
  const r = await api("/api/investigation?mode=mock");
  if (!r.ok) { fail("Mock investigation failed."); return; }
  const inv = r.data.investigation;
  document.getElementById("investigation").innerHTML =
    `<div class="card"><span class="tag">offline mock · AI interpretation, not verified fact</span> ${esc(inv.provisional_recommendation.text)}${refs(inv.provisional_recommendation.refs)}</div>`;
});
document.getElementById("liveBtn").addEventListener("click", async () => {
  clear();
  const r = await api("/api/investigation", {method: "POST",
    headers: {"Content-Type": "application/json"}, body: JSON.stringify({mode: "live"})});
  const box = document.getElementById("investigation");
  if (!r.ok) {
    const diag = r.data.diagnostics || {};
    const ref = diag.correlation_id ? ` [${esc(diag.category || "provider failure")} · ref ${esc(diag.correlation_id)}]` : "";
    box.innerHTML = `<div class="card">${esc(r.data.message || r.data.error)}${ref}</div>`;
    return;
  }
  box.innerHTML = `<div class="card"><span class="tag">live AI interpretation, needs human review</span> ${esc(r.data.investigation.provisional_recommendation.text)}</div>`;
});

document.getElementById("reportBtn").addEventListener("click", async () => {
  clear();
  const r = await api("/api/mission/report");
  const box = document.getElementById("report");
  if (!r.ok) { box.innerHTML = `<div class="card">${esc(r.data.message || r.data.error)}</div>`; return; }
  const p = r.data;
  box.innerHTML = `<div class="card"><span class="tag">final mission report · fictional</span></div>`
    + (p.readable_sections || []).map(s =>
      `<div class="card"><span class="tag">${esc(s.layer)}</span> <strong>${esc(s.title)}</strong><ul>`
      + (s.lines || []).map(line => `<li>${esc(line)}</li>`).join("") + `</ul></div>`
    ).join("")
    + `<div class="refs">${esc(p.limitations)}</div>`;
});

function showWorkspace(id) {
  for (const section of document.querySelectorAll(".workspace")) {
    section.classList.toggle("active", section.id === id);
  }
  for (const button of document.querySelectorAll("button[data-ws]")) {
    button.setAttribute("aria-current", String(button.dataset.ws === id));
  }
}
for (const button of document.querySelectorAll("button[data-ws]")) {
  button.addEventListener("click", () => showWorkspace(button.dataset.ws));
}

refresh();

