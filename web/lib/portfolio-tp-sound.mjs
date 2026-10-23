// Portfolio TP-geluid (hoorn): speelt één keer per behaalde Portfolio Take Profit af,
// alleen terwijl de app open en zichtbaar is. Alleen weergave/geluid; nooit trading.

export const PORTFOLIO_TP_SOUND_URL = "/sounds/portfolio-tp-horn.mp3";
export const PORTFOLIO_TP_SOUND_ENABLED_KEY = "amar.portfolioTpSound.enabled.v1";
export const PORTFOLIO_TP_SOUND_LAST_KEY = "amar.portfolioTpSound.lastCycleId.v1";
// Een TP die langer geleden is dan dit (app was dicht) krijgt geen hoorn meer bij openen:
// je hebt de pushmelding dan al gezien, een late hoorn is verwarrend.
export const PORTFOLIO_TP_SOUND_MAX_AGE_MS = 60 * 1000;
// Bericht van de service worker zodra de pushmelding "Portfolio Take Profit behaald" binnenkomt.
export const PORTFOLIO_TP_PUSH_MESSAGE = "amar:portfolio-tp-horn";

/**
 * Pure beslissing: moet de hoorn afgaan voor deze laatste Portfolio TP?
 * - store: het cycleId dat als "gehoord" moet worden bewaard (of null = niets wijzigen)
 * - play: alleen bij een nieuw cycleId, recent, en geluid AAN
 */
export function decidePortfolioTpSound({ latest, lastCycleId, enabled, nowMs }) {
  const cycleId = latest && typeof latest === "object" ? String(latest.cycleId || "") : "";
  if (!cycleId) return { play: false, store: null };
  if (lastCycleId && String(lastCycleId) === cycleId) return { play: false, store: null };
  const occurredAtMs = Number(latest.occurredAtMs || 0);
  const ageMs = Number(nowMs) - occurredAtMs;
  const recent = occurredAtMs > 0 && ageMs >= -60_000 && ageMs <= PORTFOLIO_TP_SOUND_MAX_AGE_MS;
  return { play: Boolean(enabled) && recent, store: cycleId };
}

function readStorage(key) {
  try { return window.localStorage.getItem(key); } catch { return null; }
}

function writeStorage(key, value) {
  try { window.localStorage.setItem(key, value); } catch {}
}

export function isPortfolioTpSoundEnabled() {
  return readStorage(PORTFOLIO_TP_SOUND_ENABLED_KEY) !== "0";
}

export function setPortfolioTpSoundEnabled(enabled) {
  writeStorage(PORTFOLIO_TP_SOUND_ENABLED_KEY, enabled ? "1" : "0");
}

let audio = null;
let unlocked = false;

function hornAudio() {
  if (typeof window === "undefined" || typeof Audio === "undefined") return null;
  if (!audio) {
    audio = new Audio(PORTFOLIO_TP_SOUND_URL);
    audio.preload = "auto";
  }
  return audio;
}

// Browsers (vooral iPhone) spelen pas geluid af na een tik in de app.
// Bij de eerste tik/toets ontgrendelen we de hoorn één keer stil.
export function installPortfolioTpSoundUnlock() {
  if (typeof window === "undefined") return () => {};
  const unlock = () => {
    if (unlocked) return;
    const element = hornAudio();
    if (!element) return;
    unlocked = true;
    element.muted = true;
    const done = () => { element.pause(); element.currentTime = 0; element.muted = false; };
    try {
      const attempt = element.play();
      if (attempt && typeof attempt.then === "function") attempt.then(done, () => { element.muted = false; unlocked = false; });
      else done();
    } catch {
      element.muted = false;
      unlocked = false;
    }
  };
  const options = { capture: true, passive: true };
  window.addEventListener("pointerdown", unlock, options);
  window.addEventListener("keydown", unlock, options);
  return () => {
    window.removeEventListener("pointerdown", unlock, options);
    window.removeEventListener("keydown", unlock, options);
  };
}

export function playPortfolioTpSound() {
  const element = hornAudio();
  if (!element) return Promise.resolve(false);
  try {
    element.pause();
    element.muted = false;
    element.currentTime = 0;
    const attempt = element.play();
    if (attempt && typeof attempt.then === "function") return attempt.then(() => true, () => false);
    return Promise.resolve(true);
  } catch {
    return Promise.resolve(false);
  }
}

// Verwerkt "latestPortfolioTp" uit /api/notifications/recent. Gedeeld over tabbladen via
// localStorage, zodat twee open tabbladen de hoorn niet dubbel afspelen.
export function handleLatestPortfolioTp(latest, nowMs = Date.now()) {
  const decision = decidePortfolioTpSound({
    latest,
    lastCycleId: readStorage(PORTFOLIO_TP_SOUND_LAST_KEY),
    enabled: isPortfolioTpSoundEnabled(),
    nowMs,
  });
  if (decision.store) writeStorage(PORTFOLIO_TP_SOUND_LAST_KEY, decision.store);
  if (decision.play) void playPortfolioTpSound();
  return decision;
}

// Pure check voor het seintje van de service worker: alleen een vers bericht met cycleId telt.
// receivedAtMs is het moment waarop de pushmelding op dit toestel binnenkwam.
export function portfolioTpFromPushMessage(data, nowMs) {
  if (!data || typeof data !== "object" || data.type !== PORTFOLIO_TP_PUSH_MESSAGE) return null;
  const cycleId = String(data.cycleId || "");
  const receivedAtMs = Number(data.receivedAtMs || 0);
  if (!cycleId || !(receivedAtMs > 0)) return null;
  if (Number(nowMs) - receivedAtMs > PORTFOLIO_TP_SOUND_MAX_AGE_MS) return null;
  return { cycleId, phase: "PUSH", occurredAtMs: receivedAtMs };
}

// Hoorn op hetzelfde moment als de pushmelding, als de app open is (ook in een ander tabblad).
// Dezelfde opslag als de poll, dus nooit dubbel per Portfolio TP.
export function listenForPortfolioTpPush() {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return () => {};
  const onMessage = (event) => {
    const latest = portfolioTpFromPushMessage(event && event.data, Date.now());
    if (latest) handleLatestPortfolioTp(latest);
  };
  navigator.serviceWorker.addEventListener("message", onMessage);
  return () => navigator.serviceWorker.removeEventListener("message", onMessage);
}
