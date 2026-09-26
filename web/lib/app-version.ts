export const WEBAPP_VERSION = "46";
// Build 437: Portfolio Snapshot krijgt Zone-Soldaten quick actions en een volledig losse, opaque Command Center-pagina.
export const WEBAPP_BUILD_NUMBER = "437";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
