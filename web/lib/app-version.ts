export const WEBAPP_VERSION = "46";
// Build 477: Portfolio Snapshot detailweergaven — Prijszone Details + Scanner Status.
export const WEBAPP_BUILD_NUMBER = "477";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
