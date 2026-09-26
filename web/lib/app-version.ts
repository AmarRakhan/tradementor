export const WEBAPP_VERSION = "46";
// Build 436: Auto Hedge kan niet meer stil worden uitgezet; expliciete bevestiging en server-side wijzigingsaudit toegevoegd.
export const WEBAPP_BUILD_NUMBER = "436";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
