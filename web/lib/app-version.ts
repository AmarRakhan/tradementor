export const WEBAPP_VERSION = "46";
// Build 473: Portfolio Koers UI 4.1 referentiepariteit — hogere mobiele chart, langere 15m-tijdlijn en bevestigde TP-details.
export const WEBAPP_BUILD_NUMBER = "473";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
