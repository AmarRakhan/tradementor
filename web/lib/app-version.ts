export const WEBAPP_VERSION = "46";
// Build 434: Portfolio Koers opent standaard in Accountwaarde; Performance blijft handmatig beschikbaar.
export const WEBAPP_BUILD_NUMBER = "434";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
