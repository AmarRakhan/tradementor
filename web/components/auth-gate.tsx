"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { sendEmailVerification } from "firebase/auth";
import { useAuthSession } from "./auth-provider";

export function AuthGate({ children }: { children: ReactNode }) {
  const auth = useAuthSession();
  if (!auth.ready) return <AuthSplash label="Beveiligde sessie controleren" />;
  if (!auth.user) return <SignInScreen />;
  if (!auth.user.emailVerified) return <VerifyEmailScreen />;
  return <>{children}</>;
}

function VerifyEmailScreen() {
  const { user, signOut } = useAuthSession();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Open de verificatiemail en klik op de link. Daarna kun je veilig verder.");

  async function refresh() {
    if (!user) return;
    setBusy(true);
    await user.reload();
    if (user.emailVerified) window.location.reload();
    else setMessage("Nog niet bevestigd. Controleer ook je spammap en probeer daarna opnieuw.");
    setBusy(false);
  }

  async function resend() {
    if (!user) return;
    setBusy(true);
    try {
      await sendEmailVerification(user);
      setMessage("Een nieuwe verificatiemail is verzonden.");
    } catch {
      setMessage("De mail kon nu niet opnieuw worden verzonden. Wacht even en probeer opnieuw.");
    } finally { setBusy(false); }
  }

  return <main className="auth-shell"><section className="auth-card">
    <div className="auth-brand"><img src="/tradementor-logo.png?v=redgreen-1" alt="TradeMentor rood-groen logo" /><div><span>TRADEMENTOR WEB</span><strong>E-mailcontrole</strong></div></div>
    <span className="kicker">LAATSTE VEILIGHEIDSSTAP</span><h1>Bevestig je e-mailadres</h1>
    <p className="auth-copy">We hebben een link gestuurd naar <strong>{user?.email}</strong>. Zo kan niemand anders jouw persoonlijke handelsomgeving activeren.</p>
    <div className="auth-message">{message}</div>
    <button className="auth-submit" type="button" disabled={busy} onClick={refresh}>{busy ? "Controleren…" : "Ik heb mijn e-mail bevestigd"}</button>
    <button className="forgot-button" type="button" disabled={busy} onClick={resend}>Verificatiemail opnieuw sturen</button>
    <button className="forgot-button" type="button" disabled={busy} onClick={() => signOut()}>Met een ander account inloggen</button>
  </section></main>;
}

function AuthSplash({ label }: { label: string }) {
  return <main className="auth-shell"><section className="auth-card loading-card"><img src="/tradementor-logo.png?v=redgreen-1" alt="TradeMentor rood-groen logo" /><span className="auth-spinner" /><p>{label}</p></section></main>;
}

function SignInScreen() {
  const { signIn, register, resetPassword, error } = useAuthSession();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setNotice("");
    try {
      if (mode === "register") await register(name, email, password);
      else await signIn(email, password);
    } catch {
      // The provider exposes the translated error below the form.
    } finally {
      setBusy(false);
    }
  }

  async function forgotPassword() {
    if (!email.trim()) return setNotice("Vul eerst je e-mailadres in.");
    setBusy(true);
    try {
      await resetPassword(email);
      setNotice("De herstelmail is verzonden.");
    } catch {
      setNotice("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="auth-brand"><img src="/tradementor-logo.png?v=redgreen-1" alt="TradeMentor rood-groen logo" /><div><span>TRADEMENTOR WEB</span><strong>Portfolio Intelligence</strong></div></div>
        <span className="kicker">PERSOONLIJKE OMGEVING</span>
        <h1>{mode === "login" ? "Welkom terug" : "Maak je account"}</h1>
        <p className="auth-copy">Je account scheidt wallet, instellingen, strategieën en abonnement strikt van iedere andere gebruiker.</p>
        <div className="auth-tabs">
          <button type="button" className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>Inloggen</button>
          <button type="button" className={mode === "register" ? "active" : ""} onClick={() => setMode("register")}>Registreren</button>
        </div>
        <form onSubmit={submit}>
          {mode === "register" && <label>Naam<input required autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Jouw naam" /></label>}
          <label>E-mailadres<input required type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="naam@voorbeeld.nl" /></label>
          <label>Wachtwoord<input required minLength={6} type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Minimaal 6 tekens" /></label>
          {(error || notice) && <div className={`auth-message ${error ? "error" : ""}`}>{error || notice}</div>}
          <button className="auth-submit" type="submit" disabled={busy}>{busy ? "Even controleren…" : mode === "login" ? "Veilig inloggen" : "Account aanmaken"}</button>
          {mode === "login" && <button className="forgot-button" type="button" disabled={busy} onClick={forgotPassword}>Wachtwoord vergeten?</button>}
        </form>
        <div className="auth-safety"><i /><span>Live handel staat na iedere nieuwe aanmelding standaard uit.</span></div>
        <a className="legal-link" href="/legal">Privacy, voorwaarden en handelsrisico</a>
      </section>
    </main>
  );
}
