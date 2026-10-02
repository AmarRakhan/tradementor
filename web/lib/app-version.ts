export const WEBAPP_VERSION = "46";
// Build 484: Scanner Status en Prijszone Details lezen canonical Strategy-2 runtime truth.
export const WEBAPP_BUILD_NUMBER = "484";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
