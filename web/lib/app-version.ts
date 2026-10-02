export const WEBAPP_VERSION = "46";
// Build 487: Actieve Trades 1.2 (server-side 1m historie, onafhankelijk van open tab/app).
export const WEBAPP_BUILD_NUMBER = "487";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}