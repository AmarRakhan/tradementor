export const WEBAPP_VERSION = "46";
// Build 426: realtime Portfolio Koers trade markers from confirmed Strategy-2 audit events.
export const WEBAPP_BUILD_NUMBER = "426";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
