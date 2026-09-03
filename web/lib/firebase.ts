import { getApp, getApps, initializeApp } from "firebase/app";
import { browserLocalPersistence, getAuth, setPersistence } from "firebase/auth";

// Firebase web configuration identifies this public client. It is not a
// credential and grants no database or trading access by itself. Firebase ID
// tokens and server-side authorization remain mandatory.
const firebaseConfig = {
  apiKey: "AIzaSyCQjFCFDMdx1dIGMvkMVMkByxXaUHBs_pY",
  authDomain: "tradementor-production.firebaseapp.com",
  projectId: "tradementor-production",
  storageBucket: "tradementor-production.firebasestorage.app",
  messagingSenderId: "604335232956",
  appId: "1:604335232956:web:d90b3a3e83d973e7fabdb9",
  measurementId: "G-CJSDEK6MSG",
};

export const firebaseApp = getApps().length ? getApp() : initializeApp(firebaseConfig);
export const firebaseAuth = getAuth(firebaseApp);
export const firebaseAuthReady = typeof window === "undefined"
  ? Promise.resolve(firebaseAuth)
  : new Promise<typeof firebaseAuth>((resolve) => {
      let settled = false;
      const finish = (source: "persistence" | "timeout") => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeout);
        if (source === "timeout") console.warn("[TradeMentor auth] persistence setup timed out; continuing with Firebase fallback");
        resolve(firebaseAuth);
      };
      const timeout = window.setTimeout(() => finish("timeout"), 4_000);
      setPersistence(firebaseAuth, browserLocalPersistence)
        .then(() => finish("persistence"))
        .catch((reason) => {
          console.warn("[TradeMentor auth] local persistence unavailable; continuing with Firebase fallback", { reason: String(reason) });
          finish("persistence");
        });
    });
