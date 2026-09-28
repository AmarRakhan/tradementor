export const WEBAPP_VERSION = "46";
// Build 464: prijszone-stoelen refill hotfix; PRIORITY_ONLY blokkeert geen vrije zone-stoelen meer.
export const WEBAPP_BUILD_NUMBER = "464";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
