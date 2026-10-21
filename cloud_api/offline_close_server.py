"""Local-only HTTP wrapper (127.0.0.1) around the REAL close/preview route source and the offline harness.
Used by web/tests/aster-close-profits-integration.test.mjs: real frontend handlers -> real Next proxy code -> this
server -> real route source -> simulated Aster ledger. Never contacts any network host."""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import offline_close_harness as h

fs = h.FakeFirestore()
ledger = h.Ledger(fs)
route, ns, HTTPException = h.build_backend(ledger, fs, extra=("preview_manual_profit_close_plan",))
USER = {"uid": "u1"}
request_log: list[dict] = []
probes: list[dict] = []


def to_dict(model):
    return {k: getattr(model, k) for k in ("confirm", "side", "expected_quantity", "percentage", "idempotency_key")}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, status, payload):
        body = json.dumps(payload, default=str).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path == "/v1/me/aster/positions/manual-profit-close-plan":
                pct = int(parse_qs(url.query).get("percentage", ["25"])[0])
                return self._send(200, ns.preview_manual_profit_close_plan(pct, USER))
            if url.path == "/__state":
                pairs = {k[-1]: v for k, v in fs.docs.items() if len(k) == 4 and k[2] == "pairs"}
                return self._send(200, {"orders": ledger.orders, "positions": {f"{s}|{d}": q for (s, d), q in ledger.pos.items()},
                                        "pairs": pairs, "rows": ledger.rows(), "requests": request_log,
                                        "probes": probes, "leaseHolder": (fs.docs.get(("asterAccountCoordination", "u1")) or {}).get("lease")})
            self._send(404, {"detail": "not found"})
        except HTTPException as exc:
            self._send(exc.status_code, {"detail": exc.detail})

    def do_POST(self):
        url = urlparse(self.path); data = self._body()
        if url.path == "/__setup":
            ledger.pos.clear(); ledger.orders.clear(); ledger.modes.clear(); fs.docs.clear(); request_log.clear()
            for row in data["positions"]:
                ledger.add(row["symbol"], row["side"], row["qty"], mark=row.get("mark", 100.0), entry=row.get("entry"),
                           minimum=row.get("minQty", 0.001), step=row.get("step", 0.001))
            for symbol, pair in data.get("pairs", {}).items():
                fs.docs[("asterPositionLossAutoHedge", "u1", "pairs", symbol)] = pair
            ledger.modes.update(data.get("modes", {}))
            probes.clear(); ledger.on_before_order = None
            if data.get("workerProbe"):
                # Auto Hedge worker (lease-first protocol) tries to run at the exact moment of every order
                def probe(symbol):
                    token = ns._acquire_aster_account_coordination("u1", "AUTO_HEDGE", "POSITION_LOSS_EXACT_1_TO_1")
                    probes.append({"symbol": symbol, "workerGotLease": bool(token)})
                    if token:
                        ns._release_aster_account_coordination("u1", token)
                ledger.on_before_order = probe
            return self._send(200, {"ok": True})
        parts = url.path.strip("/").split("/")
        if parts[:4] == ["v1", "me", "aster", "positions"] and parts[-1] == "close":
            request_log.append({"symbol": parts[-2], "body": data})
            try:
                req = h.request(data["expected_quantity"], percentage=data["percentage"], key=data["idempotency_key"], side=data["side"])
                if not data.get("confirm"):
                    raise HTTPException(422, "Bevestiging voor market sluiten ontbreekt")
                return self._send(200, route(parts[-2], req, USER))
            except HTTPException as exc:
                return self._send(exc.status_code, {"detail": exc.detail})
        self._send(404, {"detail": "not found"})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(server.server_address[1], flush=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    sys.stdin.read()          # parent closes stdin to stop
