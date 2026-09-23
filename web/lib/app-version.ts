export const WEBAPP_VERSION = "46";
// Build 407: owner-only BETA Portfolio Koers uses one canonical 15m zone ladder across every chart timeframe.
export const WEBAPP_BUILD_NUMBER = "407";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
