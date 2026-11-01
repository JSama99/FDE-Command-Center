// Minimal DOM stub that executes the real frontend/control.js against a
// backend /api/mission snapshot. Driven by a JSON action list; prints a
// JSON summary of the resulting panels for Python assertions.
//
// Usage: node mc_graph_harness.js <control.js> <snapshot.json|FAIL> <actions.json>
const fs = require("fs");

const [jsPath, snapPath, actionsPath, proposalPath, chaosDirArg, chaosRunFile] = process.argv.slice(2);
const chaosDir = chaosDirArg || "frontend/chaos-results";
const source = fs.readFileSync(jsPath, "utf8");
const failFetch = snapPath === "FAIL";
const snapshot = failFetch ? null : JSON.parse(fs.readFileSync(snapPath, "utf8"));
const actions = JSON.parse(fs.readFileSync(actionsPath, "utf8"));

const elements = {};
const nodeAttrs = {};
const gtabStubs = [];
const listBtnAttrs = {};
const listClicks = {};
const hypClicks = {};
const scnClicks = {};
const varClicks = {};
const ctabClicks = {};
const ctabPressed = {};
const runClicks = {};
const fetchLog = [];
const varPressed = {};
const viewState = { active: "view-overview" };
const viewStubs = ["view-overview", "view-investigation", "view-hypothesis", "view-decision"].map((id) => ({
  id,
  classList: { toggle(cls, on) { if (cls === "active" && on) viewState.active = id; } },
}));

function makeEl(id) {
  return {
    id, innerHTML: "", textContent: "", value: "",
    style: {}, handlers: {}, attrs: {},
    addEventListener(type, fn) { this.handlers[type] = fn; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k]; },
    appendChild(child) { this.innerHTML += child.innerHTML; },
    querySelectorAll(sel) {
      if (sel === "[data-chaos-run]") {
        return [...this.innerHTML.matchAll(/data-chaos-run="([^"]+)"/g)].map(() => {
          const stub = { disabled: false, textContent: "run",
            addEventListener(type, fn) { if (type === "click") runClicks.current = fn; },
            setAttribute() {} };
          return stub;
        });
      }
      if (sel === "button[data-variant]") {
        return [...this.innerHTML.matchAll(/data-variant="([^"]+)"/g)].map((m) => ({
          dataset: { variant: m[1] },
          addEventListener(type, fn) { if (type === "click") varClicks[m[1]] = fn; },
          setAttribute(k, v) {
            varPressed[m[1]] = String(v);
          },
        }));
      }
      if (this.id === "mcList" && sel === "button[data-item]") {
        return [...this.innerHTML.matchAll(/data-item="([^"]+)"/g)].map((m) => ({
          dataset: { item: m[1] },
          addEventListener(type, fn) { if (type === "click") listClicks[m[1]] = fn; },
          setAttribute(k, v) {
            listBtnAttrs[m[1]] = listBtnAttrs[m[1]] || {};
            listBtnAttrs[m[1]][k] = String(v);
          },
        }));
      }
      return [];
    },
  };
}
function el(id) {
  if (!elements[id]) elements[id] = makeEl(id);
  return elements[id];
}

function gNodeStub(id) {
  return {
    dataset: { node: id },
    setAttribute(k, v) {
      nodeAttrs[id] = nodeAttrs[id] || {};
      nodeAttrs[id][k] = String(v);
    },
  };
}

global.document = {
  createElement: (tag) => makeEl(tag),
  getElementById: (id) => el(id),
  querySelector: (sel) => {
    if (sel === "#mcScenarioDetail [data-chaos-run]") {
      const found = el("mcScenarioDetail").innerHTML.match(/data-chaos-run="([^"]+)"/);
      if (!found) return null;
      return { disabled: false,
        textContent: "Run this scenario now (synthetic, offline)" };
    }
    return null;
  },
  querySelectorAll: (sel) => {
    if (sel === "#mcList button[data-item]") {
      return el("mcList").querySelectorAll("button[data-item]");
    }
    if (sel === "#mcLab button[data-hyp]") {
      return [...el("mcLab").innerHTML.matchAll(/data-hyp="([^"]+)"/g)].map((m) => ({
        dataset: { hyp: m[1] },
        addEventListener(type, fn) { if (type === "click") hypClicks[m[1]] = fn; },
        setAttribute() {},
      }));
    }
    if (sel === "#mcLab button[data-item]") {
      return [...el("mcLab").innerHTML.matchAll(/data-item="([^"]+)"/g)].map((m) => ({
        dataset: { item: m[1] },
        addEventListener(type, fn) { if (type === "click") listClicks["lab:" + m[1]] = fn; },
        setAttribute() {},
      }));
    }
    if (sel === ".mcview") return viewStubs;
    if (sel === "#view-chaos button[data-ctab]") {
      return ["scenario", "results", "evaluation", "recovery"].map((name) => ({
        dataset: { ctab: name },
        addEventListener(type, fn) { if (type === "click") ctabClicks[name] = fn; },
        setAttribute(k, v) { ctabPressed[name] = String(v); },
      }));
    }
    if (sel === "#mcScenarioDetail button[data-variant]") {
      return [...el("mcScenarioDetail").innerHTML.matchAll(/data-variant="([^"]+)"/g)].map((m) => ({
        dataset: { variant: m[1] },
        addEventListener(type, fn) { if (type === "click") varClicks[m[1]] = fn; },
        setAttribute(k, v) { varPressed[m[1]] = String(v); },
      }));
    }
    if (sel === "#mcScenarioList button[data-scn]") {
      return [...el("mcScenarioList").innerHTML.matchAll(/data-scn="([^"]+)"/g)].map((m) => ({
        dataset: { scn: m[1] },
        addEventListener(type, fn) { if (type === "click") scnClicks[m[1]] = fn; },
        setAttribute() {},
      }));
    }
    if (sel === "#mcScenarioDetail button[data-item]") {
      return [...el("mcScenarioDetail").innerHTML.matchAll(/data-item="([^"]+)"/g)].map((m) => ({
        dataset: { item: m[1] },
        addEventListener(type, fn) { if (type === "click") listClicks["chaos:" + m[1]] = fn; },
        setAttribute() {},
      }));
    }
    if (sel === "#mcGraph .node") {
      const html = el("mcGraph").innerHTML;
      return [...html.matchAll(/data-node="([^"]+)"/g)].map((m) => gNodeStub(m[1]));
    }
    if (sel === "button[data-gtab]") {
      while (gtabStubs.length < 2) {
        const s = makeEl("gtab" + gtabStubs.length);
        s.dataset = { gtab: gtabStubs.length === 0 ? "evidence" : "illustrative" };
        gtabStubs.push(s);
      }
      return gtabStubs;
    }
    return [];
  },
};
global.location = { search: "" };
global.fetch = async (url, opts) => {
  if (failFetch) throw new Error("connection refused");
  fetchLog.push({ url: String(url), method: (opts && opts.method) || "GET",
                  body: (opts && opts.body) || null });
  if (String(url) === "/api/chaos/run") {
    if (!chaosRunFile || chaosRunFile === "NONE") {
      return { ok: false, status: 403,
               json: async () => ({ error: "forbidden" }) };
    }
    const data = JSON.parse(fs.readFileSync(chaosRunFile, "utf8"));
    return { ok: true, json: async () => data };
  }
  if (String(url).startsWith("chaos-results/")) {
    try {
      const data = JSON.parse(fs.readFileSync(
        chaosDir + "/" + String(url).split("/").pop(), "utf8"));
      return { ok: true, json: async () => data };
    } catch (e) {
      return { ok: false, status: 404, json: async () => ({}) };
    }
  }
  if (String(url).endsWith("/proposal")) {
    if (!proposalPath || proposalPath === "NONE") {
      return { ok: false, status: 409, json: async () => ({ error: "too-early" }) };
    }
    const proposal = JSON.parse(fs.readFileSync(proposalPath, "utf8"));
    return { ok: true, json: async () => proposal };
  }
  return { ok: true, json: async () => snapshot };
};

eval(source);

function closestFor(kind, id) {
  return (sel) => {
    if (kind === "item" && sel === "[data-item]") return { dataset: { item: id } };
    if (kind === "node" && sel === "[data-node]") return { dataset: { node: id } };
    return null;
  };
}

(async () => {
  await new Promise((r) => setTimeout(r, 50)); // let boot() finish
  for (const a of actions) {
    if (a["click-item"]) {
      if (typeof listClicks[a["click-item"]] !== "function") {
        throw new Error("no ledger button for " + a["click-item"]);
      }
      listClicks[a["click-item"]]();
    } else if (a["click-lab-item"]) {
      const fn = listClicks["lab:" + a["click-lab-item"]];
      if (typeof fn !== "function") {
        throw new Error("no lab evidence button for " + a["click-lab-item"]);
      }
      fn();
    } else if (a["select-hyp"]) {
      if (typeof hypClicks[a["select-hyp"]] !== "function") {
        throw new Error("no hypothesis button for " + a["select-hyp"]);
      }
      hypClicks[a["select-hyp"]]();
    } else if (a["select-scn"]) {
      if (typeof scnClicks[a["select-scn"]] !== "function") {
        throw new Error("no scenario button for " + a["select-scn"]);
      }
      await scnClicks[a["select-scn"]]();
    } else if (a["chaos-tab"]) {
      if (typeof ctabClicks[a["chaos-tab"]] !== "function") {
        throw new Error("no chaos tab for " + a["chaos-tab"]);
      }
      await ctabClicks[a["chaos-tab"]]();
      await new Promise((r) => setTimeout(r, 10));
    } else if (a["select-variant"]) {
      if (typeof varClicks[a["select-variant"]] !== "function") {
        throw new Error("no variant button for " + a["select-variant"]);
      }
      await varClicks[a["select-variant"]]();
      await new Promise((r) => setTimeout(r, 5));
    } else if (a["click-run"]) {
      if (typeof runClicks.current !== "function") {
        throw new Error("no run button");
      }
      await runClicks.current();
      await new Promise((r) => setTimeout(r, 5));
    } else if (a["click-chaos-item"]) {
      const fn = listClicks["chaos:" + a["click-chaos-item"]];
      if (typeof fn !== "function") {
        throw new Error("no chaos evidence button for " + a["click-chaos-item"]);
      }
      fn();
    } else if (a["click-room-item"] || a["click-room-goto"]) {
      const wantRoom = a["click-room-item"];
      const fake = {
        closest: (sel) => {
          if (wantRoom && sel === "[data-room]") return { dataset: { room: wantRoom } };
          if (!wantRoom && sel === "[data-room-goto]") return { dataset: { roomGoto: a["click-room-goto"] } };
          return null;
        },
      };
      el("mcDecisionCards").handlers.click({ target: fake });
      el("mcProposal").handlers.click({ target: fake });
    } else if (a["click-node"]) {
      el("mcGraph").handlers.click({ target: { closest: closestFor("node", a["click-node"]) } });
    } else if (a["keydown-node"]) {
      el("mcGraph").handlers.keydown({
        key: a["keydown-node"].key, preventDefault() {},
        target: { closest: closestFor("node", a["keydown-node"].node) },
      });
    } else if (a.tab === "illustrative") {
      gtabStubs[1].handlers.click();
    } else if (a.tab === "evidence") {
      gtabStubs[0].handlers.click();
    } else if (a.search !== undefined) {
      el("mcSearch").value = a.search;
      el("mcSearch").handlers.input({ target: { value: a.search } });
    } else if (a.filter) {
      el("mcFilters").handlers.click({
        target: { closest: (sel) => (sel === "button[data-filter]"
          ? { dataset: { filter: a.filter } } : null) },
      });
    }
    await new Promise((r) => setTimeout(r, 5));
  }
  const out = {
    error: el("error").textContent,
    activeView: viewState.active,
    lab: el("mcLab").innerHTML,
    labStatus: el("mcLabStatus").innerHTML,
    labQuestions: el("mcLabQuestions").innerHTML,
    roomCards: el("mcDecisionCards").innerHTML,
    roomProposal: el("mcProposal").innerHTML,
    roomVerify: el("mcVerify").innerHTML,
    roomReview: el("mcHumanReview").innerHTML,
    roomContext: el("mcDecisionContext").textContent,
    chaosList: el("mcScenarioList").innerHTML,
    chaosDetail: el("mcScenarioDetail").innerHTML,
    chaosFlow: el("mcChaosFlow").innerHTML,
    chaosResult: el("mcChaosResult").innerHTML,
    chaosExecuted: el("mcChaosExecuted").innerHTML,
    evalReport: el("mcEvalReport").innerHTML,
    recoveryRecords: el("mcRecoveryRecords").innerHTML,
    resultSummary: el("mcResultSummary").innerHTML,
    ctabPressed,
    fetchLog,
    varPressed,
    inspector: el("mcInspector").innerHTML,
    list: el("mcList").innerHTML,
    graph: el("mcGraph").innerHTML,
    illust: el("mcIllust").innerHTML,
    nodeAttrs,
    listBtnAttrs,
    gtabEvidenceDisplay: el("gtabEvidence").style.display || "",
    gtabIllustrativeDisplay: el("gtabIllustrative").style.display || "",
    gtabPressed: gtabStubs.map((s) => s.attrs["aria-pressed"] || ""),
  };
  console.log(JSON.stringify(out));
})();
