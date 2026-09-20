export const WEBAPP_VERSION = "46";
export const WEBAPP_BUILD_NUMBER = "385";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
