export const WEBAPP_VERSION = "46";
// Build 572: Price-zone cycle overview no longer gets stuck when chart/event reads are slow or partially unavailable.
export const WEBAPP_BUILD_NUMBER = "572";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}