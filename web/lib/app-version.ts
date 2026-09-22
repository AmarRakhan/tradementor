export const WEBAPP_VERSION = "46";
// Build 400: icon-first Portfolio Koers markers, Bollinger-safe placement, narrower price axis and deterministic 15m opening view.
export const WEBAPP_BUILD_NUMBER = "400";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
