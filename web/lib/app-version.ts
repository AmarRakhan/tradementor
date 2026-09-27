export const WEBAPP_VERSION = "46";
// Build 447: Portfolio Koers Graph 3.1 houdt de actuele koers altijd tussen S1/R1 en voorkomt annotatie-overlap.
export const WEBAPP_BUILD_NUMBER = "447";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
