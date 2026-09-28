export const WEBAPP_VERSION = "46";
// Build 465: live instapdiagnose toont exact welke gate vrije prijszone-stoelen tegenhoudt.
export const WEBAPP_BUILD_NUMBER = "465";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
