export const WEBAPP_VERSION = "46";
// Build 458: Botconfigurator 3.0 · Zone Warriors + Classic DCA · 4-staps BETA-flow.
export const WEBAPP_BUILD_NUMBER = "458";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
