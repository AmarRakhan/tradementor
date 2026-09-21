export const WEBAPP_VERSION = "46";
// Build 390: stale UI state can no longer restore an old Strategy-2 sizing mode.
export const WEBAPP_BUILD_NUMBER = "390";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
