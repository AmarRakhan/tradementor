export const WEBAPP_VERSION = "46";
// Build 429: Friends portal visibility hotfix on mobile.
export const WEBAPP_BUILD_NUMBER = "429";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
