"use client";

import { useEffect, useState, type FormEvent } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import type { ExchangeSnapshots } from "@/lib/use-exchange-data";

type Connection = "hyperliquid" | "aster";

export function ConnectionManager({ snapshots, onChanged }: { snapshots: ExchangeSnapshots; onChanged: () => void }) {
  const [active, setActive] = useState<Connection>("hyperliquid");
  const connected = (id: Connection) => id === "hyperliquid"
    ? Boolean(snapshots[id].data) && !snapshots[id].error
    : Boolean(snapshots[id].data?.configured) && !snapshots[id].error;
  return <section className="connection-manager">
    <div className="connection-heading"><span className="kicker">PERSOONLIJKE KOPPELINGEN</span><strong>Exchanges</strong><small>Sleutels worden rechtstreeks gecontroleerd en alleen versleuteld in jouw Google Secret Manager opgeslagen.</small></div>
    <div className="connection-tabs">{(["hyperliquid","aster"] as const).map((id) => <button type="button" key={id} className={active === id ? "active" : ""} onClick={() => setActive(id)}><i className={connected(id) ? "connected" : ""} />{id === "hyperliquid" ? "Hyperliquid" : "Aster"}</button>)}</div>
    {active === "hyperliquid" ? <HyperliquidConnection onChanged={onChanged} /> : <AsterConnection snapshot={snapshots.aster.data} onChanged={onChanged} />}
  </section>;
}

function HyperliquidConnection({ onChanged }: { onChanged: () => void }) {
  const [wallet, setWallet] = useState("");
  const [agent, setAgent] = useState("");
  const [key, setKey] = useState("");
  return <ConnectionForm submitLabel="Hyperliquid veilig koppelen" onSubmit={async () => {
    await authenticatedRequest("/api/connections/hyperliquid/wallet", { method: "PUT", body: JSON.stringify({ address: wallet.trim() }) });
    await authenticatedRequest("/api/connections/hyperliquid/agent", { method: "POST", body: JSON.stringify({ agent_address: agent.trim(), private_key: key.trim() }) });
    setKey(""); onChanged();
  }}>
    <label>Hoofdwallet-adres<input required value={wallet} onChange={(event) => setWallet(event.target.value)} placeholder="0x…" autoComplete="off" /></label>
    <label>Goedgekeurde agentwallet<input required value={agent} onChange={(event) => setAgent(event.target.value)} placeholder="0x…" autoComplete="off" /></label>
    <label>Private key agentwallet<input required type="password" value={key} onChange={(event) => setKey(event.target.value)} placeholder="Wordt niet in de browser bewaard" autoComplete="new-password" /></label>
  </ConnectionForm>;
}

function AsterConnection({ snapshot, onChanged }: { snapshot: Record<string, unknown> | null; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(false);
  const [apiWallet, setApiWallet] = useState("");
  const [providerMissing, setProviderMissing] = useState(false);
  const [authorizationUrl, setAuthorizationUrl] = useState("https://www.asterdex.com/en/api-wallet");
  const configured = snapshot?.configured === true;
  const authorizationPending = snapshot?.authorizationPending === true;
  const savedApiWallet = typeof snapshot?.apiWalletAddress === "string" ? snapshot.apiWalletAddress : "";

  useEffect(() => {
    if (savedApiWallet) setApiWallet(savedApiWallet);
  }, [savedApiWallet]);

  async function connect() {
    setBusy(true); setMessage(""); setError(false); setProviderMissing(false);
    try {
      const ethereum = (window as unknown as { ethereum?: { request: (input: { method: string; params?: unknown[] }) => Promise<unknown> } }).ethereum;
      if (!ethereum) {
        setProviderMissing(true);
        throw new Error("Deze browser kan MetaMask niet openen. Open TradeMentor via de knop hieronder in MetaMask, of gebruik op de laptop de MetaMask-browserextensie.");
      }
      const accounts = await ethereum.request({ method: "eth_requestAccounts" }) as string[];
      const address = accounts[0];
      if (!address) throw new Error("MetaMask gaf geen walletadres terug.");
      const challenge = await authenticatedRequest("/api/connections/aster/challenge") as { message: string };
      const signature = await ethereum.request({ method: "personal_sign", params: [challenge.message, address] }) as string;
      const result = await authenticatedRequest("/api/connections/aster/wallet", {
        method: "POST", body: JSON.stringify({ address, message: challenge.message, signature }),
      }) as { apiWalletAddress: string; authorizationUrl: string };
      setApiWallet(result.apiWalletAddress); setAuthorizationUrl(result.authorizationUrl);
      setMessage("MetaMask is gecontroleerd. Keur nu het API-walletadres bij Aster goed en klik daarna op Controleren.");
      onChanged();
    } catch (reason) {
      setError(true); setMessage(reason instanceof Error ? reason.message : "Aster koppelen is niet gelukt.");
    } finally { setBusy(false); }
  }

  async function verify() {
    setBusy(true); setMessage(""); setError(false);
    try {
      await authenticatedRequest("/api/connections/aster/verify", { method: "POST", body: "{}" });
      setMessage("Aster API-wallet is goedgekeurd en veilig verbonden."); onChanged();
    } catch (reason) {
      setError(true); setMessage(reason instanceof Error ? reason.message : "Aster-goedkeuring is nog niet zichtbaar.");
    } finally { setBusy(false); }
  }

  return <div className="connection-form aster-connect-flow">
    <p className="connection-note">Koppel je Aster-hoofdwallet met MetaMask. TradeMentor maakt daarna een persoonlijke API-wallet; de geheime sleutel blijft uitsluitend versleuteld in jouw Google Secret Manager.</p>
    <ol className="connection-steps">
      <li className={apiWallet || configured ? "done" : "active"}><strong>1. Hoofdwallet tekenen</strong><span>MetaMask controleert dat deze Aster-wallet van jou is. Er wordt geen order geplaatst en geen geld verplaatst.</span></li>
      <li className={configured ? "done" : apiWallet ? "active" : ""}><strong>2. API-wallet goedkeuren</strong><span>Open Aster, kies rechtsboven <b>Connect Wallet</b> en daarna <b>MetaMask</b>. Klik niet op de GitHub-documentatielink.</span></li>
      <li className={configured ? "done" : authorizationPending ? "active" : ""}><strong>3. Verbinding controleren</strong><span>TradeMentor leest de Aster-accountstatus en markeert de koppeling groen.</span></li>
    </ol>
    {!configured && !apiWallet && <button type="button" disabled={busy} onClick={connect}>{busy ? "Wallet controleren…" : "Stap 1 · Koppel Aster met MetaMask"}</button>}
    {apiWallet && !configured && <>
      <label>Persoonlijke API-wallet<input readOnly value={apiWallet} onFocus={(event) => event.currentTarget.select()} /></label>
      <button type="button" className="secondary-button" onClick={() => navigator.clipboard.writeText(apiWallet)}>Adres kopiëren</button>
      <a className="connection-link" href={authorizationUrl} target="_blank" rel="noreferrer">Stap 2 · Open officiële Aster API Wallet</a>
      <p className="connection-note"><b>Op Aster:</b> Connect Wallet → MetaMask → Authorize new API wallet. Vul het bovenstaande persoonlijke API-walletadres in en keur de wallet goed.</p>
      <button type="button" disabled={busy} onClick={verify}>{busy ? "Aster controleren…" : "Stap 3 · Ik heb het goedgekeurd"}</button>
    </>}
    {configured && <p className="success">Aster is gecontroleerd en veilig verbonden.</p>}
    {message && <p className={error ? "error" : "success"}>{message}</p>}
    {providerMissing && <>
      <button type="button" className="secondary-button" onClick={async () => {
        await navigator.clipboard.writeText(window.location.href);
        setError(false); setMessage("TradeMentor-adres gekopieerd. Open nu MetaMask → Explore en plak het adres in de browserbalk.");
      }}>Kopieer TradeMentor-adres</button>
      <p className="connection-note"><b>Op je telefoon:</b> open de MetaMask-app → tik onderaan op <b>Explore</b> → open de browser → plak het gekopieerde TradeMentor-adres. Log daar opnieuw in en ga naar Wallet → ASTER.</p>
    </>}
  </div>;
}

function ConnectionForm({ children, submitLabel, onSubmit }: { children: React.ReactNode; submitLabel: string; onSubmit: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setMessage(""); setError(false);
    try { await onSubmit(); setMessage("Koppeling gecontroleerd en persoonlijk opgeslagen."); }
    catch (reason) { setError(true); setMessage(reason instanceof Error ? reason.message : "Koppelen is niet gelukt."); }
    finally { setBusy(false); }
  }
  return <form className="connection-form" onSubmit={submit}>{children}<button type="submit" disabled={busy}>{busy ? "Veilig controleren…" : submitLabel}</button>{message && <p className={error ? "error" : "success"}>{message}</p>}</form>;
}
