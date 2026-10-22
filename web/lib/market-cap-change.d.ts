export type MarketCapChange = { changePercent: number; marketCapUsd: number | null; updatedAt: string | null };
export declare const CMC_PUBLIC_GLOBAL_METRICS_URL: string;
export declare const CMC_WEBSITE_GLOBAL_METRICS_URL: string;
export declare function parseMarketCapChange(payload: unknown): MarketCapChange | null;
export declare function formatMarketCapChange(value: number | null | undefined): string;
export declare function marketCapChangeTone(value: number | null | undefined): "positive" | "negative" | "neutral";
export declare function formatMarketCapUsd(value: number | null | undefined): string;
