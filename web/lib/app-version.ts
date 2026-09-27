export const WEBAPP_VERSION = "46";
// Build 455: Prijszone-stoelen 1.0 · gedeelde zonebron, harde globale cap, instellingen en Portfolio Snapshot.
export const WEBAPP_BUILD_NUMBER = "455";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
