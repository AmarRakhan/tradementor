export const WEBAPP_VERSION = "46";
// Build 446: Portfolio Koers Graph 3.0 toont support/resistance, actieve zone, role-flip, nieuwe high en volgende breakout zonder tradinglogica te wijzigen.
export const WEBAPP_BUILD_NUMBER = "446";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
