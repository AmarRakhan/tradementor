"use client";

export type OptionalNavigationTab =
  | "hyperliquid"
  | "markets"
  | "sniper"
  | "news"
  | "friends"
  | "journey";

export type NavigationPreferences = Record<OptionalNavigationTab, boolean>;

export const DEFAULT_NAVIGATION_PREFERENCES: NavigationPreferences = {
  hyperliquid: true,
  markets: true,
  sniper: true,
  news: true,
  friends: true,
  journey: true,
};

export const MOBILE_NAVIGATION_ORDER = [
  "home",
  "markets",
  "hyperliquid",
  "aster",
  "sniper",
  "news",
  "friends",
  "journey",
  "wallet",
] as const;

export const NAVIGATION_PREFERENCES_EVENT = "tradementor:navigation-visibility-change";

const LEGACY_HYPERLIQUID_KEY = "tradementor.navigation.hyperliquid.visible";
const STORAGE_PREFIX = "tradementor.navigation.visible.v2.";

function isBoolean(value: unknown): value is boolean {
  return value === true || value === false;
}

function storageKey(uid: string) {
  return `${STORAGE_PREFIX}${encodeURIComponent(uid)}`;
}

export function normalizeNavigationPreferences(
  value: unknown,
  fallback: NavigationPreferences = DEFAULT_NAVIGATION_PREFERENCES,
): NavigationPreferences {
  const source = value && typeof value === "object" ? value as Record<string, unknown> : {};
  return {
    hyperliquid: isBoolean(source.hyperliquid) ? source.hyperliquid : fallback.hyperliquid,
    markets: isBoolean(source.markets) ? source.markets : fallback.markets,
    sniper: isBoolean(source.sniper) ? source.sniper : fallback.sniper,
    news: isBoolean(source.news) ? source.news : fallback.news,
    friends: isBoolean(source.friends) ? source.friends : fallback.friends,
    journey: isBoolean(source.journey) ? source.journey : fallback.journey,
  };
}

export function loadNavigationPreferences(uid?: string | null): NavigationPreferences {
  if (typeof window === "undefined") return { ...DEFAULT_NAVIGATION_PREFERENCES };
  if (uid) {
    try {
      const stored = window.localStorage.getItem(storageKey(uid));
      if (stored) return normalizeNavigationPreferences(JSON.parse(stored));
    } catch {
      // A damaged local UI preference must never affect trading state.
    }
  }
  const fallback = { ...DEFAULT_NAVIGATION_PREFERENCES };
  try {
    const legacyHyperliquid = window.localStorage.getItem(LEGACY_HYPERLIQUID_KEY);
    if (legacyHyperliquid === "false") fallback.hyperliquid = false;
    else if (legacyHyperliquid === "true") fallback.hyperliquid = true;
  } catch {
    // Legacy preference is best-effort only.
  }
  return fallback;
}

export function saveNavigationPreferences(uid: string | null | undefined, value: NavigationPreferences) {
  if (typeof window === "undefined") return;
  const normalized = normalizeNavigationPreferences(value);
  try {
    if (uid) window.localStorage.setItem(storageKey(uid), JSON.stringify(normalized));
    // Keep the pre-v2 Hyperliquid preference compatible during the migration.
    window.localStorage.setItem(LEGACY_HYPERLIQUID_KEY, String(normalized.hyperliquid));
  } catch {
    // Cloud remains the durable source of truth when localStorage is unavailable.
  }
  window.dispatchEvent(new CustomEvent(NAVIGATION_PREFERENCES_EVENT, { detail: normalized }));
}

export function optionalNavigationTabVisible(tab: OptionalNavigationTab, uid?: string | null) {
  return loadNavigationPreferences(uid)[tab];
}

export function mobileNavigationDestinationVisible(destination: string, uid?: string | null) {
  if (destination === "home" || destination === "aster" || destination === "wallet") return true;
  if (
    destination === "hyperliquid" ||
    destination === "markets" ||
    destination === "sniper" ||
    destination === "news" ||
    destination === "friends" ||
    destination === "journey"
  ) {
    return optionalNavigationTabVisible(destination, uid);
  }
  return false;
}
