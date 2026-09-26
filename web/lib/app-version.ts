export const WEBAPP_VERSION = "46";
// Build 441: owner-only Legacy Hedge Recovery vergroot een bestaande 1:1 hedge handmatig met exact gelijke coin quantity per zijde.
export const WEBAPP_BUILD_NUMBER = "441";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
