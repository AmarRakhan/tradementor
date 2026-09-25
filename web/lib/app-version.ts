export const WEBAPP_VERSION = "46";
// Build 428: complete owner-only continuity reserve preset UX.
export const WEBAPP_BUILD_NUMBER = "428";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
