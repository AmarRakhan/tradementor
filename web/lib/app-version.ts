export const WEBAPP_VERSION = "46";
// Build 460: Portfolio TP · automatische stoelreset 1.0 · BETA TESTEN.
export const WEBAPP_BUILD_NUMBER = "460";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
