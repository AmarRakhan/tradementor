export const WEBAPP_VERSION = "46";
// Build 476: Botconfigurator strategie-iconen — release-regressies uitgelijnd na Build 475.
export const WEBAPP_BUILD_NUMBER = "476";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
