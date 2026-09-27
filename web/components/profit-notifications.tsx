
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuthSession } from "@/components/auth-provider";
import { authenticatedRequest } from "@/lib/cloud-client";

const OPEN_EVENT = "amar:open-profit-notifications";
const LAST_SEEN_KEY = "amar.profitNotifications.lastSeenAt.v1";

type NotificationSettings = {
  enabled: boolean;
  tradeProfitEnabled: boolean;
  mode: "EVERY_WIN" | "SUMMARY";
  intervalMinutes: 15 | 30 | 60;
  minimumProfitUsd: number;
  portfolioTpEnabled: boolean;
  refreshBalancesAtDispatch: boolean;
  activeSubscriptions?: number;
  deliveryState?: string;
};

type ProfitEvent = {
  eventId: string;
  symbol: string;
  side: string;
  realizedNetPnlUsd: number;
  occurredAtMs: number;
  capturedPortfolioValue: number;
  capturedAvailable: number;
};

const DEFAULT_SETTINGS: NotificationSettings = {
  enabled: false,
  tradeProfitEnabled: true,
  mode: "SUMMARY",
  intervalMinutes: 30,
  minimumProfitUsd: 0.5,
  portfolioTpEnabled: true,
  refreshBalancesAtDispatch: true,
};

function formatMoney(value: number, signed = false) {
  const numeric = Number.isFinite(value) ? value : 0;
  const prefix = signed && numeric >= 0 ? "+" : "";
  return prefix + new Intl.NumberFormat("nl-NL", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(numeric).replace("US$", "$");
}

function urlBase64ToUint8Array(value: string) {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map((character) => character.charCodeAt(0)));
}

function platformLabel() {
  const ua = navigator.userAgent;
  if (/iPad|iPhone|iPod/i.test(ua)) return "iOS";
  if (/Samsung/i.test(ua)) return "Samsung Android";
  if (/Android/i.test(ua)) return "Android";
  return "Web";
}

function isIos() {
  return /iPad|iPhone|iPod/i.test(navigator.userAgent);
}

function isStandalone() {
  return window.matchMedia("(display-mode: standalone)").matches ||
    Boolean((navigator as Navigator & { standalone?: boolean }).standalone);
}

async function ensureDeviceSubscription() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    throw new Error("Pushmeldingen worden door deze browser niet ondersteund.");
  }
  if (isIos() && !isStandalone()) {
    throw new Error("Op iPhone werkt Web Push nadat Amar Crypto Bot via 'Zet op beginscherm' als webapp is geopend.");
  }
  let permission = Notification.permission;
  if (permission === "default") permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error("Meldingen zijn niet toegestaan. Geef Amar Crypto Bot toestemming in de instellingen van je telefoon.");
  }

  const registration = await navigator.serviceWorker.ready;
  let subscription = await registration.pushManager.getSubscription();
  if (!subscription) {
    const keyPayload = await authenticatedRequest("/api/notifications/public-key");
    const publicKey = String(keyPayload.publicKey || "");
    if (!publicKey) throw new Error("De pushsleutel is tijdelijk niet beschikbaar.");
    subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    });
  }

  const serialized = subscription.toJSON();
  if (!serialized.endpoint || !serialized.keys?.p256dh || !serialized.keys?.auth) {
    throw new Error("De telefoon leverde geen volledige pushsubscription terug.");
  }
  await authenticatedRequest("/api/notifications/subscriptions", {
    method: "POST",
    body: JSON.stringify({
      endpoint: serialized.endpoint,
      p256dh: serialized.keys.p256dh,
      auth: serialized.keys.auth,
      expirationTime: serialized.expirationTime ?? null,
      platform: platformLabel(),
      userAgent: navigator.userAgent,
    }),
  });
  return subscription;
}

export function ProfitNotificationControl() {
  return (
    <button
      type="button"
      className="profit-notification-header-button"
      aria-label="Pushmeldingen beheren"
      title="Pushmeldingen beheren"
      onClick={() => window.dispatchEvent(new CustomEvent(OPEN_EVENT))}
    >
      <span aria-hidden="true" className="profit-bell-dot" />
      <span aria-hidden="true" className="profit-bell-glyph">🔔</span>
    </button>
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (checked: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={"profit-push-toggle " + (checked ? "on" : "")}
      onClick={() => onChange(!checked)}
    >
      <span />
    </button>
  );
}

function ModeCard({ active, icon, children, onClick }: {
  active: boolean; icon: string; children: React.ReactNode; onClick: () => void;
}) {
  return (
    <button type="button" className={"profit-mode-card " + (active ? "active" : "")} onClick={onClick}>
      <span aria-hidden="true">{icon}</span>
      <strong>{children}</strong>
    </button>
  );
}

function DeliveryStatus({ settings, permission }: {
  settings: NotificationSettings;
  permission: NotificationPermission | "unsupported";
}) {
  if (!settings.enabled) return <div className="profit-push-delivery-status off">Pushmeldingen staan uit.</div>;
  if (permission === "denied") {
    return <div className="profit-push-delivery-status error">AAN gevraagd · telefoon blokkeert meldingen. Geef toestemming in de systeeminstellingen.</div>;
  }
  if (permission === "unsupported") {
    return <div className="profit-push-delivery-status error">AAN gevraagd · deze browser ondersteunt geen pushmeldingen.</div>;
  }
  if ((settings.activeSubscriptions ?? 0) < 1) {
    return <div className="profit-push-delivery-status warn">AAN gevraagd · dit apparaat is nog niet geabonneerd op pushmeldingen.</div>;
  }
  return <div className="profit-push-delivery-status ready">● Push actief op dit apparaat</div>;
}

export function ProfitNotificationPanel() {
  const { user, ready, cloudReady } = useAuthSession();
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<NotificationSettings>(DEFAULT_SETTINGS);
  const [saved, setSaved] = useState<NotificationSettings>(DEFAULT_SETTINGS);
  const [loading, setLoading] = useState(false);
  const [working, setWorking] = useState("");
  const [message, setMessage] = useState("");
  const [permission, setPermission] = useState<NotificationPermission | "unsupported">("default");
  const scrollY = useRef(0);

  const refreshPermission = useCallback(() => {
    setPermission("Notification" in window ? Notification.permission : "unsupported");
  }, []);

  const load = useCallback(async () => {
    if (!user || !cloudReady) return;
    setLoading(true);
    setMessage("");
    try {
      const payload = await authenticatedRequest("/api/notifications/settings");
      const interval = Number(payload.intervalMinutes);
      const next: NotificationSettings = {
        ...DEFAULT_SETTINGS,
        ...payload,
        mode: payload.mode === "EVERY_WIN" ? "EVERY_WIN" : "SUMMARY",
        intervalMinutes: ([15, 30, 60].includes(interval) ? interval : 30) as 15 | 30 | 60,
        minimumProfitUsd: Number(payload.minimumProfitUsd ?? 0.5),
      };
      setSettings(next);
      setSaved(next);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Pushinstellingen konden niet worden geladen.");
    } finally {
      refreshPermission();
      setLoading(false);
    }
  }, [cloudReady, refreshPermission, user]);

  useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_EVENT, onOpen);
  }, []);

  useEffect(() => {
    if (!open) return;
    scrollY.current = window.scrollY;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    refreshPermission();
    void load();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      window.requestAnimationFrame(() => window.scrollTo({ top: scrollY.current, behavior: "auto" }));
    };
  }, [load, open, refreshPermission]);

  const dirty = useMemo(() => {
    const comparable = (value: NotificationSettings) => ({
      enabled: value.enabled,
      tradeProfitEnabled: value.tradeProfitEnabled,
      mode: value.mode,
      intervalMinutes: value.intervalMinutes,
      minimumProfitUsd: value.minimumProfitUsd,
      portfolioTpEnabled: value.portfolioTpEnabled,
      refreshBalancesAtDispatch: value.refreshBalancesAtDispatch,
    });
    return JSON.stringify(comparable(settings)) !== JSON.stringify(comparable(saved));
  }, [saved, settings]);

  async function enablePushOnDevice() {
    setWorking("permission");
    setMessage("");
    try {
      await ensureDeviceSubscription();
      refreshPermission();
      const payload = await authenticatedRequest("/api/notifications/settings");
      setSettings((current) => ({
        ...current,
        activeSubscriptions: Number(payload.activeSubscriptions || 1),
        deliveryState: String(payload.deliveryState || "SUBSCRIBED"),
      }));
    } catch (error) {
      refreshPermission();
      setMessage(error instanceof Error ? error.message : "Pushmeldingen konden niet worden geactiveerd.");
      throw error;
    } finally {
      setWorking("");
    }
  }

  async function setEnabled(next: boolean) {
    setSettings((current) => ({ ...current, enabled: next }));
    if (next) {
      try {
        await enablePushOnDevice();
      } catch {
        // Keep intended state visible; DeliveryStatus exposes the OS/browser truth.
      }
    }
  }

  async function save() {
    if (!user || !cloudReady) return;
    setWorking("save");
    setMessage("");
    try {
      if (settings.enabled && (settings.activeSubscriptions ?? 0) < 1) await enablePushOnDevice();
      const payload = await authenticatedRequest("/api/notifications/settings", {
        method: "PUT",
        body: JSON.stringify({
          enabled: settings.enabled,
          tradeProfitEnabled: settings.tradeProfitEnabled,
          mode: settings.mode,
          intervalMinutes: settings.intervalMinutes,
          minimumProfitUsd: settings.minimumProfitUsd,
          portfolioTpEnabled: settings.portfolioTpEnabled,
          refreshBalancesAtDispatch: settings.refreshBalancesAtDispatch,
        }),
      });
      const next = { ...settings, ...payload } as NotificationSettings;
      setSettings(next);
      setSaved(next);
      setMessage("Opgeslagen. Nieuwe meldingen gebruiken deze instellingen.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Opslaan is niet gelukt.");
    } finally {
      setWorking("");
      refreshPermission();
    }
  }

  async function sendTest() {
    if (!user || !cloudReady) return;
    setWorking("test");
    setMessage("");
    try {
      await ensureDeviceSubscription();
      await authenticatedRequest("/api/notifications/test", { method: "POST", body: "{}" });
      setMessage("Testmelding verzonden. Er is geen trade of portfolioactie uitgevoerd.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Testmelding versturen is niet gelukt.");
    } finally {
      setWorking("");
      refreshPermission();
    }
  }

  const previewInterval = settings.mode === "SUMMARY" ? settings.intervalMinutes : null;
  if (!open) return null;

  return (
    <div className="profit-notification-overlay" role="dialog" aria-modal="true" aria-labelledby="profit-notification-title">
      <div className="profit-notification-shell">
        <header className="profit-notification-titlebar">
          <button type="button" className="profit-notification-back" onClick={() => setOpen(false)} aria-label="Terug"><span aria-hidden="true">←</span></button>
          <span className="profit-notification-title-icon" aria-hidden="true">🔔</span>
          <div>
            <h1 id="profit-notification-title">Pushmeldingen beheren</h1>
            <p>Stel in wanneer en welke meldingen je ontvangt</p>
          </div>
          <button type="button" className="profit-notification-close" onClick={() => setOpen(false)}><span aria-hidden="true">×</span><small>Sluiten</small></button>
        </header>

        {!ready || loading ? (
          <div className="profit-notification-loading">Pushinstellingen laden…</div>
        ) : !user || !cloudReady ? (
          <div className="profit-notification-loading">Log eerst in om pushmeldingen te beheren.</div>
        ) : (
          <>
            <section className="profit-setting-row primary">
              <span className="profit-setting-icon" aria-hidden="true">🔔</span>
              <div><strong>Pushmeldingen</strong><small>Ontvang meldingen over je trades en portfolio</small></div>
              <Toggle checked={settings.enabled} onChange={setEnabled} label="Pushmeldingen" />
              <b className={settings.enabled && (settings.activeSubscriptions ?? 0) > 0 ? "on" : ""}>{settings.enabled ? "AAN" : "UIT"}</b>
            </section>

            <DeliveryStatus settings={settings} permission={permission} />

            <section className="profit-setting-block mode">
              <div className="profit-setting-heading">
                <span className="profit-setting-icon" aria-hidden="true">◷</span>
                <div><strong>Meldingsmodus</strong><small>Kies hoe vaak je meldingen wilt ontvangen</small></div>
              </div>
              <div className="profit-mode-grid">
                <ModeCard active={settings.mode === "EVERY_WIN"} icon="⚡" onClick={() => setSettings((current) => ({ ...current, mode: "EVERY_WIN" }))}>Iedere<br />winsttrade</ModeCard>
                <ModeCard active={settings.mode === "SUMMARY" && settings.intervalMinutes === 15} icon="▥" onClick={() => setSettings((current) => ({ ...current, mode: "SUMMARY", intervalMinutes: 15 }))}>Samenvatting<br />15 min</ModeCard>
                <ModeCard active={settings.mode === "SUMMARY" && settings.intervalMinutes === 30} icon="◷" onClick={() => setSettings((current) => ({ ...current, mode: "SUMMARY", intervalMinutes: 30 }))}>Samenvatting<br />30 min</ModeCard>
                <ModeCard active={settings.mode === "SUMMARY" && settings.intervalMinutes === 60} icon="◴" onClick={() => setSettings((current) => ({ ...current, mode: "SUMMARY", intervalMinutes: 60 }))}>Samenvatting<br />60 min</ModeCard>
              </div>
            </section>

            <section className="profit-setting-row">
              <span className="profit-setting-icon gold" aria-hidden="true">🏆</span>
              <div><strong>Alleen winsttrades (&gt; 0)</strong><small>Ontvang alleen meldingen van winstgevende trades</small></div>
              <Toggle checked={settings.tradeProfitEnabled} onChange={(value) => setSettings((current) => ({ ...current, tradeProfitEnabled: value }))} label="Winsttrades" />
              <b className={settings.tradeProfitEnabled ? "on" : ""}>{settings.tradeProfitEnabled ? "AAN" : "UIT"}</b>
            </section>

            <section className="profit-setting-row">
              <span className="profit-setting-icon" aria-hidden="true">◎</span>
              <div><strong>Portfolio Take Profit behaald</strong><small>Ontvang direct een pushmelding wanneer je portfolio TP-doel is bereikt</small></div>
              <Toggle checked={settings.portfolioTpEnabled} onChange={(value) => setSettings((current) => ({ ...current, portfolioTpEnabled: value }))} label="Portfolio Take Profit behaald" />
              <b className={settings.portfolioTpEnabled ? "on" : ""}>{settings.portfolioTpEnabled ? "AAN" : "UIT"}</b>
            </section>

            <section className="profit-setting-row">
              <span className="profit-setting-icon" aria-hidden="true">↻</span>
              <div><strong>Portfolio &amp; Available realtime verversen bij verzenden</strong><small>Haal de nieuwste waarden op vlak vóór de melding wordt verstuurd</small></div>
              <Toggle checked={settings.refreshBalancesAtDispatch} onChange={(value) => setSettings((current) => ({ ...current, refreshBalancesAtDispatch: value }))} label="Realtime portfolio en available" />
              <b className={settings.refreshBalancesAtDispatch ? "on" : ""}>{settings.refreshBalancesAtDispatch ? "AAN" : "UIT"}</b>
            </section>

            <section className="profit-setting-row minimum">
              <span className="profit-setting-icon" aria-hidden="true">▥</span>
              <div><strong>Minimum winst</strong><small>Ontvang alleen meldingen vanaf deze netto winst per trade</small></div>
              <select aria-label="Minimum winst" value={String(settings.minimumProfitUsd)} onChange={(event) => setSettings((current) => ({ ...current, minimumProfitUsd: Number(event.target.value) }))}>
                {[0, 0.1, 0.25, 0.5, 1, 2, 5, 10].map((value) => <option key={value} value={value}>{formatMoney(value)}</option>)}
              </select>
            </section>

            <aside className="profit-notification-info">
              <span aria-hidden="true">ⓘ</span>
              <p>Bij een samenvatting ontvang je de winsttrade met de hoogste winst uit de gekozen tijdsperiode. Portfolio en Available worden live opgehaald op het moment van verzenden. Zonder winsttrade blijft het stil.</p>
            </aside>

            <section className="profit-preview">
              <div className="profit-setting-heading">
                <span className="profit-setting-icon" aria-hidden="true">◉</span>
                <div><strong>Voorbeeld melding</strong><small>Zo ziet een pushmelding er inhoudelijk uit</small></div>
              </div>
              <div className="profit-preview-notification">
                <span className="profit-preview-logo" aria-hidden="true">A</span>
                <div>
                  <small>Amar Crypto Bot 2026 <i>nu</i></small>
                  <strong>{previewInterval ? "🏆 Mooiste winst · afgelopen " + previewInterval + " min" : "🏆 Trade gesloten met winst!"}</strong>
                  <p>BTCUSDT&nbsp; LONG <b>+$12,85</b></p>
                  {previewInterval && <p>47 winsttrades · <b>+$63,42 totaal</b></p>}
                  <p>Portfolio nu: $1.284,74</p>
                  <p>Available nu: $854,21</p>
                </div>
              </div>
            </section>

            {message && <div className="profit-notification-message" role="status">{message}</div>}

            <footer className="profit-notification-actions">
              <button type="button" className="save" onClick={save} disabled={working !== ""}>
                <span aria-hidden="true">▣</span> {working === "save" ? "Opslaan…" : dirty ? "Opslaan" : "Opgeslagen"}
              </button>
              <button type="button" className="test" onClick={sendTest} disabled={working !== ""}>
                <span aria-hidden="true">➤</span> {working === "test" ? "Versturen…" : "Testmelding versturen"}
              </button>
            </footer>
          </>
        )}
      </div>
    </div>
  );
}

export function ProfitCelebration() {
  const { user, cloudReady } = useAuthSession();
  const [event, setEvent] = useState<ProfitEvent | null>(null);
  const [visible, setVisible] = useState(false);
  const lastSeen = useRef(0);

  useEffect(() => {
    try {
      lastSeen.current = Number(window.localStorage.getItem(LAST_SEEN_KEY) || 0);
    } catch {
      lastSeen.current = 0;
    }
  }, []);

  const poll = useCallback(async () => {
    if (!user || !cloudReady || document.visibilityState !== "visible" || visible) return;
    try {
      const path = "/api/notifications/recent?after_ms=" + Math.max(0, lastSeen.current);
      const payload = await authenticatedRequest(path);
      const rows = Array.isArray(payload.events) ? payload.events as ProfitEvent[] : [];
      if (!rows.length) return;
      const newestAt = Math.max(...rows.map((row) => Number(row.occurredAtMs || 0)));
      lastSeen.current = newestAt;
      try { window.localStorage.setItem(LAST_SEEN_KEY, String(newestAt)); } catch {}
      setEvent(rows[rows.length - 1] || null);
      setVisible(true);
    } catch {
      // A celebration is informative only; it may never disturb trading.
    }
  }, [cloudReady, user, visible]);

  useEffect(() => {
    if (!user || !cloudReady) return;
    void poll();
    const timer = window.setInterval(() => void poll(), 12_000);
    const onVisibility = () => { if (document.visibilityState === "visible") void poll(); };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [cloudReady, poll, user]);

  if (!visible || !event) return null;

  return (
    <div className="profit-celebration-backdrop" role="dialog" aria-modal="true" aria-label="Trade gesloten met winst">
      <article className="profit-celebration-card">
        <button type="button" className="profit-celebration-x" onClick={() => setVisible(false)} aria-label="Sluiten">×</button>
        <header><span className="profit-celebration-brand">A</span><strong>Amar Crypto Bot 2026</strong><small>TRADE GESLOTEN</small></header>
        <div className="profit-celebration-trophy" aria-hidden="true"><i>✦</i><b>🏆</b><i>✦</i></div>
        <h2>Profit!</h2>
        <h3>Weer een mooie winst!</h3>
        <section className="profit-celebration-trade">
          <div><span className="profit-coin">◎</span><p><strong>{event.symbol}</strong><b>{event.side}</b><small>Trade succesvol gesloten</small></p></div>
          <p><strong>{formatMoney(event.realizedNetPnlUsd, true)}</strong><small>Netto winst</small></p>
        </section>
        <section className="profit-celebration-stats">
          <div><span>▣</span><small>Portfolio waarde</small><strong>{formatMoney(event.capturedPortfolioValue)}</strong></div>
          <div><span>▤</span><small>Available</small><strong>{formatMoney(event.capturedAvailable)}</strong></div>
          <div><span>↗</span><small>Gesloten winst</small><strong>{formatMoney(event.realizedNetPnlUsd, true)}</strong></div>
        </section>
        <aside><span aria-hidden="true">↗</span><p><strong>Goed gedaan!</strong><small>Een gerealiseerde winst is veilig bevestigd door de backend.</small></p></aside>
        <button type="button" className="profit-celebration-cta" onClick={() => setVisible(false)}>Top! Door naar de volgende! 🚀</button>
      </article>
    </div>
  );
}
