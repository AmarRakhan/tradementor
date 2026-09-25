export const WEBAPP_VERSION = "46";
// Build 428: Friends community analytics with risk-aware mobile trader profiles.
export const WEBAPP_BUILD_NUMBER = "428";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
