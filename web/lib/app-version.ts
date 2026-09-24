export const WEBAPP_VERSION = "46";
// Build 417 final: Portfolio Koers is informational by default; Zone-Soldatenstrategie requires explicit owner opt-in.
export const WEBAPP_BUILD_NUMBER = "417";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
