export const WEBAPP_VERSION = "46";
// Build 444: Legacy Hedge Recovery legt capacity-blokkades uit en adviseert de hoogste lagere leverage die het ingevoerde bedrag wél ondersteunt.
export const WEBAPP_BUILD_NUMBER = "444";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
