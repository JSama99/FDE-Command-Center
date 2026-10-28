// Renders backend-validated investigations. No findings are hardcoded here;
// every claim, number, and reference comes from /api responses.
const box = document.getElementById("investigation");
const errBox = document.getElementById("error");
const modeLine = document.getElementById("mode");
const approvalSection = document.getElementById("approval");

function esc(s) { return String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function refs(rs) { return `<div class="refs">refs: ${rs.map(esc).join(", ")}</div>`; }

function render(data) {
  const inv = data.investigation;
  const parts = [];
  parts.push(`<p><span class="tag">${esc(data.mode || "investigation")}</span> ${esc(data.note || "")}</p>`);
  parts.push("<h2>Evidence-backed observations</h2>");
  for (const o of inv.observations) {
    parts.push(`<div class="card"><span class="tag">${esc(o.basis || "observation")}</span> ${esc(o.text)}${refs(o.refs)}</div>`);
  }
  parts.push("<h2>Competing hypotheses (unverified interpretations)</h2>");
  for (const h of inv.competing_hypotheses) {
    parts.push(`<div class="card"><span class="tag">unverified interpretation</span> ${esc(h.text)}${refs(h.refs)}</div>`);
  }
  parts.push("<h2>Unresolved questions</h2><ul>" + inv.unresolved_questions.map(q => `<li>${esc(q)}</li>`).join("") + "</ul>");
  parts.push("<h2>Recommended diagnostic experiments</h2>");
  for (const e of inv.diagnostic_experiments) {
    parts.push(`<div class="card">${esc(e.text)}${refs(e.refs)}</div>`);
  }
  const r = inv.provisional_recommendation;
  parts.push(`<h2>Provisional recommendation (needs human approval)</h2><div class="card">${esc(r.text)}${refs(r.refs)}<div class="refs">requires_human_approval: ${r.requires_human_approval}, executes_production_change: ${r.executes_production_change}</div></div>`);
  parts.push("<h2>Evidence that could change the recommendation</h2>");
  for (const c of inv.counter_evidence) {
    parts.push(`<div class="card">${esc(c.text)}${refs(c.refs)}</div>`);
  }
  box.innerHTML = parts.join("\n");
  approvalSection.style.display = "block";
}

function fail(message, diag) {
  errBox.style.display = "block";
  errBox.textContent = diag && diag.category
    ? `${message} [${diag.category} at ${diag.field_path || "response"} — ref ${diag.correlation_id}]`
    : message;
}

async function load(url, options) {
  errBox.style.display = "none";
  const res = await fetch(url, options);
  const data = await res.json();
  if (!res.ok) { fail(data.message || "Request failed.", data.diagnostics); return; }
  modeLine.textContent = data.mode ? `mode: ${data.mode}` : "";
  render(data);
}

document.getElementById("mockBtn").addEventListener("click", () => load("/api/investigation?mode=mock"));
document.getElementById("liveBtn").addEventListener("click", () => load("/api/investigation", {
  method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({mode: "live"})
}));

async function decide(decision) {
  const note = document.getElementById("note").value;
  const res = await fetch("/api/approval", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({decision, note})
  });
  const data = await res.json();
  document.getElementById("approvalResult").textContent = data.message || "Recorded.";
}
document.getElementById("approveBtn").addEventListener("click", () => decide("approve"));
document.getElementById("rejectBtn").addEventListener("click", () => decide("reject"));

const expState = document.getElementById("expState");
const expDef = document.getElementById("expDef");
const expOut = document.getElementById("expOut");
const STATE_LABEL = {"proposed": "withheld", "prediction locked": "locked", "result revealed": "revealed", "assessed": "assessed"};

async function expRefresh() {
  const res = await fetch("/api/experiment");
  const data = await res.json();
  const d = data.definition;
  expState.innerHTML = `<span class="tag">${STATE_LABEL[data.status] || data.status}</span> EXP-001 — ${esc(data.status)}`;
  expDef.innerHTML = `<p><strong>${esc(d.title)}</strong> — ${esc(d.question)}</p><p>${esc(d.procedure)}</p><p>${esc(d.criteria_info)}</p>`;
  const parts = [];
  if (data.prediction) {
    const p = data.prediction;
    const palts = (p.alternatives || []).map(a => `<li>${esc(a.text)} (${(a.refs || []).map(esc).join(", ")})</li>`).join("");
    const pmets = p.metrics ? Object.entries(p.metrics).map(([k, v]) => `${esc(k)}: ${v}`).join("; ") : "none recorded";
    parts.push(`<div class="card"><span class="tag">locked prediction ${esc(p.version)} · ${esc(p.origin || "human-authored")}</span> ${esc(p.hypothesis_id)} expects ${esc(p.expected_finding)} — ${esc(p.expected_observation)}`
      + (p.test_procedure ? `<div>procedure: ${esc(p.test_procedure)}</div>` : "")
      + `<div>criteria: ${esc(p.criteria)}</div>`
      + (p.uncertainty ? `<div class="refs">uncertainty: ${esc(p.uncertainty)}</div>` : "")
      + (palts ? `<div>alternatives:<ul>${palts}</ul></div>` : "")
      + `<div class="refs">refs: ${p.refs.map(esc).join(", ")} · metrics: ${pmets}</div>`
      + `<div class="refs">model: ${esc(p.model_id || "human")} · generated_at: ${p.generated_at || "n/a"} · locked_at: ${p.locked_at} · hash: ${esc(p.hash)}</div></div>`);
  }
  if (data.outcome) {
    parts.push(`<div class="card"><span class="tag">revealed result</span> ${esc(data.outcome.finding)} — ${esc(data.outcome.detail)}${refs(data.outcome.refs)}</div>`);
  }
  if (data.assessment) {
    const a = data.assessment;
    parts.push(`<div class="card"><span class="tag">${esc(a.result)}</span> ${esc(a.reason)}${refs(a.refs)}</div>`);
  }
  expOut.innerHTML = parts.join("\n");
}

async function expPost(path, body) {
  const res = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})});
  const data = await res.json();
  if (!res.ok) { fail(data.message || data.error || "Experiment request failed."); return; }
  errBox.style.display = "none";
  expRefresh();
}

document.getElementById("expLockBtn").addEventListener("click", () => expPost("/api/experiment/predict", {
  hypothesis_id: document.getElementById("expHyp").value,
  expected_finding: document.getElementById("expFinding").value,
  expected_observation: document.getElementById("expObs").value,
  criteria: document.getElementById("expCrit").value,
  refs: document.getElementById("expRefs").value.split(",").map(s => s.trim()).filter(Boolean)
}));
document.getElementById("expRevealBtn").addEventListener("click", () => expPost("/api/experiment/reveal", {}));
document.getElementById("expAssessBtn").addEventListener("click", () => expPost("/api/experiment/assess", {}));
expRefresh();

const aiReview = document.getElementById("aiReview");
async function aiGenerate(mode) {
  errBox.style.display = "none";
  const res = await fetch("/api/prediction/generate", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({mode})});
  const data = await res.json();
  if (!res.ok) { fail(data.message || data.error || "Prediction failed.", data.diagnostics); return; }
  const p = data.prediction;
  const alts = (p.alternatives || []).map(a => `<li>${esc(a.text)} (${a.refs.map(esc).join(", ")})</li>`).join("");
  const mets = p.metrics ? Object.entries(p.metrics).map(([k, v]) => `${esc(k)}: ${v}`).join("; ") : "none";
  aiReview.innerHTML = `<div class="card"><span class="tag">ai-generated prediction</span> ${esc(p.hypothesis_id)} expects ${esc(p.expected_finding)} — ${esc(p.expected_observation)}<div class="refs">model: ${esc(data.model_id)} · version: ${esc(data.prediction_version)} · refs: ${p.refs.map(esc).join(", ")}</div><div>procedure: ${esc(p.test_procedure || "")}</div><div>criteria: ${esc(p.criteria)}</div><div class="refs">uncertainty: ${esc(p.uncertainty)}</div><div>alternatives:<ul>${alts}</ul></div><div class="refs">metrics: ${mets}</div><div class="refs">This exact text is what locking preserves.</div></div>`;
}
document.getElementById("aiGenMockBtn").addEventListener("click", () => aiGenerate("mock"));
document.getElementById("aiGenLiveBtn").addEventListener("click", () => aiGenerate("live"));
document.getElementById("aiLockBtn").addEventListener("click", async () => {
  const confirmed = document.getElementById("aiConfirm").checked;
  const res = await fetch("/api/prediction/lock", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({confirmed})});
  const data = await res.json();
  if (!res.ok) { fail(data.message || data.error || "Lock failed."); return; }
  errBox.style.display = "none";
  expRefresh();
});

const revCompare = document.getElementById("revCompare");
async function revGenerate(mode) {
  errBox.style.display = "none";
  const res = await fetch("/api/revision/generate", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({mode})});
  const data = await res.json();
  if (!res.ok) { fail(data.message || data.error || "Revision failed.", data.diagnostics); return; }
  const r = data.revision;
  const o = r.original_prediction;
  revCompare.innerHTML =
    `<h3>Before (original locked prediction)</h3><div class="card">${esc(o.hypothesis_id)} — expected ${esc(o.expected_finding)}: ${esc(o.expected_observation)}<div class="refs">prediction agreement: ${esc(r.deterministic_assessment.result)} (agreement is support, not proof)</div></div>` +
    `<h3>After (ai-generated interpretation)</h3><div class="card"><span class="tag">ai-generated interpretation</span> H-ACK: ${esc(r.effect_on_h_ack.stance)} <span class="tag">${esc(r.effect_on_h_ack.scope)} finding</span> — ${esc(r.effect_on_h_ack.reason)}<br>H-QUEUE: ${esc(r.effect_on_h_queue.stance)} <span class="tag">${esc(r.effect_on_h_queue.scope)} finding</span> — ${esc(r.effect_on_h_queue.reason)}<div>${esc(r.updated_recommendation.text)}</div><div class="refs">next test: ${esc(r.next_test.text)} — expect: ${esc(r.next_test.expected_observations)}</div><div class="refs">No organization-wide root cause established. Causal validation: none performed.</div></div>`;
  document.getElementById("revApproval").style.display = "block";
  expRefresh();
}
document.getElementById("revMockBtn").addEventListener("click", () => revGenerate("mock"));
document.getElementById("revLiveBtn").addEventListener("click", () => revGenerate("live"));
async function revDecide(decision) {
  const res = await fetch("/api/revision/approve", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({decision, note: document.getElementById("revNote").value})});
  const data = await res.json();
  document.getElementById("revApprovalResult").textContent = (data.message || "Recorded.") + " Shown as human-reviewed revision. No causal validation performed.";
}
document.getElementById("revApproveBtn").addEventListener("click", () => revDecide("approve"));
document.getElementById("revRejectBtn").addEventListener("click", () => revDecide("reject"));
