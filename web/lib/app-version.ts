export const WEBAPP_VERSION = "46";
// Build 485: Portfolio Koers · Actieve Trades 1.0 (additieve read-only basket-analyse).
export const WEBAPP_BUILD_NUMBER = "485";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}