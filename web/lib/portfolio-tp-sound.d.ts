export type LatestPortfolioTp = {
  cycleId: string;
  phase?: "EXECUTING" | "COMPLETED" | string;
  occurredAtMs: number;
  cycleProfitUsd?: number | null;
} | null | undefined;
export type PortfolioTpSoundDecision = { play: boolean; store: string | null };
export const PORTFOLIO_TP_SOUND_URL: string;
export const PORTFOLIO_TP_SOUND_ENABLED_KEY: string;
export const PORTFOLIO_TP_SOUND_LAST_KEY: string;
export const PORTFOLIO_TP_SOUND_MAX_AGE_MS: number;
export function decidePortfolioTpSound(input: {
  latest: LatestPortfolioTp; lastCycleId: string | null; enabled: boolean; nowMs: number;
}): PortfolioTpSoundDecision;
export function isPortfolioTpSoundEnabled(): boolean;
export function setPortfolioTpSoundEnabled(enabled: boolean): void;
export function installPortfolioTpSoundUnlock(): () => void;
export function playPortfolioTpSound(): Promise<boolean>;
export function handleLatestPortfolioTp(latest: LatestPortfolioTp, nowMs?: number): PortfolioTpSoundDecision;
export const PORTFOLIO_TP_PUSH_MESSAGE: string;
export function portfolioTpFromPushMessage(data: unknown, nowMs: number): LatestPortfolioTp;
export function listenForPortfolioTpPush(): () => void;
