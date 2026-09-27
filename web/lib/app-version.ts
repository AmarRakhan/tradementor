export const WEBAPP_VERSION = "46";
// Build 453: Auto Hedge-statuslabels koppelen exact per munt en tonen HEDGED zonder AH-prefix.
export const WEBAPP_BUILD_NUMBER = "453";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
