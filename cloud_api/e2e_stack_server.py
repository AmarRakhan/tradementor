"""Real-stack backend for the frontend end-to-end test (web/tests/aster-close-profits-integration.test.mjs with
CP20_BACKEND=real): the REAL FastAPI app (main.app, served by uvicorn on 127.0.0.1) + the REAL Firestore SDK against the
Firestore EMULATOR + the real gateway/execute_leg_once against an HTTP-level fake Aster. Same control API as
offline_close_server.py (/__setup, /__mutate, /__state). Test-only; refuses to start without a localhost emulator."""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_close_profits_2_0_e2e_stack as t   # noqa: E402  (installs env, network guard, patched Aster client)

if not t.READY:
    raise SystemExit("refusing to start: needs FIRESTORE_EMULATOR_HOST on localhost and no service-account credentials")
t.setUpModule()

import uvicorn  # noqa: E402
from fastapi import Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from offline_fake_aster import FakeAster  # noqa: E402

main, S = t.S.main, t.S
probes: list[dict] = []
request_log: list[dict] = []
MODE_MAP = {"drop_after_accept": "timeout_after_accept", "reject_before": "reject"}


def _pairs():
    return main.db.collection("asterPositionLossAutoHedge").document(S.uid).collection("pairs")


def _new_world():
    S.fake = FakeAster()
    S.uid = "e2e-" + uuid.uuid4().hex[:12]
    probes.clear(); request_log.clear()


_new_world()


def _json(payload, status=200):
    return JSONResponse(json.loads(json.dumps(payload, default=str)), status_code=status)


@main.app.middleware("http")
async def log_close_requests(request: Request, call_next):
    if request.method == "POST" and request.url.path.endswith("/close"):
        try:
            request_log.append({"symbol": request.url.path.split("/")[-2], "body": json.loads(await request.body() or b"{}")})
        except Exception:
            pass
    return await call_next(request)


@main.app.post("/__setup")
async def setup(request: Request):
    data = await request.json()
    _new_world()
    for row in data["positions"]:
        S.fake.add(row["symbol"], row["side"], row["qty"], mark=row.get("mark", 100.0), entry=row.get("entry"),
                   minimum=row.get("minQty", 0.001), step=row.get("step", 0.001))
    for symbol, pair in data.get("pairs", {}).items():
        _pairs().document(symbol).set({**pair, "symbol": symbol})
    for symbol, mode in data.get("modes", {}).items():
        S.fake.modes[symbol] = MODE_MAP.get(mode, mode)
    if data.get("workerProbe"):
        uid = S.uid

        def probe(symbol):          # the Auto Hedge worker's lease-first protocol, at the exact moment of every order
            token = main._acquire_aster_account_coordination(uid, "AUTO_HEDGE", "POSITION_LOSS_EXACT_1_TO_1")
            probes.append({"symbol": symbol, "workerGotLease": bool(token)})
            if token:
                main._release_aster_account_coordination(uid, token)
        S.fake.on_order_start = probe
    return _json({"ok": True})


@main.app.post("/__mutate")
async def mutate(request: Request):
    data = await request.json()
    for sym, price in data.get("marks", {}).items():
        S.fake.mark[sym] = float(price)
    for key, qty in data.get("pos", {}).items():
        sym, side = key.split("|"); S.fake.pos[(sym, side)] = float(qty)
    for sym, doc in data.get("pairs", {}).items():
        _pairs().document(sym).set({**doc, "symbol": sym})
    if "autoHedgeEnabled" in data:
        main.db.collection("asterPositionLossAutoHedge").document(S.uid).set({"enabled": bool(data["autoHedgeEnabled"])})
    return _json({"ok": True})


@main.app.get("/__state")
def state():
    lease = ((main.db.collection("asterAccountCoordination").document(S.uid).get().to_dict() or {}).get("lease"))
    return _json({
        "orders": [[o["symbol"], o["positionSide"], o["qty"], o["cid"]] for o in S.fake.accepted()],
        "positions": {f"{s}|{d}": q for (s, d), q in S.fake.pos.items()},
        "pairs": {d.id: d.to_dict() for d in _pairs().stream()},
        "rows": S.fake._position_rows(), "requests": request_log, "probes": probes, "leaseHolder": lease,
        "unmocked": S.fake.unmocked, "blockedNetwork": [str(a) for a in S.blocked],
    })


if __name__ == "__main__":
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0)); sock.listen(128)
    server = uvicorn.Server(uvicorn.Config(main.app, log_level="warning"))
    threading.Thread(target=lambda: (sys.stdin.read(), setattr(server, "should_exit", True)), daemon=True).start()
    print(sock.getsockname()[1], flush=True)
    server.run(sockets=[sock])
