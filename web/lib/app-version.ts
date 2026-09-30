export const WEBAPP_VERSION = "46";
// Build 472: Portfolio Koers UI 4.1 — pixel-referentie, live-zone source of truth en TP-cluster flipdetails.
export const WEBAPP_BUILD_NUMBER = "472";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
