export const WEBAPP_VERSION = "46";
// Build 419: fix first Zone-Soldaten opt-in defaults so legacy accounts can save safely.
export const WEBAPP_BUILD_NUMBER = "419";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
