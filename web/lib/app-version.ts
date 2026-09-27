export const WEBAPP_VERSION = "46";
// Build 449: Profit Push Notifications 1.1 herstelt geweigerde/stale device subscriptions automatisch.
export const WEBAPP_BUILD_NUMBER = "449";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
