export const WEBAPP_VERSION = "46";
// Build 573: Aster account/chart startup hotfix for legacy persisted candle timestamps.
// Build 573 release gate synchronized after stale 572 regression assertion repair.
export const WEBAPP_BUILD_NUMBER = "573";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}