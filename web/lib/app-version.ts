export const WEBAPP_VERSION = "46";
// Build 478: Botconfigurator 3.0 — exact referentie-artwork voor Zone Warriors en Classic DCA.
export const WEBAPP_BUILD_NUMBER = "478";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
