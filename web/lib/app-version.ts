export const WEBAPP_VERSION = "46";
// Build 450: Profit Push Notifications 1.2 fixeert VAPID private-key serialisatie voor native Web Push.
export const WEBAPP_BUILD_NUMBER = "450";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
