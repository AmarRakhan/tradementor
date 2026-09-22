export const WEBAPP_VERSION = "46";
// Build 397: PWA startup is passive; updates never reload/navigate or seize control during session restore.
export const WEBAPP_BUILD_NUMBER = "397";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
