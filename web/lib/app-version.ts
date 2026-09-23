export const WEBAPP_VERSION = "46";
// Build 410: explain the Portfolio Koers zone basis and distinguish net exposure from PnL.
// Build 410 release-contract sync: version, release history and regression correction travel together.
export const WEBAPP_BUILD_NUMBER = "410";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
