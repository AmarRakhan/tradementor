export const WEBAPP_VERSION = "46";
// Build 506: Profit Sparen 3.1 · elke bewezen winstclose telt + recovery van vandaag.
export const WEBAPP_BUILD_NUMBER = "506";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}