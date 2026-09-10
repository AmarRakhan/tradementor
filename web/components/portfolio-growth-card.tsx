"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type Growth = {
  setupRequired?: boolean;
  reliable?: boolean;
  closeEnabled?: boolean;
  baseline?: number;
  expectedEndValue?: number;
  difference?: number;
  percentage?: number;
  positionCount?: number;
  blockReason?: string;
  quoteId?: string;
};

type DailyGrowth = {
  reliable?: boolean;
  todayPercentage?: number;
  averageDailyPercentage?: number;
  measuredDays?: number;
  measurementStartDate?: string;
  blockReason?: string;
};

type CloseResult = {
  status?: string;
  closedPositions?: number;
  newBaseline?: number;
  botPaused?: boolean;
  duplicate?: boolean;
  message?: string;
};

type CloseSuccess = {
  closedPositions: number | null;
  newBaseline: number | null;
  message: string;
};

type ClosePhase = "idle" | "busy" | "success";

const money = (value: number, signed = false) => `${value < 0 ? "-" : signed ? "+" : ""}US$ ${Math.abs(value).toLocaleString("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const percent = (value: number) => `${value >= 0 ? "+" : ""}${value.toLocaleString("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
const finiteNumber = (value: unknown) => {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

export function PortfolioGrowthCard({ onChanged = () => {} }: { onChanged?: () => void }) {
  const [data, setData] = useState<Growth | null>(null);
  const [daily, setDaily] = useState<DailyGrowth | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [amount, setAmount] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [reset, setReset] = useState(false);
  const [resetReason, setResetReason] = useState("");
  const [closePhase, setClosePhase] = useState<ClosePhase>("idle");
  const [closeSuccess, setCloseSuccess] = useState<CloseSuccess | null>(null);
  const closeRequest = useRef<{ quoteId: string; key: string }>({ quoteId: "", key: "" });

  const load = useCallback(async () => {
    setError("");
    try {
      setData(await authenticatedRequest("/api/exchanges/aster/portfolio-growth") as Growth);
    } catch (cause) {
      setData({ reliable: false });
      setError(cause instanceof Error ? cause.message : "Berekening niet beschikbaar");
    }
  }, []);

  useEffect(() => {
    let active = true;
    authenticatedRequest("/api/exchanges/aster/portfolio-growth")
      .then((value) => { if (active) setData(value as Growth); })
      .catch((cause) => {
        if (!active) return;
        setData({ reliable: false });
        setError(cause instanceof Error ? cause.message : "Berekening niet beschikbaar");
      });
    authenticatedRequest("/api/exchanges/aster/portfolio-growth/daily")
      .then((value) => { if (active) setDaily(value as DailyGrowth); })
      .catch(() => { if (active) setDaily({ reliable: false }); });
    return () => { active = false; };
  }, []);

  async function saveBaseline(isReset = false) {
    const value = Number(amount.replace(",", "."));
    if (!Number.isFinite(value) || value <= 0) {
      setError("Vul een geldige positieve startwaarde in.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const path = isReset ? "/api/exchanges/aster/portfolio-growth/reset" : "/api/exchanges/aster/portfolio-growth";
      const body = isReset
        ? { amount: value, currency: "USD", confirm: true, reason: resetReason }
        : { amount: value, currency: "USD", confirm: true };
      setData(await authenticatedRequest(path, { method: "POST", body: JSON.stringify(body) }) as Growth);
      setConfirm(false);
      setReset(false);
      setAmount("");
      setResetReason("");
      onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Startwaarde opslaan is mislukt.");
    } finally {
      setBusy(false);
    }
  }

  async function closeAll() {
    if (!data?.quoteId || busy) return;
    const quoteId = data.quoteId;
    if (closeRequest.current.quoteId !== quoteId || !closeRequest.current.key) {
      closeRequest.current = { quoteId, key: crypto.randomUUID() };
    }
    setBusy(true);
    setClosePhase("busy");
    setCloseSuccess(null);
    setError("");
    try {
      const result = await authenticatedRequest("/api/exchanges/aster/automation/close-all", {
        method: "POST",
        body: JSON.stringify({
          confirm: true,
          quote_id: quoteId,
          idempotency_key: closeRequest.current.key,
        }),
      }) as CloseResult;
      if (String(result.status || "").toUpperCase() !== "COMPLETED") {
        throw new Error("Aster heeft Alles sluiten niet als voltooid bevestigd.");
      }
      const closedPositions = finiteNumber(result.closedPositions);
      const newBaseline = finiteNumber(result.newBaseline);
      setCloseSuccess({
        closedPositions,
        newBaseline,
        message: String(result.message || "Alle posities en open orders zijn door Aster bevestigd gesloten. Het account blijft bewust gepauzeerd."),
      });
      closeRequest.current = { quoteId: "", key: "" };
      setConfirm(false);
      setClosePhase("success");
      await load();
      onChanged();
    } catch (cause) {
      setClosePhase("idle");
      setError(cause instanceof Error ? cause.message : "Alles sluiten is fail-closed gestopt.");
    } finally {
      setBusy(false);
    }
  }

  const difference = Number(data?.difference ?? 0);
  const tone = !data?.reliable ? "unreliable" : difference > 0 ? "profit" : difference < 0 ? "loss" : "neutral";
  const dailyTone = (value: number) => value > 0 ? "#35c46a" : value < 0 ? "#ef5b5b" : "inherit";
  const today = Number(daily?.todayPercentage ?? 0);
  const average = Number(daily?.averageDailyPercentage ?? 0);
  const closeBusy = closePhase === "busy";
  const dailyStats = (
    <div className="portfolio-growth-daily" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "3px 12px", width: "100%", margin: "4px 0 2px", alignItems: "end" }}>
      <span style={{ display: "grid", gap: 1 }}><small>Vandaag</small><strong style={{ fontSize: "1rem", lineHeight: 1.1, color: daily?.reliable ? dailyTone(today) : "inherit" }}>{daily?.reliable ? percent(today) : "—"}</strong></span>
      <span style={{ display: "grid", gap: 1 }}><small>Gemiddeld per dag</small><strong style={{ fontSize: "1rem", lineHeight: 1.1, color: daily?.reliable ? dailyTone(average) : "inherit" }}>{daily?.reliable ? percent(average) : "—"}</strong></span>
      <small style={{ gridColumn: "1 / -1", opacity: .72, fontSize: ".72rem" }}>Gemeten over {daily?.reliable ? (daily.measuredDays ?? 1) : "—"} {daily?.measuredDays === 1 ? "dag" : "dagen"} · Sinds 23 augustus 2026</small>
    </div>
  );

  return <>
    <article className={`metric portfolio-growth ${tone}`} aria-live="polite">
      <span>PORTFOLIO GROEI</span>
      {data?.setupRequired ? (
        <div className="portfolio-growth-setup">
          <small>Stel eenmalig je startwaarde in</small>
          <input aria-label="Startwaarde in US-dollar" inputMode="decimal" placeholder="US$ 359,00" value={amount} onChange={(event) => setAmount(event.target.value)} />
          <button disabled={busy} onClick={() => setConfirm(true)}>STARTWAARDE OPSLAAN</button>
        </div>
      ) : <>
        <small>Netto winst bij alles sluiten</small>
        <strong className="portfolio-growth-money">{data?.reliable ? money(difference, true) : "—"}</strong>
        <b>{data?.reliable ? percent(Number(data?.percentage ?? 0)) : "Onbetrouwbaar"}</b>
        <button className="portfolio-close-all" disabled={busy || !data?.closeEnabled} onClick={() => setConfirm(true)}>{closeBusy ? "Bezig met sluiten..." : "ALLES SLUITEN"}</button>
        <small>Startwaarde {data?.baseline ? money(data.baseline) : "—"}</small>
        <button className="portfolio-baseline-reset" disabled={busy} onClick={() => setReset(true)}>Startwaarde resetten</button>
      </>}
      {dailyStats}
      {error && <em>{error}</em>}
      {!error && !data?.reliable && !data?.setupRequired && <em>{data?.blockReason || "Sluiten is veilig geblokkeerd"}</em>}
    </article>

    {confirm && <div className="portfolio-growth-modal" role="presentation" onMouseDown={() => { if (!busy) setConfirm(false); }}>
      <section role="dialog" aria-modal="true" aria-label={data?.setupRequired ? "Startwaarde bevestigen" : "Alles sluiten bevestigen"} onMouseDown={(event) => event.stopPropagation()}>
        {data?.setupRequired ? <>
          <h3>Startwaarde bevestigen</h3>
          <p>Deze persoonlijke startwaarde wordt server-side opgeslagen en kan daarna alleen via de resetprocedure worden gewijzigd.</p>
          <dl><dt>Startwaarde</dt><dd>{money(Number(amount.replace(",", ".")) || 0)}</dd><dt>Valuta</dt><dd>USD</dd></dl>
        </> : <>
          <h3>{closeBusy ? "Bezig met sluiten..." : "Alles sluiten bevestigen"}</h3>
          <dl>
            <dt>Actuele startwaarde</dt><dd>{money(Number(data?.baseline ?? 0))}</dd>
            <dt>Verwachte netto eindwaarde</dt><dd>{money(Number(data?.expectedEndValue ?? 0))}</dd>
            <dt>Verwacht verschil</dt><dd>{money(difference, true)}</dd>
            <dt>Verwacht percentage</dt><dd>{percent(Number(data?.percentage ?? 0))}</dd>
            <dt>Posities</dt><dd>{data?.positionCount ?? 0}</dd>
          </dl>
          <p>{closeBusy ? "Aster wordt positie voor positie gecontroleerd. Dit venster blijft open totdat de exchange bevestigt dat alle exposure en open orders weg zijn." : "De server haalt alles opnieuw op en gaat alleen door als de nettowinst nog betrouwbaar positief is. De bot blijft daarna gepauzeerd."}</p>
        </>}
        {error && <em>{error}</em>}
        <footer>
          <button disabled={busy} onClick={() => setConfirm(false)}>Annuleren</button>
          <button disabled={busy} onClick={() => data?.setupRequired ? saveBaseline(false) : closeAll()}>{data?.setupRequired ? "Bevestig startwaarde" : closeBusy ? "Bezig met sluiten..." : "Bevestig alles sluiten"}</button>
        </footer>
      </section>
    </div>}

    {closePhase === "success" && closeSuccess && <div className="portfolio-growth-modal" role="presentation" onMouseDown={() => { setClosePhase("idle"); setCloseSuccess(null); }}>
      <section role="dialog" aria-modal="true" aria-label="Alles sluiten voltooid" onMouseDown={(event) => event.stopPropagation()}>
        <h3>Alles sluiten voltooid</h3>
        <p>Alle posities en open orders zijn door Aster bevestigd gesloten.</p>
        <dl>
          <dt>Gesloten posities</dt><dd>{closeSuccess.closedPositions ?? "Bevestigd"}</dd>
          {closeSuccess.newBaseline !== null ? <><dt>Nieuwe startwaarde</dt><dd>{money(closeSuccess.newBaseline)}</dd></> : null}
          <dt>Botstatus</dt><dd>Gepauzeerd</dd>
        </dl>
        <p>{closeSuccess.message}</p>
        <footer><button onClick={() => { setClosePhase("idle"); setCloseSuccess(null); }}>Gereed</button></footer>
      </section>
    </div>}

    {reset && <div className="portfolio-growth-modal" role="presentation" onMouseDown={() => setReset(false)}>
      <section role="dialog" aria-modal="true" aria-label="Startwaarde resetten" onMouseDown={(event) => event.stopPropagation()}>
        <h3>Startwaarde handmatig resetten</h3>
        <p>Deze wijziging wordt met oude waarde, nieuwe waarde, reden en account-ID geaudit.</p>
        <label>Nieuwe startwaarde<input inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} /></label>
        <label>Reden<textarea value={resetReason} onChange={(event) => setResetReason(event.target.value)} /></label>
        <footer><button onClick={() => setReset(false)}>Annuleren</button><button disabled={busy || resetReason.trim().length < 10} onClick={() => saveBaseline(true)}>Reset bevestigen</button></footer>
      </section>
    </div>}
  </>;
}
