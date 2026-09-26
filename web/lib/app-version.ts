export const WEBAPP_VERSION = "46";
// Build 439: dagrendement telt liquidatie/tradingeffecten mee en reconstrueert alle betrouwbare account-equityhistorie.
export const WEBAPP_BUILD_NUMBER = "439";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
