export const WEBAPP_VERSION = "46";
// Build 489: Portfolio Snapshot Auto Hedge-tegel mobiel uitgelijnd.
export const WEBAPP_BUILD_NUMBER = "489";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}