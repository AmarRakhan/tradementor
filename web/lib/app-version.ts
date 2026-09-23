export const WEBAPP_VERSION = "46";
// Build 404: Botconfigurator V2 seat bars show live occupied/capacity per side instead of configured share of total.
export const WEBAPP_BUILD_NUMBER = "404";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
