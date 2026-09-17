export const WEBAPP_VERSION = "46";
export const AAVANSH_TRADING_VERSION = "1";
export function webappVersionLabel(buildNumber: string) {
  return `Aavansh Trading v${AAVANSH_TRADING_VERSION} · Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
