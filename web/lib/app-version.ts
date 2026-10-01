export const WEBAPP_VERSION = "46";
// Build 481: Portfolio Snapshot Auto Hedge + Portfolio Cyclus visueel afgewerkt.
export const WEBAPP_BUILD_NUMBER = "481";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
