export const WEBAPP_VERSION = "46";
// Build 466: Position Close toont direct voortgang en backendfouten op mobiel.
export const WEBAPP_BUILD_NUMBER = "466";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
