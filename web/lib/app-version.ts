export const WEBAPP_VERSION = "46";
// Build 456: prijszone Max actieve stoelen blijft exact de expliciet opgeslagen globale limiet.
export const WEBAPP_BUILD_NUMBER = "456";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
