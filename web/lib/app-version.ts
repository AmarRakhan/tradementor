export const WEBAPP_VERSION = "46";
// Build 464: realtime LONG/SHORT instapmeldingen met confirmed-fill gating en deduplicatie.
export const WEBAPP_BUILD_NUMBER = "464";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
