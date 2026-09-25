export const WEBAPP_VERSION = "46";
// Build 430: account-wide Soldiers reconciliation, margin diagnostics and truthful live status.
export const WEBAPP_BUILD_NUMBER = "430";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
