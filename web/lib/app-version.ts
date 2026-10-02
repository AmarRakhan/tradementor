export const WEBAPP_VERSION = "46";
// Build 484: Runtime Contract V1 operational UI truth voor Scanner Status, Prijszone Details en Portfolio Koers.
export const WEBAPP_BUILD_NUMBER = "484";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
