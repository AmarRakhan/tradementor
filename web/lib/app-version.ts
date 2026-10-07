export const WEBAPP_VERSION = "46";
// Build 565: canonical Build 518-style session chart + unified-engine live event labels; regression contract synchronized.
export const WEBAPP_BUILD_NUMBER = "565";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}