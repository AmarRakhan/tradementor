export const WEBAPP_VERSION = "46";
// Build 405: owner-only BETA Portfolio Koers gets stronger zones plus a functional soldier seat-capacity instruction bar.
export const WEBAPP_BUILD_NUMBER = "405";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
