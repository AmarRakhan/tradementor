export const WEBAPP_VERSION = "46";
// Build 447: Profit Push Notifications 1.0 met native Web Push, winstsummaries en Portfolio TP-alerts.
export const WEBAPP_BUILD_NUMBER = "447";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
