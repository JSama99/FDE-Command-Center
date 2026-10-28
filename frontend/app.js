// Static fictional snapshot. No backend coupling in this slice.
const snapshot = {
  workspace: { id: "ws-0001", name: "Harbor Clinic Intake", status: "open" },
  truthMap: {
    policies: ["Fictional policy: intake referrals must be acknowledged within 4 business hours."],
    statements: [
      "clinic-coordinator: Fictional report: referrals look sent but families say nothing arrived.",
      "it-operator: Fictional report: the server dashboard is green and jobs succeed."
    ],
    events: [
      "referral-batch: Fictional event: batch #1042 marked delivered by sender queue.",
      "inbox-check: Fictional event: clinic inbox shows zero new referrals for the same window."
    ]
  },
  ledger: [
    "Fictional hypothesis: sender receipt does not equal receiver intake.",
    "Fictional hypothesis: routing table points at a stale inbox."
  ]
};

document.getElementById("workspace").textContent =
  `${snapshot.workspace.name} (${snapshot.workspace.id}) — ${snapshot.workspace.status}`;

document.getElementById("truthmap").innerHTML =
  "<h2>Operational Truth Map</h2>" +
  "<h3>Policy</h3><ul>" + snapshot.truthMap.policies.map(t => `<li>${t}</li>`).join("") + "</ul>" +
  "<h3>Stakeholder statements</h3><ul>" + snapshot.truthMap.statements.map(t => `<li>${t}</li>`).join("") + "</ul>" +
  "<h3>Recorded events</h3><ul>" + snapshot.truthMap.events.map(t => `<li>${t}</li>`).join("") + "</ul>";

document.getElementById("ledger").innerHTML =
  "<h2>Failure Investigation Ledger</h2><ul>" +
  snapshot.ledger.map(t => `<li>${t}</li>`).join("") + "</ul>";
