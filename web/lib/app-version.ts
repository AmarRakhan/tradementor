export const WEBAPP_VERSION = "46";
// Build 475: Botconfigurator 3.0 — herstel van de goedgekeurde Zone Warriors #1 en Classic DCA #10 strategie-iconen.
export const WEBAPP_BUILD_NUMBER = "475";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
