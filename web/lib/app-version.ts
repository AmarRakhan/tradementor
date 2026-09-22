export const WEBAPP_VERSION = "46";
// Build 399: Portfolio Koers display-only declutter; visible zone overlays, max three labels and two compact clusters.
export const WEBAPP_BUILD_NUMBER = "399";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
