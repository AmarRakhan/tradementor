export const WEBAPP_VERSION = "46";
// Build 486: Portfolio Koers · Actieve Trades 1.1 (zelfde chartstijl en candle-dichtheid als Accountwaarde).
export const WEBAPP_BUILD_NUMBER = "486";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}