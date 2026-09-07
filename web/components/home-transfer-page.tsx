"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { useAuthSession } from "@/components/auth-provider";
import { useExchangeData } from "@/lib/use-exchange-data";

type Destination = {
  id: string; contactId: string; label: string; destinationType: string; asset: string;
  network: string; networkLabel?: string; chainId: number; address: string; validationStatus: string;
};
type Contact = { id: string; name: string; avatar?: string; description?: string; destinations: Destination[] };
type Intent = {
  id: string; destinationId: string; destinationLabel: string; asset: string; network: string;
  chainId: number; address: string; requestedAmount: string; fee: string; expectedNetAmount: string;
  status: string; walletAddress?: string; withdrawId?: string; txHash?: string; errorMessage?: string;
  createdAt?: string; completedAt?: string;
};
type Quote = { asset: string; network: string; chainId: number; withdrawableAmount: string; fee: string; destination: { id: string; label: string; address: string } };
type Flow = "home" | "contacts" | "destinations" | "amount" | "review" | "signing" | "status" | "done";

declare global { interface Window { ethereum?: { request(args: { method: string; params?: unknown[] }): Promise<unknown> } } }

const ACTIVE_INTENT_KEY = "tradementor.transfer.activeIntent.v1";
const GOLD = "#f1bd65";

function money(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "$ —";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}
function compactAddress(value: string) { return value?.length > 12 ? `${value.slice(0, 6)}…${value.slice(-5)}` : value; }
function number(value: unknown) { const n = Number(value); return Number.isFinite(n) ? n : 0; }
function idempotency() { return `withdraw-${Date.now()}-${crypto.randomUUID()}`; }

function navigateExisting(destination: string) {
  const button = document.querySelector<HTMLButtonElement>(`.bottom-nav .nav-button[data-destination="${destination}"], .rail-nav .nav-button[data-destination="${destination}"]`);
  button?.click();
}

export function HomeTransferPage() {
  const { user, cloudReady } = useAuthSession();
  const { snapshots } = useExchangeData(cloudReady, user?.uid || "");
  const [flow, setFlow] = useState<Flow>("home");
  const [mode, setMode] = useState<"contacts" | "recent">("contacts");
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [recent, setRecent] = useState<Intent[]>([]);
  const [contact, setContact] = useState<Contact | null>(null);
  const [destination, setDestination] = useState<Destination | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [amount, setAmount] = useState("");
  const [intent, setIntent] = useState<Intent | null>(null);
  const [typedData, setTypedData] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [addContact, setAddContact] = useState(false);
  const [addDestination, setAddDestination] = useState(false);
  const pollRef = useRef<number | null>(null);

  const aster = snapshots.aster.data || {};
  const portfolio = number(aster.equity ?? aster.accountValue ?? aster.balance);
  const pnl = number(aster.unrealizedPnl);
  const changePct = portfolio > 0 ? (pnl / Math.max(0.01, portfolio - pnl)) * 100 : 0;

  const loadContacts = async () => {
    const payload = await authenticatedRequest("/api/transfers/contacts");
    setContacts(Array.isArray(payload.contacts) ? payload.contacts : []);
  };
  const loadRecent = async () => {
    const payload = await authenticatedRequest("/api/transfers/recent");
    setRecent(Array.isArray(payload.transfers) ? payload.transfers : []);
  };

  useEffect(() => {
    if (!cloudReady || !user?.uid) return;
    void loadContacts().catch(() => undefined);
    const saved = window.localStorage.getItem(ACTIVE_INTENT_KEY);
    if (!saved) return;
    void authenticatedRequest(`/api/transfers/intents/${encodeURIComponent(saved)}`)
      .then((payload) => {
        const current = payload.intent as Intent;
        if (!current) return;
        setIntent(current); setTypedData((payload.typedData as Record<string, unknown> | undefined) || null);
        if (current.status === "COMPLETED") setFlow("done");
        else if (["SUBMITTED", "CONFIRMING", "SIGNED"].includes(current.status)) setFlow("status");
        else if (current.status === "AWAITING_SIGNATURE") setFlow("review");
        else if (["FAILED", "CANCELLED"].includes(current.status)) window.localStorage.removeItem(ACTIVE_INTENT_KEY);
      }).catch(() => undefined);
  }, [cloudReady, user?.uid]);

  const refreshIntent = async () => {
    if (!intent?.id) return;
    const payload = await authenticatedRequest(`/api/transfers/intents/${encodeURIComponent(intent.id)}`);
    const current = payload.intent as Intent;
    setIntent(current);
    if (current.status === "COMPLETED") {
      setFlow("done"); window.localStorage.removeItem(ACTIVE_INTENT_KEY); void loadRecent();
    } else if (current.status === "FAILED") {
      setError(current.errorMessage || "De opname is mislukt."); window.localStorage.removeItem(ACTIVE_INTENT_KEY);
    }
  };

  useEffect(() => {
    if (flow !== "status" || !intent?.id) return;
    void refreshIntent();
    pollRef.current = window.setInterval(() => void refreshIntent().catch(() => undefined), 3000);
    const visible = () => { if (document.visibilityState === "visible") void refreshIntent().catch(() => undefined); };
    document.addEventListener("visibilitychange", visible);
    window.addEventListener("pageshow", visible);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      document.removeEventListener("visibilitychange", visible); window.removeEventListener("pageshow", visible);
    };
  }, [flow, intent?.id]);

  const chooseContact = (item: Contact) => { setContact(item); setDestination(null); setQuote(null); setFlow("destinations"); };
  const chooseDestination = async (item: Destination) => {
    setBusy(true); setError(""); setDestination(item);
    try {
      const payload = await authenticatedRequest(`/api/transfers/quote?destinationId=${encodeURIComponent(item.id)}`);
      setQuote(payload as Quote); setAmount(""); setFlow("amount");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Bestemming kon niet worden gecontroleerd."); }
    finally { setBusy(false); }
  };
  const setFraction = (fraction: number) => {
    const maximum = number(quote?.withdrawableAmount);
    setAmount((maximum * fraction).toFixed(6).replace(/0+$/, "").replace(/\.$/, ""));
  };
  const net = Math.max(0, number(amount) - number(quote?.fee));

  const prepareIntent = async () => {
    if (!destination || !amount) return;
    setBusy(true); setError("");
    try {
      const payload = await authenticatedRequest("/api/transfers/intents", { method: "POST", body: JSON.stringify({ destinationId: destination.id, amount, idempotencyKey: idempotency() }) });
      const next = payload.intent as Intent;
      setIntent(next); setTypedData(payload.typedData || null);
      window.localStorage.setItem(ACTIVE_INTENT_KEY, next.id);
      setFlow("review");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Opname kon niet worden voorbereid."); }
    finally { setBusy(false); }
  };

  const signAndSubmit = async () => {
    if (!intent?.id || !typedData) { setError("De ondertekengegevens ontbreken. Start de opname opnieuw."); return; }
    setBusy(true); setError(""); setFlow("signing");
    try {
      if (!window.ethereum) {
        const session = await authenticatedRequest(`/api/transfers/intents/${encodeURIComponent(intent.id)}/signing-session`, { method: "POST", body: "{}" }) as { token: string };
        if (!session.token) throw new Error("MetaMask-ondertekensessie kon niet worden gestart.");
        const signUrl = `${window.location.origin}/sign-withdrawal?token=${encodeURIComponent(session.token)}`;
        const dappPath = signUrl.replace(/^https?:\/\//, "");
        window.location.href = `https://metamask.app.link/dapp/${dappPath}`;
        return;
      }
      const accounts = await window.ethereum.request({ method: "eth_requestAccounts" }) as string[];
      const wallet = String(accounts?.[0] || "").toLowerCase();
      if (!wallet) throw new Error("MetaMask heeft geen wallet vrijgegeven.");
      const signature = await window.ethereum.request({ method: "eth_signTypedData_v4", params: [wallet, JSON.stringify(typedData)] }) as string;
      const payload = await authenticatedRequest(`/api/transfers/intents/${encodeURIComponent(intent.id)}/signature`, { method: "POST", body: JSON.stringify({ signature, walletAddress: wallet }) });
      setIntent(payload.intent as Intent); setFlow("status");
    } catch (reason: unknown) {
      const message = reason instanceof Error ? reason.message : String(reason || "MetaMask heeft de aanvraag niet bevestigd.");
      if (message.includes("4001") || message.toLowerCase().includes("reject")) {
        await authenticatedRequest(`/api/transfers/intents/${encodeURIComponent(intent.id)}/cancel`, { method: "POST", body: "{}" }).catch(() => undefined);
        window.localStorage.removeItem(ACTIVE_INTENT_KEY); setFlow("review"); setError("Je hebt de MetaMask-aanvraag geannuleerd. Er is niets verstuurd.");
      } else { setFlow("review"); setError(message); }
    } finally { setBusy(false); }
  };

  const resetTransfer = () => { setFlow("contacts"); setContact(null); setDestination(null); setQuote(null); setAmount(""); setIntent(null); setTypedData(null); setError(""); };

  if (flow === "home") return <HomeDashboard portfolio={portfolio} changePct={changePct} onTransfer={() => { setFlow("contacts"); void loadContacts(); }} />;

  return <section className="tm-transfer-shell">
    <header className="tm-transfer-header"><button type="button" className="tm-back" onClick={() => flow === "contacts" ? setFlow("home") : setFlow(flow === "destinations" ? "contacts" : flow === "amount" ? "destinations" : flow === "review" ? "amount" : "contacts")}>‹</button><strong>{flow === "done" ? "Voltooid" : flow === "status" ? "Opname bezig" : flow === "review" || flow === "signing" ? "Bevestigen" : flow === "amount" ? "Bedrag en details" : flow === "destinations" ? "Bestemming kiezen" : "Overboeken"}</strong><span /></header>
    {error && <div className="tm-transfer-error" role="alert">{error}</div>}
    {flow === "contacts" && <ContactsScreen contacts={contacts} recent={recent} mode={mode} setMode={(next) => { setMode(next); if (next === "recent") void loadRecent(); }} onChoose={chooseContact} onAdd={() => setAddContact(true)} onRecent={(item) => {
      if (item.status === "COMPLETED") { setIntent(item); setFlow("done"); return; }
      void authenticatedRequest(`/api/transfers/intents/${encodeURIComponent(item.id)}`).then((payload) => {
        const current = payload.intent as Intent; setIntent(current); setTypedData((payload.typedData as Record<string, unknown> | undefined) || null);
        setFlow(current.status === "AWAITING_SIGNATURE" ? "review" : current.status === "COMPLETED" ? "done" : "status");
      }).catch((reason) => setError(reason instanceof Error ? reason.message : "Overboeking kon niet worden geopend."));
    }} />}
    {flow === "destinations" && contact && <DestinationsScreen contact={contact} busy={busy} onChoose={chooseDestination} onAdd={() => setAddDestination(true)} />}
    {flow === "amount" && destination && quote && <AmountScreen destination={destination} quote={quote} amount={amount} setAmount={setAmount} net={net} busy={busy} onFraction={setFraction} onContinue={prepareIntent} />}
    {flow === "review" && intent && <ReviewScreen intent={intent} busy={busy} onConfirm={signAndSubmit} />}
    {flow === "signing" && <SigningScreen />}
    {flow === "status" && intent && <StatusScreen intent={intent} />}
    {flow === "done" && intent && <DoneScreen intent={intent} onOverview={() => { setFlow("contacts"); setMode("recent"); void loadRecent(); }} onAgain={resetTransfer} />}
    {addContact && <AddContactModal onClose={() => setAddContact(false)} onSaved={() => { setAddContact(false); void loadContacts(); }} />}
    {addDestination && contact && <AddDestinationModal contact={contact} onClose={() => setAddDestination(false)} onSaved={() => { setAddDestination(false); void loadContacts().then(() => setFlow("contacts")); }} />}
  </section>;
}

function HomeDashboard({ portfolio, changePct, onTransfer }: { portfolio: number; changePct: number; onTransfer: () => void }) {
  const cards = [
    ["▦", "Dashboard", "aster"], ["↗", "Trading", "aster"], ["▤", "Posities", "positions"], ["◎", "Scanner", "markets"],
    ["▥", "Statistieken", "journey"], ["➤", "Overboeken", "transfer"], ["⚙", "Instellingen", "wallet"], ["•••", "Meer", ""],
  ];
  return <section className="tm-home" aria-label="Home">
    <div className="tm-home-brand"><img src="/tradementor-logo.png?v=redgreen-1" alt="" /><strong>Aster</strong><button type="button" aria-label="Help">?</button></div>
    <div className="tm-home-portfolio"><span>Portfolio</span><div className="tm-home-value-row"><div><strong>{money(portfolio || null)}</strong><small className={changePct >= 0 ? "positive" : "negative"}>{changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}% (24h)</small></div><svg viewBox="0 0 180 70" aria-hidden="true"><polyline points="0,57 14,51 26,53 39,42 54,45 67,34 80,39 94,27 108,31 120,18 134,25 148,12 160,17 180,4" fill="none" stroke="currentColor" strokeWidth="3" /></svg></div></div>
    <div className="tm-home-grid">{cards.map(([icon, label, destination]) => <button key={label} type="button" className={label === "Overboeken" ? "featured" : ""} onClick={() => destination === "transfer" ? onTransfer() : destination ? navigateExisting(destination) : undefined}><i>{icon}</i><span>{label}</span></button>)}</div>
    <button className="tm-home-transfer-callout" type="button" onClick={onTransfer}><span className="tm-home-logo-dot">✦</span><span>Snel en veilig geld overboeken<br />naar je eigen wallet of exchange.</span><b>›</b></button>
    <div className="tm-home-globe" aria-hidden="true"><div className="tm-globe-line one" /><div className="tm-globe-line two" /><div className="tm-globe-line three" /></div>
  </section>;
}

function ContactsScreen({ contacts, recent, mode, setMode, onChoose, onAdd, onRecent }: { contacts: Contact[]; recent: Intent[]; mode: "contacts"|"recent"; setMode: (m:"contacts"|"recent")=>void; onChoose:(c:Contact)=>void; onAdd:()=>void; onRecent:(i:Intent)=>void }) {
  return <div className="tm-transfer-body"><div className="tm-segment"><button className={mode === "contacts" ? "active" : ""} onClick={() => setMode("contacts")}>Contacten</button><button className={mode === "recent" ? "active" : ""} onClick={() => setMode("recent")}>Recente</button></div>
    {mode === "contacts" ? <><div className="tm-contact-grid">{contacts.map((item) => <button key={item.id} onClick={() => onChoose(item)}><span className="tm-avatar">{item.avatar ? <img src={item.avatar} alt="" /> : item.name.slice(0,2).toUpperCase()}</span><strong>{item.name}</strong><small>{item.destinations?.length || 0} adressen</small></button>)}<button className="add" onClick={onAdd}><span className="tm-avatar">＋</span><strong>Toevoegen</strong></button></div><button className="tm-secondary-wide" onClick={onAdd}>＋ Nieuw contact toevoegen</button>{contacts.length === 0 && <p className="tm-empty">Voeg eerst jezelf of een andere ontvanger toe.</p>}</> : <div className="tm-list">{recent.map((item) => <button key={item.id} onClick={() => onRecent(item)}><span><strong>{item.destinationLabel}</strong><small>{item.network} · {item.createdAt ? new Date(item.createdAt).toLocaleString("nl-NL") : ""}</small></span><span><strong>{item.requestedAmount} {item.asset}</strong><small className={`status ${item.status.toLowerCase()}`}>{item.status}</small></span></button>)}{recent.length === 0 && <p className="tm-empty">Nog geen overboekingen.</p>}</div>}
  </div>;
}

function DestinationsScreen({ contact, busy, onChoose, onAdd }: { contact: Contact; busy:boolean; onChoose:(d:Destination)=>void; onAdd:()=>void }) {
  return <div className="tm-transfer-body"><div className="tm-selected-contact"><span className="tm-avatar">{contact.avatar ? <img src={contact.avatar} alt="" /> : contact.name.slice(0,2).toUpperCase()}</span><div><strong>{contact.name}</strong><small>{contact.destinations?.length || 0} adressen</small></div></div><div className="tm-destination-list">{(contact.destinations || []).map((item) => <button disabled={busy} key={item.id} onClick={() => onChoose(item)}><span className="tm-coin">{item.asset.slice(0,1)}</span><span><strong>{item.label}</strong><small>{item.networkLabel || item.network}</small></span><b>⋮</b></button>)}</div><button className="tm-secondary-wide" onClick={onAdd}>＋ Nieuw adres toevoegen</button></div>;
}

function AmountScreen({ destination, quote, amount, setAmount, net, busy, onFraction, onContinue }: { destination:Destination; quote:Quote; amount:string; setAmount:(v:string)=>void; net:number; busy:boolean; onFraction:(n:number)=>void; onContinue:()=>void }) {
  const valid = number(amount) > number(quote.fee) && number(amount) <= number(quote.withdrawableAmount);
  return <div className="tm-transfer-body"><div className="tm-destination-card"><span className="tm-coin">{destination.asset[0]}</span><span><strong>{destination.label}</strong><small>{quote.network}</small></span></div><div className="tm-verified">✓ <span><strong>Adres geverifieerd</strong><small>Technisch geldig voor {destination.asset} op {quote.network}.</small></span></div><label className="tm-amount-label">Bedrag</label><div className="tm-amount-input"><input inputMode="decimal" value={amount} onChange={(e)=>setAmount(e.target.value.replace(",", ".").replace(/[^0-9.]/g,""))} placeholder="0" /><strong>{destination.asset}</strong></div><div className="tm-balance"><span>Opneembaar: {quote.withdrawableAmount} {destination.asset}</span><button onClick={()=>onFraction(1)}>Max</button></div><div className="tm-fractions"><button onClick={()=>onFraction(.25)}>25%</button><button onClick={()=>onFraction(.5)}>50%</button><button onClick={()=>onFraction(.75)}>75%</button><button onClick={()=>onFraction(1)}>Max</button></div><div className="tm-summary"><p><span>Je ontvangt (geschat)</span><strong>{net.toFixed(6).replace(/0+$/,"").replace(/\.$/,"")} {destination.asset}</strong></p><p><span>Network fee (Aster)</span><strong>{quote.fee} {destination.asset}</strong></p><p><span>Netwerk</span><strong>{quote.network}</strong></p></div><button className="tm-primary" disabled={!valid || busy} onClick={onContinue}>{busy ? "Controleren…" : "Overboeken"}</button></div>;
}

function ReviewScreen({ intent, busy, onConfirm }: { intent:Intent; busy:boolean; onConfirm:()=>void }) {
  return <div className="tm-transfer-body"><div className="tm-destination-card"><span className="tm-coin">{intent.asset[0]}</span><span><strong>{intent.destinationLabel}</strong><small>{intent.network}</small></span></div><div className="tm-summary review"><p><span>Bedrag</span><strong>{intent.requestedAmount} {intent.asset}</strong></p><p><span>Netwerkfee</span><strong>{intent.fee} {intent.asset}</strong></p><p><span>Je ontvangt (geschat)</span><strong>{intent.expectedNetAmount} {intent.asset}</strong></p><p><span>Bestemming</span><strong>{compactAddress(intent.address)}</strong></p></div><div className="tm-checks"><p>✓ Adres gecontroleerd</p><p>✓ Juiste asset ({intent.asset})</p><p>✓ Juiste netwerk ({intent.network})</p><p>✓ Opgeslagen bestemming</p></div><button className="tm-primary" disabled={busy} onClick={onConfirm}>{busy ? "MetaMask openen…" : "Bevestigen en MetaMask openen"}</button><small className="tm-footnote">MetaMask vraagt jou persoonlijk om de withdrawal-handtekening. Je private key of seed wordt nooit opgeslagen.</small></div>;
}
function SigningScreen() { return <div className="tm-transfer-body tm-centered"><div className="tm-metamask">🦊</div><h2>MetaMask</h2><p>Controleer de signature request en druk daar op <strong>Confirm</strong>.</p><div className="tm-spinner" /><small>Na bevestigen gaat deze flow automatisch verder.</small></div>; }
function StatusScreen({ intent }: { intent:Intent }) {
  const submitted = ["SUBMITTED","CONFIRMING","COMPLETED"].includes(intent.status); const confirming=["CONFIRMING","COMPLETED"].includes(intent.status); const done=intent.status === "COMPLETED";
  return <div className="tm-transfer-body"><div className="tm-timeline"><Step done title="Handtekening ontvangen" /><Step done={submitted} active={!submitted} title="Opname verzonden" /><Step done={confirming} active={submitted&&!confirming} title="Bevestigingen op blockchain" /><Step done={done} active={confirming&&!done} title="Aankomst bij bestemming" /><Step done={done} title="Voltooid" /></div><div className="tm-info-note">Je kunt deze pagina sluiten. Bij terugkomst halen we automatisch de actuele status van dezelfde opname op.</div></div>;
}
function Step({ done, active=false, title }: {done:boolean;active?:boolean;title:string}) { return <div className={`tm-step ${done?"done":active?"active":""}`}><i>{done?"✓":active?"•":""}</i><span>{title}</span></div>; }
function DoneScreen({ intent, onOverview, onAgain }: {intent:Intent;onOverview:()=>void;onAgain:()=>void}) { return <div className="tm-transfer-body tm-done"><div className="tm-success">✓</div><h2>Opname gelukt!</h2><p>Je hebt {intent.requestedAmount} {intent.asset} overgeboekt naar {intent.destinationLabel}.</p><div className="tm-summary"><p><span>Tx hash</span><strong>{compactAddress(intent.txHash || "—")}</strong></p><p><span>Bedrag</span><strong>{intent.requestedAmount} {intent.asset}</strong></p><p><span>Netwerkfee</span><strong>{intent.fee} {intent.asset}</strong></p><p><span>Bestemming</span><strong>{intent.destinationLabel}</strong></p><p><span>Netwerk</span><strong>{intent.network}</strong></p></div><button className="tm-secondary-wide" onClick={onOverview}>Naar overzicht</button><button className="tm-primary" onClick={onAgain}>Nog een overboeking</button></div>; }

function AddContactModal({ onClose, onSaved }: {onClose:()=>void;onSaved:()=>void}) {
  const [name,setName]=useState(""); const [avatar,setAvatar]=useState(""); const [busy,setBusy]=useState(false); const [error,setError]=useState("");
  const pick=(file?:File)=>{if(!file)return;if(file.size>250_000){setError("Kies een foto kleiner dan 250 KB.");return;}const reader=new FileReader();reader.onload=()=>setAvatar(String(reader.result||""));reader.readAsDataURL(file)};
  const save=async()=>{setBusy(true);setError("");try{await authenticatedRequest("/api/transfers/contacts",{method:"POST",body:JSON.stringify({name,avatar,description:""})});onSaved();}catch(e){setError(e instanceof Error?e.message:"Opslaan mislukt.");}finally{setBusy(false)}};
  return <div className="tm-modal-layer" onMouseDown={onClose}><div className="tm-modal" onMouseDown={e=>e.stopPropagation()}><h3>Nieuw contact</h3>{error&&<div className="tm-transfer-error">{error}</div>}<label>Naam<input value={name} onChange={e=>setName(e.target.value)} placeholder="Bijv. Ikzelf" /></label><label className="tm-photo-picker">Profielfoto<input type="file" accept="image/*" onChange={e=>pick(e.target.files?.[0])} />{avatar&&<img src={avatar} alt="Preview" />}</label><div className="tm-modal-actions"><button onClick={onClose}>Annuleren</button><button disabled={!name.trim()||busy} onClick={save}>Opslaan</button></div></div></div>;
}
function AddDestinationModal({ contact, onClose, onSaved }: {contact:Contact;onClose:()=>void;onSaved:()=>void}) {
  const [label,setLabel]=useState("");const [asset,setAsset]=useState("USDC");const [network,setNetwork]=useState("arbitrum");const [address,setAddress]=useState("");const [busy,setBusy]=useState(false);const [error,setError]=useState("");
  const save=async()=>{setBusy(true);setError("");try{await authenticatedRequest("/api/transfers/destinations",{method:"POST",body:JSON.stringify({contactId:contact.id,label,destinationType:"exchange",asset,network,address:address.trim()})});onSaved();}catch(e){setError(e instanceof Error?e.message:"Adres kon niet worden opgeslagen.");}finally{setBusy(false)}};
  return <div className="tm-modal-layer" onMouseDown={onClose}><div className="tm-modal" onMouseDown={e=>e.stopPropagation()}><h3>Nieuw adres</h3>{error&&<div className="tm-transfer-error">{error}</div>}<label>Naam<input value={label} onChange={e=>setLabel(e.target.value)} placeholder="Bijv. Kraken USDC" /></label><div className="tm-form-row"><label>Asset<select value={asset} onChange={e=>setAsset(e.target.value)}><option>USDC</option><option>USDT</option></select></label><label>Netwerk<select value={network} onChange={e=>setNetwork(e.target.value)}><option value="arbitrum">Arbitrum One</option><option value="ethereum">Ethereum</option><option value="bsc">BNB Smart Chain</option></select></label></div><label>Ontvangstadres<input value={address} onChange={e=>setAddress(e.target.value)} placeholder="0x…" autoCapitalize="none" autoCorrect="off" /></label><small className="tm-footnote">Een adres wordt pas opgeslagen nadat asset, netwerk en adresformaat server-side zijn gecontroleerd.</small><div className="tm-modal-actions"><button onClick={onClose}>Annuleren</button><button disabled={!label.trim()||!address.trim()||busy} onClick={save}>{busy?"Controleren…":"Controleren en opslaan"}</button></div></div></div>;
}
