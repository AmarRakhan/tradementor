export const WEBAPP_VERSION = "46";
// Build 387 release-history hotfix marker: fixes are visible in Versiegeschiedenis.
export const WEBAPP_BUILD_NUMBER = "387";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
