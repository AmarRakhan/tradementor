"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
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
import { firebaseAuth } from "@/lib/firebase";

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

  const bootstrap = useCallback(async (current: User) => {
    setCloudReady(false);
    const token = await current.getIdToken();
    const response = await fetch("/api/session/bootstrap", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) throw new Error("De persoonlijke cloudsessie kon niet worden gecontroleerd.");
    setCloudReady(true);
  }, []);

  useEffect(() => onAuthStateChanged(firebaseAuth, (current) => {
    setUser(current);
    setReady(true);
    setError("");
    if (current) bootstrap(current).catch((reason) => setError(authMessage(reason)));
    else setCloudReady(false);
  }), [bootstrap]);

  const signIn = useCallback(async (email: string, password: string) => {
    setError("");
    try {
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
      window.localStorage.removeItem("tradementor.admin.credential.v2");
      window.localStorage.setItem("tradementor.activeDestination", "wallet");
    }
    await firebaseSignOut(firebaseAuth);
  }, []);
  const idToken = useCallback(async () => {
    const current = firebaseAuth.currentUser;
    if (!current) throw new Error("Log eerst in bij TradeMentor.");
    return current.getIdToken();
  }, []);

  const value = useMemo(() => ({ user, ready, cloudReady, error, signIn, register, resetPassword, signOut, idToken }), [user, ready, cloudReady, error, signIn, register, resetPassword, signOut, idToken]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuthSession(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider ontbreekt.");
  return value;
}
