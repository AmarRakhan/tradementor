export const WEBAPP_VERSION = "46";
// Build 416: owner-only zone soldiers plus gentle monotone zone-distance entry sizing.
export const WEBAPP_BUILD_NUMBER = "416";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
