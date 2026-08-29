import { firebaseAuth } from "./firebase";
import { demoModeEnabled } from "./demo-data";

export async function authenticatedRequest(path: string, init: RequestInit = {}) {
  const method = String(init.method || "GET").toUpperCase();
  if (demoModeEnabled() && method !== "GET" && method !== "HEAD") {
    throw new Error("Demo-modus is alleen-lezen. Er is niets opgeslagen of uitgevoerd.");
  }
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
