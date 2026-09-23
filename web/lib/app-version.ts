export const WEBAPP_VERSION = "46";
// Build 406: BETA Portfolio Koers extrapolates full-height zones so the active zone and soldier advice follow the current equity outside confirmed bands.
export const WEBAPP_BUILD_NUMBER = "406";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
