export const WEBAPP_VERSION = "46";
// Build 528: restore visible Aster bot on/off switch in Botconfigurator 3.0.
export const WEBAPP_BUILD_NUMBER = "528";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}