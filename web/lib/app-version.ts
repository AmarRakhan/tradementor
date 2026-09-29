export const WEBAPP_VERSION = "46";
// Build 469: actieve prijszone-stoelen blijven numeriek zichtbaar tijdens een zonewissel via exchange-bevestigde per-zone bezetting. Release-history contract gesynchroniseerd.
export const WEBAPP_BUILD_NUMBER = "469";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
