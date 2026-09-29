export const WEBAPP_VERSION = "46";
// Build 471: handmatige 25/50/75/100%-close kan een Auto Hedge-leg bewust verkleinen zonder dat de hedge-lock de gebruikersactie tegenhoudt.
export const WEBAPP_BUILD_NUMBER = "471";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
