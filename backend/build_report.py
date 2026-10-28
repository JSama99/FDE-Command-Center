"""Generate frontend/case-001.json and frontend/case-001.html from the backend.

Usage: python3 backend/build_report.py
Reads fixtures + backend.report, writes backend-generated artifacts only.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .report import build_case_report

ROOT = Path(__file__).resolve().parents[1]


def _quote_block(item: dict) -> str:
    q = html.escape(item["quote"])
    ref = f"{html.escape(item['doc_id'])} [{item['start']}:{item['end']}]"
    return f"<blockquote>{q}<cite>{ref}</cite></blockquote>"


def render_html(report: dict, embedded_json: str) -> str:
    sections: list[str] = []
    sections.append("<h2>Policy requirements (verified quotations)</h2>")
    sections.append("".join(_quote_block(q) for q in report["policy_requirements"]))

    sections.append("<h2>Dispatcher statements (attributed)</h2>")
    sections.append("".join(_quote_block(q) for q in report["dispatcher_statements"]))

    sections.append("<h2>Manager statements (attributed)</h2>")
    sections.append("".join(_quote_block(q) for q in report["manager_statements"]))

    sections.append("<h2>Contradictions (source-backed)</h2><ul>")
    for c in report["contradictions"]:
        srcs = "; ".join(f'{html.escape(s["ref"])}: &ldquo;{html.escape(s["quote"])}&rdquo;' for s in c["sources"])
        sections.append(
            f"<li><strong>{html.escape(c['title'])}</strong><br>{srcs}<br>"
            f"Computed: {html.escape(c['computed'])}<br>Status: {html.escape(c['status'])}</li>"
        )
    sections.append("</ul>")

    sections.append("<h2>Unresolved questions</h2><ul>")
    for u in report["unresolved_questions"]:
        sections.append(f"<li>{html.escape(u)}</li>")
    sections.append("</ul>")

    sections.append("<h2>Event-log calculations (deterministic)</h2>")
    sections.append(
        "<table><thead><tr><th>Finding</th><th>Value</th><th>Cases</th><th>Rule</th><th>Source</th></tr></thead><tbody>"
    )
    for calc in report["calculations"]:
        ids = ", ".join(calc["ids"]) if calc["ids"] else "&mdash;"
        sections.append(
            f"<tr><td>{html.escape(calc['label'])}</td>"
            f"<td>{calc['value']} <span class='den'>/ {html.escape(calc['denominator'])}</span></td>"
            f"<td>{html.escape(ids)}</td>"
            f"<td>{html.escape(calc['rule'])}</td>"
            f"<td>{html.escape(calc['source'])}</td></tr>"
        )
    sections.append("</tbody></table>")

    obs = report["reported_observation_only"]
    sections.append("<h2>Reported observation (not a cause)</h2>")
    sections.append(
        f"<blockquote>{html.escape(obs['quote'])}<cite>{html.escape(obs['source'])}</cite></blockquote>"
        f"<p>{html.escape(obs['note'])}</p>"
    )

    sections.append("<h2>Hypotheses (unverified interpretations)</h2><ul>")
    for h in report["hypotheses"]:
        basis = "; ".join(html.escape(b) for b in h["basis"])
        sections.append(
            f"<li><span class='tag'>unverified interpretation</span> {html.escape(h['text'])}<br>Basis: {basis}</li>"
        )
    sections.append("</ul>")

    body = "\n".join(sections)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Case-001 Evidence Inspection Workspace</title>
<style>
body {{ font-family: system-ui, -apple-system, sans-serif; margin: 2rem auto; max-width: 900px; padding: 0 1rem; color: #1a1a1a; }}
header p {{ color: #444; }}
section {{ margin: 1.5rem 0; }}
blockquote {{ border-left: 3px solid #333; margin: 0.75rem 0; padding: 0.5rem 0.75rem; background: #f6f6f6; }}
blockquote cite {{ display: block; font-size: 0.8rem; font-style: normal; color: #444; margin-top: 0.25rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
th, td {{ border: 1px solid #999; padding: 0.4rem 0.5rem; text-align: left; vertical-align: top; }}
th {{ background: #eee; }}
.den {{ color: #444; font-size: 0.8rem; }}
.tag {{ background: #eee; border: 1px solid #999; padding: 0 0.4rem; font-size: 0.8rem; }}
</style>
</head>
<body>
<header>
<h1>Case-001 Evidence Inspection Workspace</h1>
<p>All data is fictional. Policy and stakeholder text is verified verbatim with source offsets. Counts are computed from fixtures/case-001/events.csv.</p>
</header>
{body}
<script type="application/json" id="report-data">
{embedded_json}
</script>
</body>
</html>
"""


def main() -> None:
    report = build_case_report(ROOT)
    frontend = ROOT / "frontend"
    data_json = json.dumps(report, indent=2)
    (frontend / "case-001.json").write_text(data_json + "\n", encoding="utf-8")
    (frontend / "case-001.html").write_text(render_html(report, data_json), encoding="utf-8")
    print("wrote frontend/case-001.json and frontend/case-001.html")


if __name__ == "__main__":
    main()
