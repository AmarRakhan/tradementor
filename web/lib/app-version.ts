export const WEBAPP_VERSION = "46";
// Build 550: always-visible Portfolio Koers price zones with aligned regression and deploy contract.
export const WEBAPP_BUILD_NUMBER = "550";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}