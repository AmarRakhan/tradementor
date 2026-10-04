export const WEBAPP_VERSION = "46";
// Build 504: startup fast path · Aster snapshot/realtime parallel met sessie-bootstrap, bounded retries.
export const WEBAPP_BUILD_NUMBER = "504";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}