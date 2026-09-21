export const WEBAPP_VERSION = "46";
// Build 388: Portfolio Snapshot shows active versus configured LONG/SHORT slot capacity.
export const WEBAPP_BUILD_NUMBER = "388";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
