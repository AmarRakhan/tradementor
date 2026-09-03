"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signOut as firebaseSignOut,
  updateProfile,
  type User,
} from "firebase/auth";
import { firebaseAuth, firebaseAuthReady } from "@/lib/firebase";
import { clearAsterSnapshot, withBoundedRetry } from "@/lib/aster-snapshot-cache.mjs";

type AuthContextValue = {
  user: User | null;
  ready: boolean;
  cloudReady: boolean;
  error: string;
  signIn: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  resetPassword: (email: string) => Promise<void>;
  signOut: () => Promise<void>;
  idToken: () => Promise<string>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function authMessage(error: unknown): string {
  const code = typeof error === "object" && error && "code" in error ? String(error.code) : "";
  if (code.includes("invalid-credential")) return "E-mailadres of wachtwoord klopt niet.";
  if (code.includes("email-already-in-use")) return "Dit e-mailadres heeft al een TradeMentor-account.";
  if (code.includes("weak-password")) return "Kies een wachtwoord van minimaal zes tekens.";
  if (code.includes("invalid-email")) return "Vul een geldig e-mailadres in.";
  if (code.includes("too-many-requests")) return "Te veel pogingen. Probeer het later opnieuw.";
  return error instanceof Error ? error.message : "Aanmelden is niet gelukt.";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [cloudReady, setCloudReady] = useState(false);
  const [error, setError] = useState("");
  const bootstrapInFlight = useRef<{ uid: string; promise: Promise<void> } | null>(null);

  const previewUser = useMemo(() => {
    if (typeof window === "undefined" || window.location.hostname !== "terminal.local" || !new URLSearchParams(window.location.search).has("staging-demo")) return null;
    return { uid: "preview-user", email: "preview@tradementor.invalid", displayName: "Staging Preview", emailVerified: true, getIdToken: async () => "tradementor-local-preview" } as unknown as User;
  }, []);

  const bootstrap = useCallback(async (current: User) => {
    if (bootstrapInFlight.current?.uid === current.uid) return bootstrapInFlight.current.promise;
    setCloudReady(false);
    const started = performance.now();
    const run = (async () => {
    let token: string;
    try {
      token = await current.getIdToken(false);
    } catch (reason) {
      const code = typeof reason === "object" && reason && "code" in reason ? String(reason.code) : "";
      if (code.includes("user-token-expired") || code.includes("invalid-user-token") || code.includes("user-disabled")) {
        await firebaseSignOut(firebaseAuth);
        throw new Error("Je oude sessie is verwijderd. Log opnieuw in om verder te gaan.");
      }
      throw reason;
    }
    const send = async (value: string) => {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 12_000);
      try { return await fetch("/api/session/bootstrap", { method: "POST", headers: { Authorization: `Bearer ${value}` }, signal: controller.signal, cache: "no-store" }); }
      finally { window.clearTimeout(timeout); }
    };
    const verifiedSend = (value: string) => withBoundedRetry(async () => {
      const candidate = await send(value);
      if (candidate.status >= 500) throw new Error("De cloudsessie reageert tijdelijk niet.");
      return candidate;
    }, { attempts: 2, delays: [500] });
    let response = await verifiedSend(token);
    if (response.status === 401) {
      token = await current.getIdToken(true);
      response = await verifiedSend(token);
      if (response.status === 401) {
        throw new Error("Je login is geldig, maar de persoonlijke cloudsessie kon nog niet worden bevestigd. Probeer het zo opnieuw.");
      }
    }
    if (!response.ok) throw new Error("De persoonlijke cloudsessie kon niet worden gecontroleerd.");
    setCloudReady(true);
    console.info("[TradeMentor bootstrap timing]", { totalMs: Math.round(performance.now() - started) });
    })().finally(() => {
      if (bootstrapInFlight.current?.uid === current.uid) bootstrapInFlight.current = null;
    });
    bootstrapInFlight.current = { uid: current.uid, promise: run };
    return run;
  }, []);

  useEffect(() => {
    if (previewUser) { setUser(previewUser); setReady(true); bootstrap(previewUser).catch((reason) => setError(authMessage(reason))); return; }
    let unsubscribe = () => {};
    let active = true;
    let authStateReceived = false;
    const authStateTimeout = window.setTimeout(() => {
      if (!active || authStateReceived) return;
      const current = firebaseAuth.currentUser;
      console.warn("[TradeMentor auth] initial auth state timed out; continuing with the current Firebase session");
      setUser(current);
      setReady(true);
      setError(current ? "De sessiecontrole duurde te lang. De laatst bekende sessie wordt hersteld." : "De sessiecontrole duurde te lang. Log opnieuw in om verder te gaan.");
      if (current) bootstrap(current).catch((reason) => setError(authMessage(reason)));
    }, 8_000);
    firebaseAuthReady
      .then(() => {
        if (!active) return;
        unsubscribe = onAuthStateChanged(firebaseAuth, (current) => {
          authStateReceived = true;
          window.clearTimeout(authStateTimeout);
          setUser(current);
          setReady(true);
          setError("");
          if (current) bootstrap(current).catch((reason) => setError(authMessage(reason)));
          else setCloudReady(false);
        });
      })
      .catch((reason) => {
        if (!active) return;
        setReady(true);
        setError(authMessage(reason));
      });
    return () => {
      active = false;
      window.clearTimeout(authStateTimeout);
      unsubscribe();
    };
  }, [bootstrap, previewUser]);

  useEffect(() => {
    const resume = () => {
      const current = firebaseAuth.currentUser;
      if (current && !cloudReady) bootstrap(current).catch((reason) => setError(authMessage(reason)));
    };
    window.addEventListener("online", resume);
    return () => window.removeEventListener("online", resume);
  }, [bootstrap, cloudReady]);

  const signIn = useCallback(async (email: string, password: string) => {
    setError("");
    try {
      await firebaseAuthReady;
      await signInWithEmailAndPassword(firebaseAuth, email.trim(), password);
    } catch (reason) {
      const message = authMessage(reason);
      setError(message);
      throw new Error(message);
    }
  }, []);

  const register = useCallback(async (name: string, email: string, password: string) => {
    setError("");
    try {
      await firebaseAuthReady;
      const result = await createUserWithEmailAndPassword(firebaseAuth, email.trim(), password);
      await updateProfile(result.user, { displayName: name.trim() });
      await sendEmailVerification(result.user);
    } catch (reason) {
      const message = authMessage(reason);
      setError(message);
      throw new Error(message);
    }
  }, []);

  const resetPassword = useCallback(async (email: string) => {
    setError("");
    try {
      await sendPasswordResetEmail(firebaseAuth, email.trim());
    } catch (reason) {
      const message = authMessage(reason);
      setError(message);
      throw new Error(message);
    }
  }, []);

  const signOut = useCallback(async () => {
    if (typeof window !== "undefined") {
      const uid = firebaseAuth.currentUser?.uid;
      if (uid) {
        clearAsterSnapshot(window.localStorage, uid);
        window.localStorage.removeItem(`tradementor.portfolioEquity.v2.${encodeURIComponent(uid)}`);
      }
      window.localStorage.removeItem("tradementor.admin.credential.v2");
      window.localStorage.setItem("tradementor.activeDestination", "wallet");
    }
    await firebaseSignOut(firebaseAuth);
  }, []);
  const idToken = useCallback(async () => {
    const current = firebaseAuth.currentUser || previewUser;
    if (!current) throw new Error("Log eerst in bij TradeMentor.");
    return current.getIdToken();
  }, [previewUser]);

  const value = useMemo(() => ({ user, ready, cloudReady, error, signIn, register, resetPassword, signOut, idToken }), [user, ready, cloudReady, error, signIn, register, resetPassword, signOut, idToken]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuthSession(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider ontbreekt.");
  return value;
}
