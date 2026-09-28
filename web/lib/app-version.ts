export const WEBAPP_VERSION = "46";
// Build 463: Tradecentrum Position Close 1.0 met 25/50/75/100% partial close.
export const WEBAPP_BUILD_NUMBER = "463";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
