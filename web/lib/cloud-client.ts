import { firebaseAuth } from "./firebase";
import { onAuthStateChanged } from "firebase/auth";
import { demoModeEnabled } from "./demo-data";

// One short-lived, account-scoped read for the existing canonical Aster endpoint.
// This deduplicates UI readers; it does NOT introduce another exchange or trading pipeline.
type SharedAsterRequest = { uid: string; promise: Promise<unknown>; validUntil: number };
let sharedAsterRequest: SharedAsterRequest | null = null;
function clearSharedAsterRequest() { sharedAsterRequest = null; }
let observedUid: string | null = null;
if (typeof window !== "undefined") {
  onAuthStateChanged(firebaseAuth, (user) => {
    const nextUid = user?.uid ?? null;
    if (observedUid !== nextUid) {
      clearSharedAsterRequest();
      observedUid = nextUid;
    }
  });
}
function scopedAsterRequest(uid: string, load: () => Promise<unknown>): Promise<unknown> {
  if (observedUid !== uid) { clearSharedAsterRequest(); observedUid = uid; }
  const now = Date.now();
  if (sharedAsterRequest?.uid === uid && sharedAsterRequest.validUntil > now)
    return sharedAsterRequest.promise;
  const promise = load().then((payload) => {
    if (firebaseAuth.currentUser?.uid !== uid) throw new Error("Account gewijzigd tijdens het laden.");
    return payload;
  });
  const entry = { uid, promise, validUntil: now + 2000 };
  sharedAsterRequest = entry;
  void promise.catch(() => { if (sharedAsterRequest === entry) clearSharedAsterRequest(); });
  return promise;
}


export async function authenticatedRequest(path: string, init: RequestInit = {}) {
  const method = String(init.method || "GET").toUpperCase();
  if (demoModeEnabled() && method !== "GET" && method !== "HEAD") {
    throw new Error("Demo-modus is alleen-lezen. Er is niets opgeslagen of uitgevoerd.");
  }
  // Firebase persistence may still be restoring a session on initial render.
  await firebaseAuth.authStateReady();
  const user = firebaseAuth.currentUser;
  if (!user) {
    clearSharedAsterRequest();
    observedUid = null;
    throw new Error("Log eerst in bij TradeMentor.");
  }
  const request = async (forceRefresh: boolean) => {
    const token = await user.getIdToken(forceRefresh);
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    if (path.startsWith("/api/admin")) {
      const credential = window.localStorage.getItem("tradementor.admin.credential.v2");
      if (credential) headers.set("X-TradeMentor-Admin-Device", credential);
    }
    const response = await fetch(path, { ...init, headers });
    const payload = await response.json().catch(() => ({}));
    return { response, payload };
  };
  const load = async () => {
    let { response, payload } = await request(false);
    if (response.status === 401) ({ response, payload } = await request(true));
    if (!response.ok) {
      throw new Error(typeof payload.detail === "string" ? payload.detail :
        response.status === 403 ? "Geen toegang tot accountgegevens." :
        `Accountgegevens niet beschikbaar (HTTP ${response.status}).`);
    }
    return payload;
  };
  // GET requests for this exact endpoint share one per-user in-flight call and
  // a 2s freshness window. Mutations and all other endpoints are unaffected.
  if (path === "/api/exchanges/aster" && method === "GET") return scopedAsterRequest(user.uid, load);
  return load();
}

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
