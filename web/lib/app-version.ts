export const WEBAPP_VERSION = "46";
// Build 422: owner-only soldier activity windows and viewport-aware all-visible chart events.
export const WEBAPP_BUILD_NUMBER = "422";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
