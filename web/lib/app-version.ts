export const WEBAPP_VERSION = "46";
// Build 402: Botconfigurator V2 beta-only rollout with isolated release flags and exposure-aware entry controls.
export const WEBAPP_BUILD_NUMBER = "402";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
