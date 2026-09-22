export const WEBAPP_VERSION = "46";
// Build 394: Portfolio Koers current equity is locked to the same visible Portfolio Snapshot truth; backend remains historical/fallback only.
export const WEBAPP_BUILD_NUMBER = "394";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
