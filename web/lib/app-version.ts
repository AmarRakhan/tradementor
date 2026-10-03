export const WEBAPP_VERSION = "46";
// Build 493: Snapshot-kaartteksten passen volledig binnen hun eigen randen op mobiel.
export const WEBAPP_BUILD_NUMBER = "493";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}