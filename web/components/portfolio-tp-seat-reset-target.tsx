"use client";

import { useEffect, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type Props = {
  savedLong: number;
  savedShort: number;
  currentLong: number;
  currentShort: number;
  legacyFallback?: boolean;
  onConfirmed: (strategy2: Record<string, unknown>) => void;
  onChanged: () => void;
};

const whole = (value: string) => {
  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const parsed = Number(trimmed);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : null;
};

export function PortfolioTpSeatResetTarget({
  savedLong,
  savedShort,
  currentLong,
  currentShort,
  legacyFallback = false,
  onConfirmed,
  onChanged,
}: Props) {
  const [confirmedLong, setConfirmedLong] = useState(Math.max(0, Math.round(savedLong)));
  const [confirmedShort, setConfirmedShort] = useState(Math.max(0, Math.round(savedShort)));
  const [longDraft, setLongDraft] = useState(String(Math.max(0, Math.round(savedLong))));
  const [shortDraft, setShortDraft] = useState(String(Math.max(0, Math.round(savedShort))));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (dirty) return;
    const nextLong = Math.max(0, Math.round(savedLong));
    const nextShort = Math.max(0, Math.round(savedShort));
    setConfirmedLong(nextLong);
    setConfirmedShort(nextShort);
    setLongDraft(String(nextLong));
    setShortDraft(String(nextShort));
  }, [savedLong, savedShort, dirty]);

  const changeLong = (value: string) => {
    setLongDraft(value);
    setDirty(true);
    setMessage("");
  };
  const changeShort = (value: string) => {
    setShortDraft(value);
    setDirty(true);
    setMessage("");
  };

  async function saveResetValues() {
    const longValue = whole(longDraft);
    const shortValue = whole(shortDraft);
    if (longValue === null || shortValue === null) {
      setMessage("Gebruik voor LONG en SHORT een geheel getal van 0 of hoger.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const result = await authenticatedRequest("/api/exchanges/aster/strategy2/settings", {
        method: "PUT",
        body: JSON.stringify({
          settings: {
            portfolioTpResetLongSlots: longValue,
            portfolioTpResetShortSlots: shortValue,
          },
        }),
      }) as Record<string, unknown>;
      const strategy2 = result.strategy2 && typeof result.strategy2 === "object"
        ? result.strategy2 as Record<string, unknown>
        : null;
      const settings = strategy2?.settings && typeof strategy2.settings === "object"
        ? strategy2.settings as Record<string, unknown>
        : null;
      if (!strategy2 || !settings) throw new Error("Server heeft de resetwaarden niet bevestigd.");
      const serverLong = Number(settings.portfolioTpResetLongSlots);
      const serverShort = Number(settings.portfolioTpResetShortSlots);
      if (!Number.isInteger(serverLong) || serverLong < 0 || !Number.isInteger(serverShort) || serverShort < 0) {
        throw new Error("Server gaf geen geldige LONG/SHORT-resetwaarden terug.");
      }
      setConfirmedLong(serverLong);
      setConfirmedShort(serverShort);
      setLongDraft(String(serverLong));
      setShortDraft(String(serverShort));
      setDirty(false);
      setMessage("Resetwaarden server-side opgeslagen.");
      onConfirmed(strategy2);
      await Promise.resolve(onChanged());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Resetwaarden opslaan mislukt.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="ptp-reset-target" data-feature="portfolio-tp-seat-reset-target-2">
    <div className="ptp-reset-inputs">
      <label><span>LONG na reset</span><span className="ptp-reset-field"><input inputMode="numeric" pattern="[0-9]*" value={longDraft} onChange={(event) => changeLong(event.target.value)} aria-label="LONG na reset" /><em>slots</em></span></label>
      <label><span>SHORT na reset</span><span className="ptp-reset-field"><input inputMode="numeric" pattern="[0-9]*" value={shortDraft} onChange={(event) => changeShort(event.target.value)} aria-label="SHORT na reset" /><em>slots</em></span></label>
      <button type="button" className="ptp-reset-save" disabled={!dirty || busy} onClick={() => void saveResetValues()}>{busy ? "Opslaan…" : "Resetwaarden opslaan"}</button>
    </div>
    {legacyFallback && <p className="ptp-reset-migration">Nog geen aparte resetwaarden opgeslagen. Tot je opslaat blijven de bestaande cyclus-startwaarden leidend.</p>}
    {dirty && <p className="ptp-reset-unsaved">Niet opgeslagen — de kaart hieronder blijft de server-bevestigde resetwaarde tonen.</p>}
    {message && <p className="ptp-reset-message">{message}</p>}
    <div className="ptp-reset-flow" aria-label="Portfolio TP resetdoel">
      <span><small>Nu ingesteld</small><b>{Math.max(0, Math.round(currentLong))}L / {Math.max(0, Math.round(currentShort))}S</b></span>
      <i>→</i>
      <span className="close"><small>Portfolio TP</small><b>Alles dicht</b></span>
      <i>→</i>
      <span><small>Reset naar</small><b>{confirmedLong}L / {confirmedShort}S</b></span>
    </div>
    <small className="ptp-reset-note">Opslaan wijzigt alleen het toekomstige resetdoel. Er wordt geen positie geopend of gesloten. De reset wordt pas toegepast na bevestigde flat-state.</small>
    <style>{`
      .ptp-reset-target{display:grid;gap:12px;margin-top:12px}
      .ptp-reset-inputs{display:grid;grid-template-columns:1fr 1fr auto;gap:10px;align-items:end}
      .ptp-reset-inputs label{display:grid;gap:6px;font-size:12px;color:#c7d0c9}
      .ptp-reset-field{display:flex;min-height:48px;border:1px solid rgba(212,178,72,.42);border-radius:12px;overflow:hidden;background:rgba(0,0,0,.28)}
      .ptp-reset-field input{min-width:0;width:100%;border:0;outline:0;background:transparent;color:#fff;font:700 18px/1.2 inherit;padding:0 12px}
      .ptp-reset-field em{display:flex;align-items:center;padding:0 10px;color:#9fa8a1;font-style:normal;font-size:11px}
      .ptp-reset-save{min-height:48px;border:1px solid rgba(232,190,62,.7);border-radius:12px;background:linear-gradient(135deg,rgba(176,133,20,.34),rgba(8,83,59,.55));color:#fff6c6;font-weight:800;padding:0 14px}
      .ptp-reset-save:disabled{opacity:.45}
      .ptp-reset-migration,.ptp-reset-unsaved,.ptp-reset-message{margin:0;border-radius:10px;padding:9px 10px;font-size:11px;line-height:1.45}
      .ptp-reset-migration{background:rgba(232,190,62,.08);color:#d9cca0}
      .ptp-reset-unsaved{background:rgba(232,190,62,.12);color:#ffe08a}
      .ptp-reset-message{background:rgba(17,185,125,.09);color:#aee8d2}
      .ptp-reset-flow{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:8px;align-items:center}
      .ptp-reset-flow>span{min-height:62px;display:grid;place-content:center;text-align:center;border:1px solid rgba(190,165,83,.34);border-radius:12px;background:rgba(0,0,0,.22)}
      .ptp-reset-flow small{display:block;color:#9ea7a0;font-size:10px;margin-bottom:5px}
      .ptp-reset-flow b{font-size:14px;color:#f6f7f4}
      .ptp-reset-flow i{color:#27e7a6;font-style:normal}
      .ptp-reset-flow .close{border-color:rgba(210,178,70,.44)}
      .ptp-reset-note{display:block;color:#99a29c;line-height:1.45}
      @media(max-width:620px){.ptp-reset-inputs{grid-template-columns:1fr 1fr}.ptp-reset-save{grid-column:1/-1}.ptp-reset-flow{grid-template-columns:1fr auto 1fr auto 1fr;gap:5px}.ptp-reset-flow>span{min-height:58px;padding:5px}.ptp-reset-flow b{font-size:12px}}
      @media(max-width:360px){.ptp-reset-inputs{grid-template-columns:1fr}.ptp-reset-save{grid-column:auto}.ptp-reset-flow{grid-template-columns:1fr}.ptp-reset-flow>i{transform:rotate(90deg);text-align:center}}
    `}</style>
  </div>;
}
