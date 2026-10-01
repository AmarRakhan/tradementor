export const WEBAPP_VERSION = "46";
// Build 483: Zichtbare tabbladen 2.0 met per-user cloudpersistence en directe mobiele nav-sync.
export const WEBAPP_BUILD_NUMBER = "483";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
