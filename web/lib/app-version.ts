export const WEBAPP_VERSION = "46";
// Build 424: Aster-only Ultra Rivalry presentation skin; trading behavior unchanged.
export const WEBAPP_BUILD_NUMBER = "424";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
