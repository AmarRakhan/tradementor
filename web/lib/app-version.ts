export const WEBAPP_VERSION = "46";
// Build 413: Portfolio Koers opens zone-focused and shows adjacent-zone distance primarily as live percentages.
export const WEBAPP_BUILD_NUMBER = "413";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
