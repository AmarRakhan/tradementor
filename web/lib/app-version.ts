export const WEBAPP_VERSION = "46";
// Build 414: cold-start on ASTER, tighter Portfolio Koers focus and an operational formation dashboard; regression fixture aligned to the intended in-zone focus window.
export const WEBAPP_BUILD_NUMBER = "414";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
