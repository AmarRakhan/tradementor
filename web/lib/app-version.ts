export const WEBAPP_VERSION = "46";
// Build 392: independent LONG/SHORT slot controls with completed regression validation.
export const WEBAPP_BUILD_NUMBER = "392";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
