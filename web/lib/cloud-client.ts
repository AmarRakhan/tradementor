import { firebaseAuth } from "./firebase";
import { demoModeEnabled } from "./demo-data";

const ASTER_SHARED_SNAPSHOT_PATH = "/api/exchanges/aster";
const ASTER_SHARED_SNAPSHOT_MAX_AGE_MS = 5000;

type SharedAsterSnapshotCache = {
  uid: string;
  payload: unknown;
  updatedAt: number;
};

type AsterSnapshotListener = (payload: unknown, updatedAt: number) => void;

let sharedAsterSnapshotCache: SharedAsterSnapshotCache | null = null;
let sharedAsterSnapshotInFlight: { uid: string; promise: Promise<unknown> } | null = null;
const sharedAsterSnapshotListeners = new Set<AsterSnapshotListener>();
let sharedAsterSnapshotFeedTimer: number | null = null;

function publishSharedAsterSnapshot(payload: unknown, updatedAt: number) {
  for (const listener of sharedAsterSnapshotListeners) {
    try { listener(payload, updatedAt); } catch { /* one UI consumer may not break the shared feed */ }
  }
}

function stopSharedAsterSnapshotFeedIfUnused() {
  if (sharedAsterSnapshotListeners.size || sharedAsterSnapshotFeedTimer === null) return;
  window.clearInterval(sharedAsterSnapshotFeedTimer);
  sharedAsterSnapshotFeedTimer = null;
}

function ensureSharedAsterSnapshotFeed() {
  if (typeof window === "undefined" || sharedAsterSnapshotFeedTimer !== null) return;
  void sharedAsterSnapshotRequest({ cache: "no-store" }).catch(() => {});
  sharedAsterSnapshotFeedTimer = window.setInterval(() => {
    if (document.visibilityState === "visible") {
      void sharedAsterSnapshotRequest({ cache: "no-store" }).catch(() => {});
    }
  }, ASTER_SHARED_SNAPSHOT_MAX_AGE_MS);
}

export function subscribeSharedAsterSnapshot(listener: AsterSnapshotListener) {
  sharedAsterSnapshotListeners.add(listener);
  const current = sharedAsterSnapshotCache;
  const uid = firebaseAuth.currentUser?.uid || "";
  if (current && uid && current.uid === uid) listener(current.payload, current.updatedAt);
  ensureSharedAsterSnapshotFeed();
  return () => {
    sharedAsterSnapshotListeners.delete(listener);
    stopSharedAsterSnapshotFeedIfUnused();
  };
}

export function readSharedAsterSnapshot() {
  const uid = firebaseAuth.currentUser?.uid || "";
  if (!sharedAsterSnapshotCache || !uid || sharedAsterSnapshotCache.uid !== uid) return null;
  return { payload: sharedAsterSnapshotCache.payload, updatedAt: sharedAsterSnapshotCache.updatedAt };
}

export function invalidateSharedAsterSnapshot() {
  sharedAsterSnapshotCache = null;
  sharedAsterSnapshotInFlight = null;
}

async function networkAuthenticatedRequest(path: string, init: RequestInit = {}) {
  const user = firebaseAuth.currentUser;
  if (!user) throw new Error("Log eerst in bij TradeMentor.");
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
  let { response, payload } = await request(false);
  if (response.status === 401) ({ response, payload } = await request(true));
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "De cloudopdracht is niet gelukt.");
  return payload;
}

async function sharedAsterSnapshotRequest(init: RequestInit = {}) {
  const user = firebaseAuth.currentUser;
  if (!user) throw new Error("Log eerst in bij TradeMentor.");
  const uid = user.uid;
  const now = Date.now();

  if (
    sharedAsterSnapshotCache
    && sharedAsterSnapshotCache.uid === uid
    && now - sharedAsterSnapshotCache.updatedAt <= ASTER_SHARED_SNAPSHOT_MAX_AGE_MS
  ) {
    return sharedAsterSnapshotCache.payload;
  }

  if (sharedAsterSnapshotInFlight?.uid === uid) return sharedAsterSnapshotInFlight.promise;

  const promise = networkAuthenticatedRequest(ASTER_SHARED_SNAPSHOT_PATH, init)
    .then((payload) => {
      const updatedAt = Date.now();
      sharedAsterSnapshotCache = { uid, payload, updatedAt };
      publishSharedAsterSnapshot(payload, updatedAt);
      return payload;
    })
    .finally(() => {
      if (sharedAsterSnapshotInFlight?.promise === promise) sharedAsterSnapshotInFlight = null;
    });

  sharedAsterSnapshotInFlight = { uid, promise };
  return promise;
}

export async function authenticatedRequest(path: string, init: RequestInit = {}) {
  const method = String(init.method || "GET").toUpperCase();
  if (demoModeEnabled() && method !== "GET" && method !== "HEAD") {
    throw new Error("Demo-modus is alleen-lezen. Er is niets opgeslagen of uitgevoerd.");
  }

  if (method !== "GET" && method !== "HEAD" && path.startsWith("/api/exchanges/aster")) {
    invalidateSharedAsterSnapshot();
  }

  if (method === "GET" && path === ASTER_SHARED_SNAPSHOT_PATH) {
    return sharedAsterSnapshotRequest(init);
  }

  return networkAuthenticatedRequest(path, init);
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
