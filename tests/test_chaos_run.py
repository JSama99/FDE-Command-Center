"""MC-005d: controlled local chaos execution endpoint tests.

Real handle_request paths with explicit transport records. No sockets,
no provider calls, no state mutation tolerated.
"""

import hashlib
import json
import os
import unittest
from pathlib import Path

from backend.chaos_simulation import run_simulation, validate_simulation_result
from backend.server import handle_request, new_context

ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "fixtures" / "case-001"
CHAOS_DIR = ROOT / "fixtures" / "chaos-lab"
RECEIPTS_DIR = ROOT / "evaluator-private" / "receipts"


def transport(peer="127.0.0.1", origin="http://localhost:8000",
              host="localhost:8000"):
    return {"peer": peer, "origin": origin, "host": host,
            "local_origins": {"http://localhost:8000",
                              "http://127.0.0.1:8000"},
            "local_hosts": {"localhost:8000", "127.0.0.1:8000"}}


def post(ctx, payload, transport_record="default"):
    if isinstance(payload, dict):
        raw = json.dumps(payload).encode()
    elif isinstance(payload, str):
        raw = payload.encode()
    else:
        raw = payload
    kwargs = {} if transport_record == "default" else {"transport": transport_record}
    return handle_request("POST", "/api/chaos/run", raw, ctx, **kwargs)


def hashes(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(directory).iterdir()) if p.is_file()}


class ChaosRunGateTest(unittest.TestCase):
    def test_default_deny_without_transport(self):
        status, payload, _ = post(new_context(),
                                  {"scenario_id": "CHS-ACK-01",
                                   "variant": "injected"})
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "forbidden")

    def test_non_loopback_peer_rejected(self):
        for peer in ("192.168.1.10", "10.0.0.5", "", None):
            status, payload, _ = post(
                new_context(), {"scenario_id": "CHS-ACK-01",
                                "variant": "injected"},
                transport(peer=peer))
            self.assertEqual(status, 403, msg=str(peer))
            self.assertEqual(payload["error"], "forbidden")

    def test_origin_and_host_enforced(self):
        ctx = new_context()
        good = {"scenario_id": "CHS-ACK-01", "variant": "injected"}
        for kwargs in ({"origin": "http://evil.test:8000"},
                       {"origin": None},
                       {"host": "evil.test:8000"},
                       {"host": None},
                       {"host": "localhost:9999"}):
            args = {"peer": "127.0.0.1", "origin": "http://localhost:8000",
                    "host": "localhost:8000",
                    "local_origins": {"http://localhost:8000",
                                      "http://127.0.0.1:8000"},
                    "local_hosts": {"localhost:8000", "127.0.0.1:8000"}}
            args.update(kwargs)
            status, payload, _ = post(ctx, good, args)
            self.assertEqual(status, 403, msg=str(kwargs))
            self.assertEqual(payload["error"], "forbidden")

    def test_loopback_variants_accepted_at_gate(self):
        status, payload, _ = post(
            new_context(), {"scenario_id": "CHS-ACK-01", "variant": "baseline"},
            transport(peer="::1", origin="http://127.0.0.1:8000",
                       host="127.0.0.1:8000"))
        self.assertEqual(status, 200)
        self.assertTrue(payload["ran"])


class ChaosRunValidationTest(unittest.TestCase):
    def run_ok(self, ctx, payload):
        status, payload_out, _ = post(ctx, payload, transport())
        self.assertEqual(status, 200)
        self.assertTrue(payload_out["ran"])
        return payload_out

    def test_exactly_one_validated_simulation(self):
        expected = run_simulation("CHS-ACK-01", "injected")
        out = self.run_ok(new_context(), {"scenario_id": "CHS-ACK-01",
                                          "variant": "injected"})
        self.assertEqual(out["result"], expected)
        validate_simulation_result(out["result"])
        self.assertIsInstance(out["executed_at"], int)

    def test_rejections(self):
        ctx = new_context()
        cases = [
            ({"scenario_id": "CHS-NOPE", "variant": "injected"},
             400, "unknown-scenario"),
            ({"scenario_id": "CHS-ACK-01", "variant": "chaos"},
             400, "unknown-variant"),
            ({"scenario_id": "CHS-ACK-01", "variant": "injected",
              "extra": 1}, 400, "bad_request"),
            ({"scenario_id": "CHS-ACK-01"}, 400, "bad_request"),
            ("not json{", 400, "bad_request"),
            (b"", 400, "bad_request"),
            ("x" * 3000, 413, "too_large"),
        ]
        for payload, status_want, error_want in cases:
            status, payload_out, _ = post(ctx, payload, transport())
            self.assertEqual(status, status_want, msg=str(payload)[:40])
            self.assertEqual(payload_out["error"], error_want)
            self.assertNotIn("result", payload_out)

    def test_no_mission_or_file_mutation(self):
        ctx = new_context()
        status, before, _ = handle_request("GET", "/api/mission", None, ctx)
        self.assertEqual(status, 200)
        case_before = hashes(CASE_DIR)
        chaos_before = hashes(CHAOS_DIR)
        receipts_before = hashes(RECEIPTS_DIR)
        self.run_ok(ctx, {"scenario_id": "CHS-WINDOW-01",
                          "variant": "injected"})
        self.run_ok(ctx, {"scenario_id": "CHS-ASSIGN-01",
                          "variant": "baseline"})
        status, after, _ = handle_request("GET", "/api/mission", None, ctx)
        self.assertEqual(status, 200)
        self.assertEqual(before, after)
        self.assertEqual(hashes(CASE_DIR), case_before)
        self.assertEqual(hashes(CHAOS_DIR), chaos_before)
        self.assertEqual(hashes(RECEIPTS_DIR), receipts_before)

    def test_no_provider_dependency(self):
        saved = os.environ.pop("MODEL_API_KEY", None)
        try:
            self.run_ok(new_context(), {"scenario_id": "CHS-ACK-01",
                                        "variant": "injected"})
        finally:
            if saved is not None:
                os.environ["MODEL_API_KEY"] = saved


class ChaosRunSocketTest(unittest.TestCase):
    """Real loopback HTTP against the actual server handler (no mocks)."""

    @classmethod
    def setUpClass(cls):
        import threading

        from backend.server import Handler, new_context
        from http.server import ThreadingHTTPServer

        cls._saved = Handler.context
        Handler.context = new_context()
        try:
            cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        except OSError as exc:
            raise unittest.SkipTest(
                "listening sockets unavailable in this sandbox; "
                "run outside the sandbox for real-socket verification"
            ) from exc
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        from backend.server import Handler

        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=10)
        Handler.context = cls._saved

    def request(self, body, origin="ORIGIN", host="HOST"):
        import http.client

        origin = (f"http://localhost:{self.port}" if origin == "ORIGIN"
                  else origin)
        host = (f"localhost:{self.port}" if host == "HOST" else host)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if origin is not None:
            headers["Origin"] = origin
        if host is not None:
            headers["Host"] = host
        conn.request("POST", "/api/chaos/run", body=json.dumps(body),
                     headers=headers)
        response = conn.getresponse()
        payload = json.loads(response.read().decode())
        conn.close()
        return response.status, payload

    def test_binds_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_socket_run_succeeds(self):
        status, payload = self.request({"scenario_id": "CHS-ACK-01",
                                        "variant": "injected"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ran"])
        validate_simulation_result(payload["result"])
        self.assertEqual(payload["result"]["detector"]["flagged"], ["CHS-A"])

    def test_socket_rejects_cross_origin(self):
        status, payload = self.request(
            {"scenario_id": "CHS-ACK-01", "variant": "injected"},
            origin="http://evil.test:8000")
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "forbidden")

    def test_socket_rejects_missing_origin(self):
        status, payload = self.request(
            {"scenario_id": "CHS-ACK-01", "variant": "injected"},
            origin=None)
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
