"use client";

import { useEffect, useRef, useState } from "react";

type SessionPayload = {
  intent: { destinationLabel: string; requestedAmount: string; asset: string; network: string; address: string };
  typedData: Record<string, unknown>;
  walletAddress: string;
  expiresAt: string;
};

declare global { interface Window { ethereum?: { request(args: { method: string; params?: unknown[] }): Promise<unknown> } } }

function short(value: string) { return value?.length > 12 ? `${value.slice(0, 6)}…${value.slice(-5)}` : value; }

export default function SignWithdrawalPage() {
  const [session, setSession] = useState<SessionPayload | null>(null);
  const [state, setState] = useState<"loading"|"ready"|"signing"|"done"|"error">("loading");
  const [error, setError] = useState("");
  const tokenRef = useRef("");
  const started = useRef(false);

  useEffect(() => {
    const token = new URL(window.location.href).searchParams.get("token") || "";
    tokenRef.current = token;
    if (!token) { setError("Ondertekensessie ontbreekt."); setState("error"); return; }
    fetch(`/api/transfers/sign/${encodeURIComponent(token)}`, { cache: "no-store" })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "Ondertekensessie kon niet worden geladen.");
        setSession(payload as SessionPayload); setState("ready");
      })
      .catch((reason) => { setError(reason instanceof Error ? reason.message : "Ondertekensessie kon niet worden geladen."); setState("error"); });
  }, []);

  const sign = async () => {
    if (!session || state === "signing" || state === "done") return;
    setState("signing"); setError("");
    try {
      if (!window.ethereum) throw new Error("Open deze pagina in MetaMask.");
      const accounts = await window.ethereum.request({ method: "eth_requestAccounts" }) as string[];
      const wallet = String(accounts?.[0] || "").toLowerCase();
      if (!wallet) throw new Error("MetaMask heeft geen wallet vrijgegeven.");
      if (wallet !== session.walletAddress.toLowerCase()) throw new Error("Kies in MetaMask dezelfde wallet die aan Aster is gekoppeld.");
      const signature = await window.ethereum.request({ method: "eth_signTypedData_v4", params: [wallet, JSON.stringify(session.typedData)] }) as string;
      const response = await fetch(`/api/transfers/sign/${encodeURIComponent(tokenRef.current)}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ signature, walletAddress: wallet }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Aster heeft de handtekening niet verwerkt.");
      setState("done");
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason || "MetaMask heeft de aanvraag niet bevestigd.");
      setError(message.includes("4001") ? "Je hebt de MetaMask-aanvraag geannuleerd." : message);
      setState("error");
    }
  };

  useEffect(() => {
    if (state !== "ready" || started.current) return;
    started.current = true;
    const timer = window.setTimeout(() => void sign(), 250);
    return () => window.clearTimeout(timer);
  }, [state, session]);

  return <main style={{minHeight:"100dvh",background:"#050708",color:"#f5f5f3",display:"grid",placeItems:"center",padding:20,fontFamily:"system-ui"}}>
    <section style={{width:"min(100%,430px)",background:"#111518",border:"1px solid rgba(240,189,104,.25)",borderRadius:22,padding:22,textAlign:"center"}}>
      <div style={{fontSize:52}}>🦊</div><h1 style={{margin:"8px 0"}}>MetaMask bevestiging</h1>
      {session && <div style={{margin:"18px 0",padding:15,borderRadius:14,background:"#191e22",textAlign:"left"}}>
        <p><b>{session.intent.requestedAmount} {session.intent.asset}</b> naar {session.intent.destinationLabel}</p>
        <p style={{color:"#9ca2a6"}}>{session.intent.network} · {short(session.intent.address)}</p>
      </div>}
      {state === "loading" && <p>Veilige opname laden…</p>}
      {state === "signing" && <p>Controleer de melding in MetaMask en druk op <b>Confirm</b>.</p>}
      {state === "done" && <><div style={{fontSize:44,color:"#39dc78"}}>✓</div><p>Handtekening ontvangen en opname verzonden.</p><small style={{color:"#999"}}>Ga nu terug naar Crypto Bot 2026. De status wordt daar automatisch bijgewerkt.</small></>}
      {error && <p style={{color:"#ff9da2"}}>{error}</p>}
      {(state === "ready" || state === "error") && session && <button type="button" onClick={() => { started.current = true; void sign(); }} style={{width:"100%",marginTop:15,minHeight:48,border:0,borderRadius:13,background:"linear-gradient(100deg,#efb258,#ffe0a6)",color:"#1d1409",fontWeight:800}}>MetaMask bevestigen</button>}
      <small style={{display:"block",marginTop:14,color:"#777"}}>Je seed phrase en private key verlaten MetaMask nooit.</small>
    </section>
  </main>;
}
