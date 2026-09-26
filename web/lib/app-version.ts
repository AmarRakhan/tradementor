export const WEBAPP_VERSION = "46";
// Build 440: Portfolio TP herstart uitsluitend vanaf bevestigde werkelijke post-close equity en toont de duurzame cycle als bron van waarheid.
export const WEBAPP_BUILD_NUMBER = "440";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
