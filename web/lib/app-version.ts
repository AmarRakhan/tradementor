export const WEBAPP_VERSION = "46";
// Build 418: owner-only App Continuity Monitor with read-only Bybit reserve.
export const WEBAPP_BUILD_NUMBER = "418";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
