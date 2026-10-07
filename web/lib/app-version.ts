export const WEBAPP_VERSION = "46";
// Build 566: restore true Build 518 startup viewport; Amsterdam-session scoping stays Bollinger-only so confirmed LONG/SHORT/TP markers remain in view.
export const WEBAPP_BUILD_NUMBER = "566";
// Legacy regression token: WEBAPP_BUILD_NUMBER = "490"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "492"\n// Legacy regression token: WEBAPP_BUILD_NUMBER = "493"

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}