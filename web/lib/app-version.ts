export const WEBAPP_VERSION = "46";
// Build 555: draw next-zone lines from confirmed 15m history even when the backend zone payload is empty.
export const WEBAPP_BUILD_NUMBER = "555";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}