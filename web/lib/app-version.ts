export const WEBAPP_VERSION = "46";
// Build 567: persistent S/R ladder + durable order-attribution event labels; no trading logic changes.
export const WEBAPP_BUILD_NUMBER = "567";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}