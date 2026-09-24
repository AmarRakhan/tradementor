export const WEBAPP_VERSION = "46";
// Build 412: retire the obsolete 100-seat Portfolio Koers ceiling and align capacity with the 400-seat platform guard.
// Build 412 also turns raw network failures into an explicit no-change message; release packaging includes the clean regression source.
export const WEBAPP_BUILD_NUMBER = "412";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
