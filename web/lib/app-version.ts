export const WEBAPP_VERSION = "46";
// Build 395: Portfolio Koers visual parity pass with blue trading frame, real legacy equity history, boxed event markers and Snapshot detail lines.
export const WEBAPP_BUILD_NUMBER = "395";

export function webappVersionLabel(buildNumber: string = WEBAPP_BUILD_NUMBER) {
  return `Webapp versie ${WEBAPP_VERSION} · build ${buildNumber}`;
}
