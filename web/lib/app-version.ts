export const WEBAPP_VERSION = "46";
// Build 393: persistent live Portfolio Koers chart above the unchanged Portfolio Snapshot.
export const WEBAPP_BUILD_NUMBER = "393";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
