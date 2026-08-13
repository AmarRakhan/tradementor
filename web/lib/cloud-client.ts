import { firebaseAuth } from "./firebase";

export async function authenticatedRequest(path: string, init: RequestInit = {}) {
  const user = firebaseAuth.currentUser;
  if (!user) throw new Error("Log eerst in bij TradeMentor.");
  const token = await user.getIdToken();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (path.startsWith("/api/admin")) {
    const credential = window.localStorage.getItem("tradementor.admin.credential.v2");
    if (credential) headers.set("X-TradeMentor-Admin-Device", credential);
  }
  const response = await fetch(path, { ...init, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "De cloudopdracht is niet gelukt.");
  return payload;
}
