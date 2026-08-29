from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    s = p.read_text()
    count = s.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:100]!r}")
    p.write_text(s.replace(old, new, 1))


replace_once(
    "cloud_api/aster_realtime.py",
    "    def symbols(self) -> tuple[str, ...]:\n        with self._lock:\n            return tuple(sorted(self._by_symbol))\n\n    def tenant_count",
    "    def symbols(self) -> tuple[str, ...]:\n        with self._lock:\n            return tuple(sorted(self._by_symbol))\n\n    def symbols_for(self, uid: str) -> tuple[str, ...]:\n        tenant = str(uid).strip()\n        with self._lock:\n            return tuple(sorted(symbol for symbol, members in self._by_symbol.items() if tenant in members))\n\n    def tenant_count",
)
replace_once(
    "cloud_api/aster_realtime.py",
    "        self._latest_by_symbol: dict[str, RealtimeMarketEvent] = {}\n\n    def stop(self) -> None:\n        self._stop.set()\n",
    "        self._latest_by_symbol: dict[str, RealtimeMarketEvent] = {}\n        self._loop: asyncio.AbstractEventLoop | None = None\n\n    def stop(self) -> None:\n        loop = self._loop\n        if loop is not None and loop.is_running():\n            loop.call_soon_threadsafe(self._stop.set)\n        else:\n            self._stop.set()\n",
)
replace_once(
    "cloud_api/aster_realtime.py",
    "    async def run(self) -> None:\n        backoff = 1.0\n",
    "    async def run(self) -> None:\n        self._loop = asyncio.get_running_loop()\n        backoff = 1.0\n",
)

health_anchor = '''@app.get("/internal/aster-realtime/health")
def aster_realtime_health(authorization:str|None=Header(default=None))->dict[str,Any]:
    verify_internal_cloud_request(authorization);worker=_aster_realtime_worker
    return {"workerEnabled":os.getenv("ASTER_REALTIME_WORKER","false").lower()=="true","executionEnabled":os.getenv("ASTER_REALTIME_EXECUTION_ENABLED","false").lower()=="true",**(worker.health() if worker else {"connected":False,"subscriptions":0,"tenants":0})}

'''
health_plus = health_anchor + '''@app.on_event("shutdown")
def stop_aster_realtime_worker()->None:
    worker=_aster_realtime_worker
    if worker is not None:worker.stop()


@app.get("/v1/me/aster/realtime/events")
def aster_realtime_events(user:dict[str,Any]=Depends(authenticated_user))->StreamingResponse:
    uid=str(user["uid"])
    async def stream():
        last_seen:dict[str,int]={};last_heartbeat=time.monotonic()
        while True:
            worker=_aster_realtime_worker
            if worker is None:
                yield "event: status\\ndata: {\\"connected\\":false,\\"reason\\":\\"worker-disabled\\"}\\n\\n"
                await asyncio.sleep(2.0);continue
            allowed=worker.registry.symbols_for(uid)
            latest=worker.latest(allowed)
            for symbol,payload in latest.items():
                stamp=int(payload.get("receivedAtMs",0) or 0)
                if stamp<=last_seen.get(symbol,0):continue
                last_seen[symbol]=stamp
                yield f"event: mark\\ndata: {json.dumps(payload,separators=(',',':'))}\\n\\n"
            now=time.monotonic()
            if now-last_heartbeat>=15:
                yield ": heartbeat\\n\\n";last_heartbeat=now
            await asyncio.sleep(.25)
    return StreamingResponse(stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache, no-transform","X-Accel-Buffering":"no","Connection":"keep-alive"})


'''
replace_once("cloud_api/main.py", health_anchor, health_plus)

cloud = Path("web/lib/cloud-client.ts")
s = cloud.read_text()
if "export async function authenticatedStream" in s:
    raise SystemExit("cloud-client already patched")
s += '''
export async function authenticatedStream(path: string, init: RequestInit = {}) {
  const user = firebaseAuth.currentUser;
  if (!user) throw new Error("Log eerst in bij TradeMentor.");
  const request = async (forceRefresh: boolean) => {
    const token = await user.getIdToken(forceRefresh);
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    return fetch(path, { ...init, headers, cache: "no-store" });
  };
  let response = await request(false);
  if (response.status === 401) response = await request(true);
  if (!response.ok || !response.body) throw new Error("Realtime Aster-feed is niet beschikbaar.");
  return response;
}
'''
cloud.write_text(s)

replace_once(
    "web/lib/use-exchange-data.ts",
    'import { authenticatedRequest } from "./cloud-client";',
    'import { authenticatedRequest, authenticatedStream } from "./cloud-client";\nimport { applyAsterRealtimeMark, parseSseChunk } from "./aster-realtime.mjs";',
)
realtime_effect = '''  useEffect(() => {
    if (!cloudReady || !uid) return;
    const controller = new AbortController();
    let stopped = false;
    let retryMs = 1000;
    const run = async () => {
      while (!stopped) {
        try {
          const response = await authenticatedStream("/api/exchanges/aster/realtime", { signal: controller.signal });
          const reader = response.body!.getReader();
          const decoder = new TextDecoder();
          let buffer = ""; retryMs = 1000;
          while (!stopped) {
            const { value, done } = await reader.read();
            if (done) throw new Error("Realtime Aster-stream gesloten");
            const parsed = parseSseChunk(buffer, decoder.decode(value, { stream: true }));
            buffer = parsed.rest;
            for (const event of parsed.events) {
              if (!event || typeof event !== "object" || !("symbol" in event) || !("markPrice" in event)) continue;
              setState((current) => {
                if (current.uid !== uid) return current;
                const previous = current.snapshots.aster;
                if (!previous.data) return current;
                const data = applyAsterRealtimeMark(previous.data, event) as Record<string, unknown>;
                if (data === previous.data) return current;
                return { ...current, snapshots: { ...current.snapshots, aster: { ...previous, data, updatedAt: Date.now() } } };
              });
            }
          }
        } catch (error) {
          if (stopped || controller.signal.aborted) return;
          console.warn("[TradeMentor Aster realtime] reconnect", error);
          await new Promise((resolve) => window.setTimeout(resolve, retryMs));
          retryMs = Math.min(15_000, retryMs * 2);
        }
      }
    };
    void run();
    return () => { stopped = true; controller.abort(); };
  }, [cloudReady, uid]);

'''
replace_once(
    "web/lib/use-exchange-data.ts",
    "  useEffect(() => {\n    if (!cloudReady) return;\n    refreshAll();\n",
    realtime_effect + "  useEffect(() => {\n    if (!cloudReady) return;\n    refreshAll();\n",
)

route = Path("web/app/api/exchanges/aster/realtime/route.ts")
route.parent.mkdir(parents=True, exist_ok=True)
route.write_text('''import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
const CLOUD_API = process.env.TRADEMENTOR_CLOUD_API_URL || "https://tradementor-api-604335232956.europe-west4.run.app";

export async function GET(request: NextRequest) {
  const authorization = request.headers.get("authorization");
  if (!authorization?.startsWith("Bearer ")) return new Response("Unauthorized", { status: 401 });
  const upstream = await fetch(`${CLOUD_API}/v1/me/aster/realtime/events`, {
    headers: { Authorization: authorization, Accept: "text/event-stream" },
    cache: "no-store",
    signal: request.signal,
  });
  if (!upstream.ok || !upstream.body) return new Response("Realtime feed unavailable", { status: upstream.status || 502 });
  return new Response(upstream.body, { status: 200, headers: {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
  }});
}
''')

backend_test = Path("cloud_api/test_aster_realtime.py")
t = backend_test.read_text()
if "test_registry_symbols_for_tenant_isolated" not in t:
    t += '''\n\ndef test_registry_symbols_for_tenant_isolated():\n    registry=SymbolRegistry();registry.replace({"SOLUSDT":["a","b"],"BTCUSDT":["a"],"DOGEUSDT":["b"]})\n    assert registry.symbols_for("a")== ("BTCUSDT","SOLUSDT")\n    assert registry.symbols_for("b")== ("DOGEUSDT","SOLUSDT")\n    assert registry.symbols_for("unknown")==()\n'''
backend_test.write_text(t)

Path("web/tests/aster-realtime.test.mjs").write_text('''import test from "node:test";
import assert from "node:assert/strict";
import { applyAsterRealtimeMark, parseSseChunk } from "../lib/aster-realtime.mjs";

test("live mark updates only matching position and recalculates PnL", () => {
  const source={positions:[{symbol:"SOLUSDT",side:"LONG",quantity:2,entryPrice:100,markPrice:100,unrealizedPnl:0},{symbol:"BTCUSDT",side:"SHORT",quantity:1,entryPrice:50,markPrice:50,unrealizedPnl:0}]};
  const out=applyAsterRealtimeMark(source,{symbol:"SOLUSDT",markPrice:103,receivedAtMs:10,transportLatencyMs:4});
  assert.equal(out.positions[0].markPrice,103);assert.equal(out.positions[0].unrealizedPnl,6);assert.equal(out.positions[0].notionalUsd,206);
  assert.equal(out.positions[1],source.positions[1]);assert.equal(out.unrealizedPnl,6);assert.equal(source.positions[0].markPrice,100);
});
test("short PnL uses inverse price direction",()=>{const out=applyAsterRealtimeMark({positions:[{symbol:"X",side:"SHORT",quantity:2,entryPrice:10}]},{symbol:"X",markPrice:8});assert.equal(out.positions[0].unrealizedPnl,4)});
test("SSE parser preserves split frames",()=>{const a=parseSseChunk('', 'event: mark\\ndata: {"symbol":"SOL');const b=parseSseChunk(a.rest,'USDT","markPrice":101}\\n\\n');assert.equal(b.events[0].symbol,'SOLUSDT');assert.equal(b.events[0].markPrice,101)});
''')
