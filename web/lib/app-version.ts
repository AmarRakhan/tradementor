export const WEBAPP_VERSION = "46";
// Build 482: Rendement Overzicht 1.0 met auditbare daghistorie en 3D detailweergave.
export const WEBAPP_BUILD_NUMBER = "482";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
