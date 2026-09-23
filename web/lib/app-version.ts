export const WEBAPP_VERSION = "46";
// Build 403: Botconfigurator V2 beta UI on the established isolated release shell; CI contract aligned.
export const WEBAPP_BUILD_NUMBER = "403";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
