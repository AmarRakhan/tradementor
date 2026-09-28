export const WEBAPP_VERSION = "46";
// Build 462: Portfolio TP stoelreset ook beschikbaar in legacy/STABLE Botinstellingen.
export const WEBAPP_BUILD_NUMBER = "462";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
