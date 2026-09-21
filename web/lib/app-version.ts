export const WEBAPP_VERSION = "46";
// Build 391: LONG/SHORT slot edits are independent; the untouched side stays fixed and total positions follows the sum.
export const WEBAPP_BUILD_NUMBER = "391";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
