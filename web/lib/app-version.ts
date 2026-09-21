export const WEBAPP_VERSION = "46";
// Build 387: productionfixes are visible in Versiegeschiedenis; build 386 remains historical.
export const WEBAPP_BUILD_NUMBER = "387";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
