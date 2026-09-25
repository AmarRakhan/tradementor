export const WEBAPP_VERSION = "46";
// Build 430: Per-position Auto Hedge candidate with pixel-bound 3D settings.
export const WEBAPP_BUILD_NUMBER = "430";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
