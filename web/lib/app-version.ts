export const WEBAPP_VERSION = "46";
// Build 435: startup-flits verwijderd; Portfolio Koers blijft afgedekt tot de eerste canonieke Accountwaarde-load gereed is. Regressiecontract bijgewerkt.
export const WEBAPP_BUILD_NUMBER = "435";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
