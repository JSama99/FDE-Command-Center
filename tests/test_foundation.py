"""Foundation tests. Stdlib unittest only."""

import unittest

from backend.fixtures import FICTIONAL_NOTICE, seed_sample
from backend.ledger import LedgerStore
from backend.model_client import ModelConfig, NoOpModelClient
from backend.truth_map import TruthMapStore
from backend.workspace import WorkspaceStore


class FoundationTest(unittest.TestCase):
    def test_workspace_create_and_get(self):
        stores = WorkspaceStore()
        ws = stores.create("Harbor Clinic Intake")
        self.assertEqual(stores.get(ws.id), ws)
        self.assertEqual(len(stores.list()), 1)

    def test_truth_map_keeps_types_distinct(self):
        seed = seed_sample()
        ws = seed["workspace"]
        m = seed["maps"].for_workspace(ws.id)
        self.assertEqual(len(m.policies), 1)
        self.assertEqual(len(m.statements), 2)
        self.assertEqual(len(m.events), 2)

    def test_ledger_is_insertion_ordered_per_workspace(self):
        ledger = LedgerStore()
        ledger.append("ws-0001", "first")
        ledger.append("ws-0001", "second")
        ledger.append("ws-0002", "other-workspace")
        got = [e.hypothesis for e in ledger.list_for("ws-0001")]
        self.assertEqual(got, ["first", "second"])

    def test_seed_is_fictional(self):
        self.assertIn("fictional", FICTIONAL_NOTICE.lower())
        seed = seed_sample()
        ws = seed["workspace"]
        m = seed["maps"].for_workspace(ws.id)
        texts = [m.policies[0].text, m.statements[0].text, m.events[0].detail]
        self.assertTrue(all("fictional" in t.lower() for t in texts))

    def test_model_client_seam_needs_no_network(self):
        client = NoOpModelClient(ModelConfig())
        self.assertIn("not configured", client.summarize("anything").lower())


if __name__ == "__main__":
    unittest.main()
