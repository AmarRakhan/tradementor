export const WEBAPP_VERSION = "46";
// Build 409: owner-only BETA Portfolio Koers gives every signed zone a clearly distinct fill and neutralizes non-active boundary lines.
export const WEBAPP_BUILD_NUMBER = "409";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
