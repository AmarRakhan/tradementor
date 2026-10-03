export const WEBAPP_VERSION = "46";
// Build 492: Auto Hedge gridfix releasebaar gemaakt; regressietest volgt de nieuwe native grid-layout.
export const WEBAPP_BUILD_NUMBER = "492";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}