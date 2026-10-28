"""Local server for the AI Investigation Workspace (Task 005).

- Serves frontend/ statically.
- GET  /api/report -> verified case-001 report (Task 003 builder).
- GET  /api/investigation?mode=mock -> deterministic offline investigation,
  no API call, for UI testing.
- POST /api/investigation {"mode": "live"} -> explicit live run through the
  Meta Responses API adapter. Requires MODEL_API_KEY. Nothing runs automatically.
- POST /api/approval {"decision": "approve"|"reject", "note": "..."} ->
  records the human decision in memory. No production change can be executed;
  no such code path exists.

Run: python3 -m backend.server [--port 8000]
"""

from __future__ import annotations

import json
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .ai_prediction import (
    AI_PREDICTION_VERSION,
    build_evidence_cutoff,
    generate_ai_prediction,
    mock_prediction_payload,
    mock_revision_payload,
    produce_revision,
    validate_prediction,
    validate_revision,
)
from .experiment import (
    ExperimentError,
    assess as assess_experiment,
    build_registry as experiment_registry,
    lock_prediction,
    new_experiment_state,
    public_view,
    reveal_outcome,
)
from .investigation import (
    DiagnosticError,
    InvestigationValidationError,
    build_offline_investigation,
    diagnostic_report,
    produce_investigation,
)
from .meta_adapter import (
    CATEGORY_EXPLANATIONS,
    MAX_OUTPUT_TOKENS,
    MODEL_ID,
    MalformedResponseError,
    MetaModelAdapter,
    MissingCredentialsError,
    ProviderError,
    ProviderFailure,
)
from .mission import (
    MissionError,
    choose_diagnostic,
    decide_intervention,
    diagnostic_result,
    intervention_proposal,
    mission_report,
    mission_view,
    new_mission_state,
)
from .report import build_case_report

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"

CONTENT_TYPES = {".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".css": "text/css"}

ERROR_MESSAGES = {
    "missing_credentials": "Live investigation needs MODEL_API_KEY. No request was sent.",
    "provider_unavailable": "Provider request failed. No investigation was produced.",
    "invalid_investigation": "Model output failed evidence validation and was not displayed.",
    "bad_request": "Request not understood.",
    "not_found": "Unknown path.",
}


def new_context(base_dir: str | Path = ROOT) -> dict:
    return {
        "base_dir": Path(base_dir),
        "approvals": [],
        "diagnostics": [],
        "experiment": new_experiment_state(),
        "mission": new_mission_state(),
    }


def _record_diagnostics(ctx: dict, record: dict) -> None:
    log = ctx.setdefault("diagnostics", [])
    log.append(record)
    del log[:-20]


def _provider_failure_response(ctx: dict, exc: BaseException,
                               correlation_id: str) -> tuple[int, dict, str]:
    """Sanitized 502 for a failed provider attempt. The record carries only
    category, HTTP status, exception class, timeout flag, transmission
    assessment, model, output cap, and usage availability — never keys,
    headers, bodies, or provider error text."""
    from datetime import datetime, timezone

    if isinstance(exc, ProviderFailure):
        transport = dict(exc.diagnostic)
    else:  # legacy ProviderError without classification; never guessed
        transport = {"category": "provider-error", "http_status": None,
                     "exception_class": type(exc).__name__,
                     "timeout_occurred": False, "transmission": "unknown"}
    record = {"correlation_id": correlation_id,
              "timestamp": datetime.now(timezone.utc).isoformat(),
              "model": MODEL_ID,
              "max_output_tokens": MAX_OUTPUT_TOKENS,
              "usage_available": False,
              **transport}
    _record_diagnostics(ctx, record)
    explanation = CATEGORY_EXPLANATIONS.get(
        record["category"], "the provider request failed")
    if record["transmission"] == "confirmed" and record["http_status"] is not None:
        reach = (f"The request reached the provider, which answered "
                 f"HTTP {record['http_status']}.")
    elif record["transmission"] == "confirmed":
        reach = "The request reached the provider, which did not complete it."
    else:
        reach = ("It is not established whether the request reached the "
                 "provider.")
    message = (f"Provider request failed: {explanation} "
               f"[reference {correlation_id}]. {reach} No usage information "
               f"is available, no investigation was produced, and nothing "
               f"was executed.")
    return 502, {"error": "provider_unavailable", "message": message,
                 "diagnostics": record}, "application/json"


def _static(path: str) -> tuple[int, bytes, str] | None:
    if ".." in path or "\x00" in path:
        return None
    rel = path.lstrip("/") or "index.html"
    if rel == "frontend" or rel.startswith("frontend/"):
        # Tolerate the /frontend/ URL prefix (used in server startup messages)
        # so pages opened that way resolve their sibling assets identically.
        rel = rel[len("frontend"):].lstrip("/") or "index.html"
    target = (FRONTEND_DIR / rel).resolve()
    try:
        target.relative_to(FRONTEND_DIR.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    return 200, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream")


def handle_request(
    method: str, target: str, body: bytes | None, ctx: dict
) -> tuple[int, bytes | dict, str]:
    parsed = urllib.parse.urlparse(target)
    query = urllib.parse.parse_qs(parsed.query)
    path = parsed.path

    if path == "/api/report" and method == "GET":
        return 200, build_case_report(ctx["base_dir"]), "application/json"

    if path == "/api/investigation" and method == "GET":
        mode = query.get("mode", ["mock"])[0]
        if mode != "mock":
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        return 200, build_offline_investigation(ctx["base_dir"]), "application/json"

    if path == "/api/investigation" and method == "POST":
        try:
            payload = json.loads((body or b"{}").decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        if payload.get("mode") != "live":
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        correlation_id = uuid.uuid4().hex[:12]
        try:
            return 200, produce_investigation(MetaModelAdapter(), ctx["base_dir"]), "application/json"
        except MissingCredentialsError:
            return 503, {"error": "missing_credentials", "message": ERROR_MESSAGES["missing_credentials"]}, "application/json"
        except ProviderError as exc:
            return _provider_failure_response(ctx, exc, correlation_id)
        except MalformedResponseError as exc:
            record = diagnostic_report(exc, correlation_id, "response-parsing")
            _record_diagnostics(ctx, record)
            return 502, {
                "error": "invalid_investigation",
                "message": ERROR_MESSAGES["invalid_investigation"],
                "diagnostics": record,
            }, "application/json"
        except InvestigationValidationError as exc:
            record = diagnostic_report(exc, correlation_id, "evidence-validation")
            _record_diagnostics(ctx, record)
            return 502, {
                "error": "invalid_investigation",
                "message": ERROR_MESSAGES["invalid_investigation"],
                "diagnostics": record,
            }, "application/json"

    if path == "/api/experiment" and method == "GET":
        return 200, public_view(ctx["experiment"]), "application/json"

    if path == "/api/experiment/predict" and method == "POST":
        try:
            payload = json.loads((body or b"{}").decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        try:
            registry = experiment_registry(ctx["base_dir"])
            record = lock_prediction(ctx["experiment"], payload, registry, int(time.time()))
        except ExperimentError as exc:
            status = 409 if exc.code in ("already-locked", "too-early") else 400
            return status, {"error": exc.code, "message": str(exc)}, "application/json"
        return 200, {"locked": True, "prediction": record}, "application/json"

    if path == "/api/experiment/reveal" and method == "POST":
        try:
            outcome = reveal_outcome(ctx["experiment"], int(time.time()))
        except ExperimentError as exc:
            return 409, {"error": exc.code, "message": str(exc)}, "application/json"
        return 200, {"revealed": True, "outcome": outcome}, "application/json"

    if path == "/api/experiment/assess" and method == "POST":
        try:
            assessment = assess_experiment(ctx["experiment"])
        except ExperimentError as exc:
            return 409, {"error": exc.code, "message": str(exc)}, "application/json"
        return 200, {"assessed": True, "assessment": assessment}, "application/json"

    if path == "/api/prediction/generate" and method == "POST":
        try:
            payload = json.loads((body or b"{}").decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        mode = payload.get("mode")
        if mode not in ("mock", "live"):
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        from .report import build_case_report as _report

        report = _report(ctx["base_dir"])
        try:
            if mode == "mock":
                from .investigation import build_evidence_registry as _registry

                validated = validate_prediction(
                    mock_prediction_payload(), _registry(report)
                )
                envelope = {
                    "origin": "ai-generated",
                    "model_id": "offline-mock",
                    "prediction_version": AI_PREDICTION_VERSION,
                    "evidence_cutoff": build_evidence_cutoff(report),
                    "generated_at": int(time.time()),
                    "demonstration_only": True,
                    "prediction": validated,
                }
            else:
                envelope = generate_ai_prediction(MetaModelAdapter(), ctx["base_dir"], int(time.time()))
        except MissingCredentialsError:
            return 503, {"error": "missing_credentials", "message": ERROR_MESSAGES["missing_credentials"]}, "application/json"
        except ProviderError as exc:
            return _provider_failure_response(ctx, exc, uuid.uuid4().hex[:12])
        except (MalformedResponseError, DiagnosticError, InvestigationValidationError) as exc:
            record = diagnostic_report(
                exc, uuid.uuid4().hex[:12],
                "response-parsing" if isinstance(exc, MalformedResponseError) else "prediction-validation",
            )
            _record_diagnostics(ctx, record)
            return 502, {
                "error": "invalid_investigation",
                "message": ERROR_MESSAGES["invalid_investigation"],
                "diagnostics": record,
            }, "application/json"
        ctx["pending_ai"] = envelope
        envelope = dict(envelope)
        envelope["requires_confirmation"] = True
        return 200, envelope, "application/json"

    if path == "/api/prediction/lock" and method == "POST":
        try:
            payload = json.loads((body or b"{}").decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        if payload.get("confirmed") is not True:
            return 400, {"error": "confirmation-required", "message": "Human confirmation is required before locking."}, "application/json"
        if ctx["experiment"].get("prediction") is not None:
            return 409, {"error": "already-locked", "message": "Prediction is already locked and cannot be changed."}, "application/json"
        pending = ctx.get("pending_ai")
        if pending is None:
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        try:
            from .investigation import build_evidence_registry as _registry2

            from .report import build_case_report as _report2

            registry = _registry2(_report2(ctx["base_dir"]))
            validated = validate_prediction(pending["prediction"], registry)
            record = lock_prediction(
                ctx["experiment"],
                dict(validated),
                registry,
                int(time.time()),
                origin="ai-generated",
                extra={
                    "model_id": pending["model_id"],
                    "prediction_version": pending["prediction_version"],
                    "evidence_cutoff": pending["evidence_cutoff"],
                    "generated_at": pending["generated_at"],
                },
            )
        except ExperimentError as exc:
            status = 409 if exc.code in ("already-locked", "too-early") else 400
            return status, {"error": exc.code, "message": str(exc)}, "application/json"
        except (DiagnosticError, InvestigationValidationError) as exc:
            return 400, {"error": "bad-prediction", "message": str(exc)}, "application/json"
        ctx["pending_ai"] = None
        return 200, {"locked": True, "prediction": record}, "application/json"

    if path == "/api/revision/generate" and method == "POST":
        try:
            payload = json.loads((body or b"{}").decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        mode = payload.get("mode")
        if mode not in ("mock", "live"):
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        experiment = ctx["experiment"]
        if experiment["status"] != "assessed":
            return 409, {"error": "too-early", "message": "Revision requires a revealed and assessed experiment."}, "application/json"
        try:
            if mode == "mock":
                from .investigation import build_evidence_registry as _registry3

                from .report import build_case_report as _report3

                report = _report3(ctx["base_dir"])
                registry = _registry3(report)
                validated = validate_revision(
                    mock_revision_payload(), registry,
                    experiment["prediction"], experiment["outcome"], experiment["assessment"],
                )
                result = {
                    "origin": "offline-mock",
                    "model_id": "offline-mock",
                    "version": 1,
                    "generated_at": int(time.time()),
                    "demonstration_only": True,
                    "revision": validated,
                }
            else:
                result = produce_revision(MetaModelAdapter(), ctx["base_dir"], experiment, int(time.time()), "ai-generated")
        except MissingCredentialsError:
            return 503, {"error": "missing_credentials", "message": ERROR_MESSAGES["missing_credentials"]}, "application/json"
        except ProviderError as exc:
            return _provider_failure_response(ctx, exc, uuid.uuid4().hex[:12])
        except (MalformedResponseError, DiagnosticError, InvestigationValidationError) as exc:
            record = diagnostic_report(
                exc, uuid.uuid4().hex[:12],
                "response-parsing" if isinstance(exc, MalformedResponseError) else "revision-validation",
            )
            _record_diagnostics(ctx, record)
            return 502, {
                "error": "invalid_investigation",
                "message": ERROR_MESSAGES["invalid_investigation"],
                "diagnostics": record,
            }, "application/json"
        experiment["revision"] = result
        experiment["revision_validation"] = None
        return 200, result, "application/json"

    if path == "/api/revision/approve" and method == "POST":
        try:
            payload = json.loads((body or b"{}").decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        if ctx["experiment"].get("revision") is None:
            return 409, {"error": "too-early", "message": "No revision to validate yet."}, "application/json"
        decision = payload.get("decision")
        if decision not in ("approve", "reject"):
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        record = {
            "decision": decision,
            "note": str(payload.get("note", ""))[:500],
            "at": int(time.time()),
            "executed": False,
        }
        ctx["experiment"]["revision_validation"] = record
        return 200, {
            "recorded": True,
            "executed": False,
            "message": "Revision validation recorded. No production change was executed and none can be.",
        }, "application/json"

    if path == "/api/diagnostics/latest" and method == "GET":
        log = ctx.get("diagnostics", [])
        if not log:
            return 404, {"error": "not_found", "message": ERROR_MESSAGES["not_found"]}, "application/json"
        return 200, log[-1], "application/json"

    if path == "/api/approval" and method == "POST":
        try:
            payload = json.loads((body or b"{}").decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        decision = payload.get("decision")
        if decision not in ("approve", "reject"):
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        record = {
            "decision": decision,
            "note": str(payload.get("note", ""))[:500],
            "at": int(time.time()),
            "executed": False,
        }
        ctx["approvals"].append(record)
        return 200, {
            "recorded": True,
            "executed": False,
            "message": "Decision recorded. No production change was executed and none can be.",
        }, "application/json"

    if path == "/api/mission" and method == "GET":
        return 200, mission_view(ctx), "application/json"

    if path == "/api/mission/diagnostic" and method == "POST":
        try:
            payload = json.loads((body or b"{}").decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        try:
            return 200, choose_diagnostic(ctx, payload.get("choice")), "application/json"
        except MissionError as exc:
            status = 409 if exc.code in ("already-chosen", "too-late") else 400
            return status, {"error": exc.code, "message": str(exc)}, "application/json"

    if path == "/api/mission/diagnostic/result" and method == "GET":
        try:
            return 200, diagnostic_result(ctx), "application/json"
        except MissionError as exc:
            return 409, {"error": exc.code, "message": str(exc)}, "application/json"

    if path == "/api/mission/proposal" and method == "GET":
        try:
            return 200, intervention_proposal(ctx), "application/json"
        except MissionError as exc:
            return 409, {"error": exc.code, "message": str(exc)}, "application/json"

    if path == "/api/mission/intervention" and method == "POST":
        try:
            payload = json.loads((body or b"{}").decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"error": "bad_request", "message": ERROR_MESSAGES["bad_request"]}, "application/json"
        try:
            return 200, decide_intervention(
                ctx, payload.get("decision"), payload.get("note", ""),
                payload.get("proposal_id"), payload.get("proposal_version")), "application/json"
        except MissionError as exc:
            status = 409 if exc.code in ("already-decided", "too-early", "proposal-mismatch") else 400
            return status, {"error": exc.code, "message": str(exc)}, "application/json"

    if path == "/api/mission/report" and method == "GET":
        try:
            return 200, mission_report(ctx), "application/json"
        except MissionError as exc:
            return 409, {"error": exc.code, "message": str(exc)}, "application/json"

    if method == "GET" and (path == "/" or not path.startswith("/api/")):
        static = _static(path)
        if static is not None:
            return static
        return 404, {"error": "not_found", "message": ERROR_MESSAGES["not_found"]}, "application/json"

    return 404, {"error": "not_found", "message": ERROR_MESSAGES["not_found"]}, "application/json"


class Handler(BaseHTTPRequestHandler):
    context: dict = {}

    def _send(self, status: int, payload: bytes | dict, content_type: str) -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        if isinstance(payload, dict) and "application/json" not in content_type:
            content_type = "application/json"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        status, payload, content_type = handle_request(self.command, self.path, body, self.context)
        self._send(status, payload, content_type)

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def log_message(self, *args) -> None:
        pass


def main(port: int = 8000) -> None:
    Handler.context = new_context()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"FDE Command Center on http://localhost:{port}/frontend/investigate.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    import sys

    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8000
    main(port)
