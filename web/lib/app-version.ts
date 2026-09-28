export const WEBAPP_VERSION = "46";
// Build 459: Botconfigurator 3.1 · server-confirmed huidige instellingen + snel wijzigen · BETA-only.
export const WEBAPP_BUILD_NUMBER = "459";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
