export const WEBAPP_VERSION = "46";
// Build 390: server-fresh Strategy-2 sizing isolation; existing preservation and Sniper history contracts retained.
export const WEBAPP_BUILD_NUMBER = "390";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
