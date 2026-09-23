export const WEBAPP_VERSION = "46";
// Build 408: owner-only BETA Portfolio Koers becomes a clear zone decision map with explicit boundaries and next-level triggers.
export const WEBAPP_BUILD_NUMBER = "408";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
