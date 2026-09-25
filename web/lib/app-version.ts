export const WEBAPP_VERSION = "46";
// Build 427: harden owner-only continuity monitor Bybit reserve calculation.
export const WEBAPP_BUILD_NUMBER = "427";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
