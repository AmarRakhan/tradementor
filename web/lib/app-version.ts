export const WEBAPP_VERSION = "46";
// Build 480: Portfolio Snapshot Auto Hedge + Portfolio Cyclus status-tegels opgeschoond.
export const WEBAPP_BUILD_NUMBER = "480";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
