export const WEBAPP_VERSION = "46";
// Build 443: centrale BETA/STABLE release-entitlements voor Zone-Soldaten, Command Center, Auto Hedge en Legacy Hedge Recovery.
export const WEBAPP_BUILD_NUMBER = "443";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
