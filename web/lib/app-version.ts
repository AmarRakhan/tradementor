export const WEBAPP_VERSION = "46";
// Build 442: Legacy Hedge Recovery preview toont per zijde de break-evenafstand vóór en na verhogen, plus de relatieve afstandsverbetering.
export const WEBAPP_BUILD_NUMBER = "442";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
