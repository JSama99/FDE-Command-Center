"""Read-only connection smoke test for the official Meta Responses API.

Explicit opt-in only: run `python3 -m backend.smoke_test`.
Makes exactly one minimal authorized request ("Reply with exactly: ok").
Never prints the API key. Never touches case data or production systems.
A successful response proves connectivity only, never an investigation result.
"""

from __future__ import annotations

import sys
import urllib.parse

from .meta_adapter import (
    CREDENTIAL_ENV_VAR,
    MetaModelAdapter,
    MissingCredentialsError,
    ProviderError,
    ProviderFailure,
    config_from_env,
)

SMOKE_INPUT = "Reply with exactly: ok"


def main() -> int:
    try:
        config, _key = config_from_env()
    except MissingCredentialsError as exc:
        print(f"smoke: disabled ({exc})")
        print(f"smoke: set {CREDENTIAL_ENV_VAR} in the environment and retry explicitly")
        return 2
    host = urllib.parse.urlparse(config.endpoint).hostname or config.endpoint
    print(f"smoke: POST {host}/responses model={config.model} mode={config.mode}")
    try:
        text = MetaModelAdapter(config).request_text(SMOKE_INPUT)
    except ProviderFailure as exc:
        # Sanitized diagnostic only: the allowlisted fields below. Never the
        # raw exception string, headers, credentials, or provider bodies.
        print("smoke: provider failure")
        for field in ("category", "http_status", "exception_class",
                      "timeout_occurred", "transmission"):
            print(f"smoke: {field}={exc.diagnostic.get(field)}")
        return 3
    except ProviderError:
        print("smoke: provider failure (unclassified)")
        return 3
    except Exception as exc:  # last-resort guard: class name only, never str(exc)
        print(f"smoke: unexpected failure ({type(exc).__name__})")
        return 3
    print(f"smoke: ok, received {len(text)} chars: {text[:80]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
