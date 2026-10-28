"""Fictional seed data only. No real systems, no real people."""

from __future__ import annotations

from .ledger import LedgerStore
from .truth_map import TruthMapStore
from .workspace import Workspace, WorkspaceStore

FICTIONAL_NOTICE = "All data in this module is fictional."


def seed_sample() -> dict:
    workspaces = WorkspaceStore()
    maps = TruthMapStore()
    ledger = LedgerStore()

    ws = workspaces.create("Harbor Clinic Intake")

    pol = maps.add_policy(
        ws.id,
        "Fictional policy: intake referrals must be acknowledged within 4 business hours.",
    )
    s1 = maps.add_statement(ws.id, "clinic-coordinator", "Fictional report: referrals look sent but families say nothing arrived.")
    s2 = maps.add_statement(ws.id, "it-operator", "Fictional report: the server dashboard is green and jobs succeed.")
    e1 = maps.add_event(ws.id, "referral-batch", "Fictional event: batch #1042 marked delivered by sender queue.")
    e2 = maps.add_event(ws.id, "inbox-check", "Fictional event: clinic inbox shows zero new referrals for the same window.")

    l1 = ledger.append(ws.id, "Fictional hypothesis: sender receipt does not equal receiver intake.", [e1.id, e2.id])
    l2 = ledger.append(ws.id, "Fictional hypothesis: routing table points at a stale inbox.", [s1.id, pol.id])

    return {"workspace": ws, "workspaces": workspaces, "maps": maps, "ledger": ledger}
