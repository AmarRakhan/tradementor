export const WEBAPP_VERSION = "44";
export function webappVersionLabel(buildNumber: string) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
