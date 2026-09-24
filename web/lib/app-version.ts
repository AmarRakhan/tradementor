export const WEBAPP_VERSION = "46";
// Build 420: stabilize Portfolio Koers, add the compact strategy cockpit, and clarify optional exposure-refill.
export const WEBAPP_BUILD_NUMBER = "420";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
