export const WEBAPP_VERSION = "46";
// Build 540: publish zero-sided Zone Warriors runtime + max-cap sync with corrected release contract.
export const WEBAPP_BUILD_NUMBER = "540";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}