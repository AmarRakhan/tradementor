export const WEBAPP_VERSION = "46";
// Build 396: PWA startup is single-load; service-worker takeover no longer reloads during Firebase session restore.\nexport const WEBAPP_BUILD_NUMBER = "396";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
