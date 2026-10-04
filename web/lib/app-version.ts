export const WEBAPP_VERSION = "46";
// Build 505: Profit Pot dagtotaal incl. buffer + live USDC Spot saldo.
export const WEBAPP_BUILD_NUMBER = "505";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}