export const WEBAPP_VERSION = "46";
// Build 401: Portfolio Koers matches the approved crossed-swords reference with real confirmed equity zone regions.
export const WEBAPP_BUILD_NUMBER = "401";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
