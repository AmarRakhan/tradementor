export const WEBAPP_VERSION = "46";
// Build 432: Portfolio Koers 2.0 cashflow-corrected performance + live Zone-Soldaten status.
export const WEBAPP_BUILD_NUMBER = "432";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
