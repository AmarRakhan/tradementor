#!/usr/bin/env python3
"""Publieke Aster-websocketprobe (geen sleutels, geen orders, geen accountdata).

Doel: bewijzen welke SUBSCRIBE-vorm Aster weigert met close 3001 "illegal request".
Elke test opent een eigen verbinding, stuurt één SUBSCRIBE en telt 12 s lang berichten.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

from websockets.asyncio.client import connect

URL = "wss://fstream.asterdex.com/stream"


async def probe(name: str, symbols: list[str], *, batch: int | None = None, seconds: float = 12.0) -> dict:
    params = [f"{s.lower()}@markPrice@1s" for s in symbols]
    out = {"test": name, "streams": len(params), "batch": batch, "messages": 0, "events": 0,
           "symbolsSeen": 0, "close": None, "firstReply": None}
    seen: set[str] = set()
    try:
        async with connect(URL, ping_interval=None, close_timeout=5, max_queue=4096) as ws:
            chunks = [params] if not batch else [params[i:i + batch] for i in range(0, len(params), batch)]
            for i, chunk in enumerate(chunks):
                await ws.send(json.dumps({"method": "SUBSCRIBE", "params": chunk, "id": i + 1}))
                if batch:
                    await asyncio.sleep(0.25)
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, end - time.monotonic()))
                except asyncio.TimeoutError:
                    break
                out["messages"] += 1
                msg = json.loads(raw)
                if out["firstReply"] is None:
                    out["firstReply"] = str(raw)[:200]
                data = msg.get("data") if isinstance(msg, dict) else None
                if isinstance(data, dict) and data.get("s"):
                    out["events"] += 1
                    seen.add(data["s"])
    except Exception as exc:  # close 3001 e.d.
        out["close"] = f"{type(exc).__name__}: {exc}"[:200]
    out["symbolsSeen"] = len(seen)
    return out


async def main() -> int:
    symbols = [line.strip() for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
    ordered = sorted(dict.fromkeys(s.upper() for s in symbols))
    ascii_only = [s for s in ordered if s.isascii()]
    non_ascii = [s for s in ordered if not s.isascii()]
    shard0, shard1 = ordered[:200], ordered[200:400]
    tests = [
        ("btc_single", ["BTCUSDT"], None),
        ("shard0_as_live", shard0, None),
        ("shard1_as_live", shard1, None),
        ("shard1_ascii_only", [s for s in shard1 if s.isascii()], None),
        ("non_ascii_single", non_ascii[:1], None),
        ("ascii_200_batch25", ascii_only[:200], 25),
    ]
    print(json.dumps({"total": len(ordered), "nonAscii": non_ascii}, ensure_ascii=False))
    for name, syms, batch in tests:
        if not syms:
            continue
        print(json.dumps(await probe(name, syms, batch=batch), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
