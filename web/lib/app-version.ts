export const WEBAPP_VERSION = "46";
// Build 445: centrale BETA/STABLE-entitlements vervangen owner-only testgates zonder instellingen of trading automatisch te activeren.
export const WEBAPP_BUILD_NUMBER = "445";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
