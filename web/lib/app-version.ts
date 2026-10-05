export const WEBAPP_VERSION = "46";
// Build 513: Portfolio Koers visuele upgrade 1.1 · stable viewport + premium zone/marker UX.
export const WEBAPP_BUILD_NUMBER = "513";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}