"""Meta Model API adapter for muse-spark-1.3 (Standard).

Official Responses API (https://dev.meta.ai/docs/quickstart):
- POST https://api.meta.ai/v1/responses
- Body: {"model": "muse-spark-1.3", "input": "<text>",
         "max_output_tokens": <explicit cap, documented output-token limit>}
- Bearer authentication from the MODEL_API_KEY environment variable.
- Assistant text is extracted from the output message content blocks.
- Pricing (official pricing-rate-limits page): Muse Spark 1.3 Standard
  $1.25/1M input, $0.15/1M cached input, $4.25/1M output tokens. The provider
  publishes rate limits but no account spending cap; our guardrails are one
  request per explicit action, no retries, a 30s timeout, and the output cap.

Credentials stay server-side: read from the environment at call time, attached
only to the outbound request, never logged, never written to files, and never
sent to the frontend. Stdlib only (urllib + json); no SDK. No Contributor
model IDs are used anywhere.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

MODEL_ID = "muse-spark-1.3"
MODE = "standard"
BASE_URL = "https://api.meta.ai/v1"
RESPONSES_PATH = "/responses"
DEFAULT_ENDPOINT = BASE_URL + RESPONSES_PATH
CREDENTIAL_ENV_VAR = "MODEL_API_KEY"
LEGACY_CREDENTIAL_ENV_VAR = "META_API_KEY"
ENDPOINT_ENV_VAR = "META_MODEL_ENDPOINT"

# Conservative explicit output cap. Largest observed structured output in
# stored evaluations is ~700 tokens; 4096 gives headroom without changing
# evidence input or investigation logic. Supported: the documented model
# maximum output is 131,072 tokens, so 4096 fits with wide margin. Bounds
# per-call output spend to 4096/1M * $4.25 = $0.0174 at official Standard
# pricing. Raised from 2048 after a live truncation (incomplete /
# max_output_tokens); prior responses and scores are unaffected.
MAX_OUTPUT_TOKENS = 4096
MIN_OUTPUT_TOKENS = 16

# Fallback used only when a caller supplies no instructions. Production callers
# (backend.investigation.produce_investigation) always pass instructions built
# from the evidence registry, which describe the exact schema and references.
FALLBACK_INSTRUCTIONS = (
    "Return a single JSON object. Every item must cite its evidence references. "
    "Use only the evidence provided below."
)


class MissingCredentialsError(RuntimeError):
    pass


class ProviderError(RuntimeError):
    pass


# Failure categories for sanitized diagnostics. Assigned only from exception
# or response evidence; never guessed. Transmission vocabulary: "confirmed"
# (the provider answered, so the request demonstrably arrived), "possible"
# (a timeout may have been processed server-side), "unknown" (everything
# else — never overclaimed as unsent).
FAILURE_CATEGORIES = (
    "invalid-request", "authorization", "rate-limited", "provider-error",
    "connection", "dns", "tls", "timeout",
)

CATEGORY_EXPLANATIONS = {
    "invalid-request": "the provider rejected the request as invalid (HTTP 400)",
    "authorization": "the provider refused authorization (HTTP 401/403); check the server-side key",
    "rate-limited": "the provider rate-limited the request (HTTP 429) without a stated cause",
    "provider-error": "the provider failed to complete the request",
    "connection": "the request could not reach the provider (connection error)",
    "dns": "the provider hostname could not be resolved (DNS error)",
    "tls": "the secure connection to the provider failed (TLS error)",
    "timeout": "the provider request timed out",
}


# Documented Responses API response statuses (corroborated across the
# provider's Responses documentation and independent implementations).
# Anything else is recorded as "other": raw provider text is never logged.
RESPONSE_STATUSES = ("completed", "in_progress", "incomplete", "failed",
                     "cancelled")

# Documented incomplete_details reasons. Only these are preserved;
# any other reason is dropped (recorded as None), never logged raw.
INCOMPLETE_REASONS = ("max_output_tokens", "content_filter")


def sanitize_response_status(status: object) -> str:
    return status if status in RESPONSE_STATUSES else "other"


def sanitize_incomplete_reason(response: object) -> str | None:
    details = response.get("incomplete_details") if isinstance(response, dict) else None
    reason = details.get("reason") if isinstance(details, dict) else None
    return reason if reason in INCOMPLETE_REASONS else None


class ProviderFailure(ProviderError):
    """ProviderError carrying a sanitized diagnostic dict. The diagnostic
    holds only category, HTTP status, exception class, timeout flag, and
    transmission assessment — never keys, headers, bodies, or provider
    error text that could carry sensitive content."""

    def __init__(self, message: str, diagnostic: dict) -> None:
        super().__init__(message)
        self.diagnostic = dict(diagnostic)


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError,)):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        return isinstance(reason, (TimeoutError,)) or "timed out" in str(reason).lower()
    return False


def classify_transport_error(exc: BaseException) -> dict:
    """Classify a urlopen failure from exception evidence only."""
    name = type(exc).__name__
    if isinstance(exc, urllib.error.HTTPError):
        status = exc.code
        if status == 400:
            category = "invalid-request"
        elif status in (401, 403):
            category = "authorization"
        elif status == 429:
            category = "rate-limited"
        else:
            category = "provider-error"
        return {"category": category, "http_status": status,
                "exception_class": name, "timeout_occurred": False,
                "transmission": "confirmed", "response_status": None,
                "incomplete_reason": None}
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if _is_timeout(exc) or _is_timeout(reason):
        return {"category": "timeout", "http_status": None,
                "exception_class": name, "timeout_occurred": True,
                "transmission": "possible", "response_status": None,
                "incomplete_reason": None}
    import socket
    import ssl

    target = reason if not isinstance(reason, str) else exc
    if isinstance(target, ssl.SSLError):
        category = "tls"
    elif isinstance(target, socket.gaierror):
        category = "dns"
    else:
        category = "connection"
    return {"category": category, "http_status": None,
            "exception_class": name, "timeout_occurred": False,
            "transmission": "unknown", "response_status": None,
            "incomplete_reason": None}


class MalformedResponseError(ValueError):
    pass


@dataclass
class MetaConfig:
    model: str = MODEL_ID
    mode: str = MODE
    endpoint: str = DEFAULT_ENDPOINT
    timeout_seconds: int = 30
    max_output_tokens: int = MAX_OUTPUT_TOKENS

    def __post_init__(self) -> None:
        if self.model != MODEL_ID:
            raise ValueError(f"only {MODEL_ID} is supported, got {self.model!r}")
        if self.mode != MODE:
            raise ValueError(f"only Standard mode ({MODE!r}) is supported, got {self.mode!r}")
        if self.max_output_tokens < MIN_OUTPUT_TOKENS:
            raise ValueError(
                f"max_output_tokens minimum is {MIN_OUTPUT_TOKENS}, "
                f"got {self.max_output_tokens!r}")


def read_api_key() -> str:
    for var in (CREDENTIAL_ENV_VAR, LEGACY_CREDENTIAL_ENV_VAR):
        key = os.environ.get(var, "")
        if key.strip():
            # Strip surrounding whitespace: a pasted trailing newline or space
            # would otherwise be sent inside the Bearer token and rejected
            # with HTTP 401. The value itself is never logged.
            return key.strip()
    raise MissingCredentialsError(
        f"{CREDENTIAL_ENV_VAR} is not set; live requests are disabled"
    )


def config_from_env() -> tuple[MetaConfig, str]:
    """Return (config, api_key). Raises MissingCredentialsError when absent."""
    key = read_api_key()
    endpoint = os.environ.get(ENDPOINT_ENV_VAR, DEFAULT_ENDPOINT)
    return MetaConfig(endpoint=endpoint), key


# Documented reasoning-effort values for the Responses API. "low" spends
# fewer reasoning tokens (which share the max_output_tokens budget) for
# tightly scratched structured outputs. Omitted by default: callers that do
# not opt in send exactly the previous body.
REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")

# Single-variable experiment (Task 009.6e): structured investigations use
# low reasoning effort after repeated truncation at higher budgets.
INVESTIGATION_REASONING_EFFORT = "low"


def build_responses_payload(model: str, text_input: str,
                            max_output_tokens: int = MAX_OUTPUT_TOKENS,
                            reasoning_effort: str | None = None) -> dict:
    """Official Responses API request body. Standard tier is selected by the
    model id itself; the schema carries no separate mode parameter.
    max_output_tokens is the documented output-token limit field; reasoning
    effort is included only when explicitly requested."""
    if reasoning_effort is not None and reasoning_effort not in REASONING_EFFORTS:
        raise ValueError(f"unknown reasoning effort: {reasoning_effort!r}")
    body = {"model": model, "input": text_input,
            "max_output_tokens": max_output_tokens}
    if reasoning_effort is not None:
        body["reasoning"] = {"effort": reasoning_effort}
    return body


def extract_response_text(response: object) -> str:
    """Extract assistant text from a Responses API response object."""
    if not isinstance(response, dict):
        raise MalformedResponseError("provider response must be a JSON object")
    status = response.get("status", "completed")
    if status != "completed":
        raise ProviderFailure(
            "provider response did not complete",
            {"category": "provider-error", "http_status": None,
             "exception_class": "ProviderError", "timeout_occurred": False,
             "transmission": "confirmed",
             "response_status": sanitize_response_status(status),
             "incomplete_reason": sanitize_incomplete_reason(response)})
    output = response.get("output")
    if not isinstance(output, list):
        raise MalformedResponseError("provider response has no output list")
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in ("output_text", "text"):
                text = block.get("text", "")
                if isinstance(text, str) and text:
                    parts.append(text)
    if not parts:
        raise MalformedResponseError("provider response contains no assistant text")
    return "".join(parts)


class MetaModelAdapter:
    """Live adapter for the official Responses API. Fails safely without
    credentials or provider access; never sends anything automatically."""

    def __init__(self, config: MetaConfig | None = None, api_key: str | None = None) -> None:
        self.config = config or MetaConfig()
        self._api_key = api_key

    def _key(self) -> str:
        if self._api_key and self._api_key.strip():
            return self._api_key.strip()
        return read_api_key()

    def _post(self, text_input: str,
              reasoning_effort: str | None = None) -> dict:
        key = self._key()
        body = json.dumps(build_responses_payload(
            self.config.model, text_input,
            self.config.max_output_tokens, reasoning_effort)).encode("utf-8")
        request = urllib.request.Request(
            self.config.endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        # Credential is attached only to the outbound request object; it is
        # never logged, never written to disk, and never sent to the frontend.
        request.add_unredirected_header("Authorization", f"Bearer {key}")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except (urllib.error.URLError, OSError) as exc:
            # Single attempt, no retries: classify from exception evidence and
            # raise with a sanitized diagnostic. The raw exception text may
            # echo URLs or provider content, so the message stays generic.
            raise ProviderFailure(
                "provider request failed", classify_transport_error(exc)) from exc
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MalformedResponseError(f"provider returned non-JSON: {exc}") from exc
        return parsed

    def request_text(self, text_input: str) -> str:
        # Generic text path: unchanged body, no reasoning control.
        return extract_response_text(self._post(text_input))

    def request_structured(self, context: dict, instructions: str | None = None,
                           reasoning_effort: str | None = None) -> dict:
        text_input = (instructions or FALLBACK_INSTRUCTIONS) + "\n\nEvidence:\n" + json.dumps(context)
        text = extract_response_text(self._post(text_input, reasoning_effort))
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MalformedResponseError(f"model returned malformed JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise MalformedResponseError("model response must be a JSON object")
        return parsed

    def summarize(self, prompt: str) -> str:
        return self.request_text(prompt)


class MockAdapter:
    """No-network adapter for tests and offline use."""

    def __init__(self, canned: dict | None = None) -> None:
        self.canned = canned
        self.last_context: dict | None = None
        self.last_instructions: str | None = None
        self.last_reasoning_effort: str | None = None

    def request_structured(self, context: dict, instructions: str | None = None,
                           reasoning_effort: str | None = None) -> dict:
        self.last_context = context
        self.last_instructions = instructions
        self.last_reasoning_effort = reasoning_effort
        if self.canned is not None:
            return self.canned
        return {
            "observations": [],
            "competing_hypotheses": [],
            "unresolved_questions": [],
            "diagnostic_experiments": [],
            "provisional_recommendation": {
                "text": "Fictional mock: no recommendation without evidence.",
                "refs": ["events.csv"],
                "requires_human_approval": True,
                "executes_production_change": False,
            },
            "counter_evidence": [],
        }

    def summarize(self, prompt: str) -> str:
        return "fictional-summary: mock adapter, no network"
