export const WEBAPP_VERSION = "46";
// Build 421: account-only Strategy Status Command Center test for the hard owner beta account; no general rollout.
export const WEBAPP_BUILD_NUMBER = "421";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
