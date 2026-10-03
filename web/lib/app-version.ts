export const WEBAPP_VERSION = "46";
// Build 491: Snapshot-row herverdeeld; Auto Hedge krijgt eigen ruimte zonder kaart-overlap.
export const WEBAPP_BUILD_NUMBER = "491";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}