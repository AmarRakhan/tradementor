export const WEBAPP_VERSION = "46";
// Build 411: keep Portfolio Koers on the live candle, expose history gaps and fail closed for soldier advice.
// Build 411 also pairs with server-side continuous equity sampling and contiguous-only zone evidence.
export const WEBAPP_BUILD_NUMBER = "411";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
