"""Close Profits 2.0 — end-to-end on the REAL stack (no model of Firestore, no model of the route):
 * real FastAPI app (`main.app`) through fastapi.testclient,
 * real Firestore SDK against the Firestore EMULATOR (project close-profits-test-only),
 * real aster_gateway.AsterV3Client + execute_leg_once against an HTTP-level fake Aster (offline_fake_aster.FakeAster).
Only mocked: Aster (HTTP fake), Firebase ID-token verification (dependency override), the Secret Manager lookup.
A socket guard fails the test on any non-localhost connection. SKIPs unless FIRESTORE_EMULATOR_HOST is a localhost
address and no service-account credentials are in the environment. Never run against production."""
from __future__ import annotations

import os
import socket
import sys
import threading
import unittest
import uuid
from decimal import Decimal, ROUND_DOWN
from types import SimpleNamespace

HOST = os.environ.get("FIRESTORE_EMULATOR_HOST", "")
READY = HOST.startswith(("127.0.0.1:", "localhost:")) and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

S = SimpleNamespace(main=None, fake=None, uid=None, blocked=[], orig_connect=None)


def setUpModule():
    if not READY:
        raise unittest.SkipTest("needs the Firestore emulator on localhost and no service-account credentials")
    os.environ.update({
        "GOOGLE_CLOUD_PROJECT": "close-profits-test-only", "GCLOUD_PROJECT": "close-profits-test-only",
        "ASTER_LIVE_EXECUTION_ENABLED": "true",                       # route gate; the 'exchange' is the local fake
        "ASTER_POSITION_LOSS_AUTO_HEDGE_WORKER": "false", "ASTER_POSITION_LOSS_AUTO_HEDGE_EXECUTION_ENABLED": "true",
        "TRADEMENTOR_ENVIRONMENT": "e2e-test",
    })
    import google.auth
    import google.auth.credentials
    google.auth.default = lambda *a, **k: (google.auth.credentials.AnonymousCredentials(), "close-profits-test-only")

    S.orig_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in {"127.0.0.1", "::1", "localhost"}:
            S.blocked.append(address)
            raise OSError(f"E2E network guard: outbound connection to {address} blocked")
        return S.orig_connect(self, address)
    socket.socket.connect = guarded

    # main.py builds a Hyperliquid Info() client at import (public meta request over HTTPS). Not part of Close
    # Profits and must not touch the network in this test: replace it with an inert stand-in BEFORE the import.
    import hyperliquid.info

    class _InertInfo:
        def __init__(self, *args, **kwargs):
            pass
    hyperliquid.info.Info = _InertInfo

    sys.path.insert(0, os.path.dirname(__file__))
    import main
    from offline_fake_aster import FakeAster
    S.main = main
    RealClient = main.AsterV3Client

    class FakeBackedClient(RealClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = S.fake.transport()
            super().__init__(**kwargs)
    main.AsterV3Client = FakeBackedClient
    main.load_aster_secret = lambda user: SimpleNamespace(signer_address="0x" + "0" * 40, private_key="not-a-real-key")
    main.local_eip712_signer = lambda secret: (lambda encoded: "0x" + "0" * 130)
    main.app.dependency_overrides[main.authenticated_user] = lambda: {"uid": S.uid}


def tearDownModule():
    if S.orig_connect:
        socket.socket.connect = S.orig_connect
    if S.main:
        S.main.app.dependency_overrides.clear()


def floor_step(value, step):
    d = Decimal(str(step))
    return float((Decimal(repr(value)) / d).to_integral_value(rounding=ROUND_DOWN) * d)


@unittest.skipUnless(READY, "needs Firestore emulator")
class E2E(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from offline_fake_aster import FakeAster
        S.fake = self.fake = FakeAster()
        S.uid = self.uid = "e2e-" + uuid.uuid4().hex[:12]
        S.blocked.clear()
        self.http = TestClient(S.main.app, raise_server_exceptions=False)
        self.db = S.main.db

    def tearDown(self):
        self.assertEqual(S.blocked, [], "outbound network attempt detected")
        self.assertEqual(self.fake.unmocked, [], "unexpected Aster endpoint called")

    # ---- what the frontend does, step by step (aster-recent-trades.tsx closeProfits) ----------------------
    def preview(self, pct):
        r = self.http.get(f"/v1/me/aster/positions/manual-profit-close-plan?percentage={pct}")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def close(self, symbol, qty, pct, key=None):
        return self.http.post(f"/v1/me/aster/positions/{symbol}/close", json={
            "confirm": True, "side": "SHORT", "expected_quantity": qty, "percentage": pct,
            "idempotency_key": key or ("e2e-key-" + uuid.uuid4().hex)})

    def targets(self, pct):
        data = self.preview(pct)
        picked = {(s["symbol"]) for s in data["selected"] if str(s["side"]).upper() == "SHORT"}
        out = []
        for row in data["snapshot"]["rows"]:
            if row["symbol"] in picked and row["side"] == "SHORT":
                out.append((row["symbol"], abs(float(row["quantity"]))))
        return out

    def bulk(self, pct):
        """Frontend loop: fresh check before every close, close sequentially, stop on anything unclear."""
        result = {"closed": [], "stopped": None, "skipped": []}
        for symbol, qty in self.targets(pct):
            fresh = self.preview(pct)
            if not any(s["symbol"] == symbol for s in fresh["selected"]):
                result["skipped"].append(symbol); continue
            r = self.close(symbol, qty, pct)
            if r.status_code == 200:
                result["closed"].append(symbol)
            else:
                result["stopped"] = (symbol, r.status_code, r.json().get("detail")); break
        return result

    def seed_world(self, n=25, hedged=5):
        self.expected = {}
        for i in range(n):
            sym = f"S{i:02d}USDT"
            qty = round(37.123 + i * 1.7, 3)
            self.fake.add(sym, "SHORT", qty, mark=100.0, entry=105.0)
            self.expected[sym] = qty
            if i < hedged:                                   # Auto Hedge pair: LONG protected, SHORT is the hedge leg
                self.fake.add(sym, "LONG", qty, mark=100.0, entry=95.0)
                self.db.collection("asterPositionLossAutoHedge").document(self.uid).collection("pairs").document(sym).set({
                    "symbol": sym, "status": "HEDGED", "protectedSide": "LONG", "hedgeSide": "SHORT",
                    "rehedgeEnabled": True, "reservedHedgeQty": 0.0, "generationId": "g1"})
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).set({"enabled": True})
        # noise that must NEVER be selected/closed: losing SHORT, profitable LONG-only, SHORT at exactly $0.50
        self.fake.add("LOSSUSDT", "SHORT", 10.0, mark=110.0, entry=105.0)
        self.fake.add("LONGUSDT", "LONG", 10.0, mark=120.0, entry=100.0)
        self.fake.add("EDGEUSDT", "SHORT", 10.0, mark=100.0, entry=100.05)   # pnl = 0.5 exactly -> not > 0.50

    def pair(self, sym):
        return (self.db.collection("asterPositionLossAutoHedge").document(self.uid).collection("pairs").document(sym).get().to_dict())


class ImportSmoke(E2E):
    def test_real_app_imports_and_preview_route_answers_on_real_firestore(self):
        self.seed_world(n=3, hedged=1)
        data = self.preview(50)
        syms = sorted(s["symbol"] for s in data["selected"])
        self.assertEqual(syms, ["S00USDT", "S01USDT", "S02USDT"])


if __name__ == "__main__":
    unittest.main()
