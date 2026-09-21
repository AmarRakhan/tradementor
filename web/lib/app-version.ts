export const WEBAPP_VERSION = "46";
// Build 389: Portfolio TP remains additive to the pair-level Take Profit.
export const WEBAPP_BUILD_NUMBER = "389";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
