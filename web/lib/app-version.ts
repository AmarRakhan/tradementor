export const WEBAPP_VERSION = "46";
// Build 511: iPhone/iOS Scroll Performance 1.0 · CI contract aligned with native async scrolling.
export const WEBAPP_BUILD_NUMBER = "511";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}