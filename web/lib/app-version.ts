export const WEBAPP_VERSION = "46";
// Build 451: native pushmeldingen tonen geen Amar Crypto Bot-tekst meer in de melding zelf.
export const WEBAPP_BUILD_NUMBER = "451";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
