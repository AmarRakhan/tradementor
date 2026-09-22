export const WEBAPP_VERSION = "46";
// Build 398: Portfolio Koers visual calm pass; max five full event labels, collision clustering and price-scaled zone bands.
export const WEBAPP_BUILD_NUMBER = "398";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
