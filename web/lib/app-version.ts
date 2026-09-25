export const WEBAPP_VERSION = "46";
// Build 431: Auto Hedge 2.0 exact 1:1 lifecycle, hedge-lock, recovery and rehedge.
export const WEBAPP_BUILD_NUMBER = "431";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
