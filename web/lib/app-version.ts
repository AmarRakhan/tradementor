export const WEBAPP_VERSION = "46";
// Build 448: Profit Push Notifications 1.0 bovenop Portfolio Koers Graph 3.1.
export const WEBAPP_BUILD_NUMBER = "448";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
