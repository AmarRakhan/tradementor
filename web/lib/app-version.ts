export const WEBAPP_VERSION = "46";
// Build 425: reusable zone missions and true old-zone profitable homecomings.
export const WEBAPP_BUILD_NUMBER = "425";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
