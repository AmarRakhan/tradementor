export const WEBAPP_VERSION = "46";
// Build 414: cold-start on ASTER, tighter Portfolio Koers focus and an operational formation dashboard.
export const WEBAPP_BUILD_NUMBER = "414";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
