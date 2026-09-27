export const WEBAPP_VERSION = "46";
// Build 457: Portfolio Koers en Portfolio Snapshot delen exact dezelfde live actieve prijszone.
export const WEBAPP_BUILD_NUMBER = "457";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
