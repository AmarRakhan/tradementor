export const WEBAPP_VERSION = "46";
// Build 488: Gesloten resultaat telt alleen exchange-bewezen volledig gesloten posities.
export const WEBAPP_BUILD_NUMBER = "488";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}