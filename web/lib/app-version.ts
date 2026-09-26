export const WEBAPP_VERSION = "46";
// Build 443: Legacy Hedge Recovery gebruikt actuele Aster openingsruimte en herplant veilig na leverage-/capacitywijzigingen.
export const WEBAPP_BUILD_NUMBER = "443";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
