export const WEBAPP_VERSION = "46";
// Build 415: BETA zone-owned soldier pools, persistent origin ownership, notional exposure balancing and updated regression contracts.
export const WEBAPP_BUILD_NUMBER = "415";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
