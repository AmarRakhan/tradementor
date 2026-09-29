export const WEBAPP_VERSION = "46";
// Build 468: handmatig sluiten van beide Auto Hedge-legs zet de overblijvende leg veilig in Recovery zonder automatische heropening.
export const WEBAPP_BUILD_NUMBER = "468";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
