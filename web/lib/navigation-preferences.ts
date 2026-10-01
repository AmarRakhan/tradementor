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
const LEGACY_HYPERLIQUID_OWNER_KEY = "tradementor.navigation.hyperliquid.visible.owner.v2";
const STORAGE_PREFIX = "tradementor.navigation.visible.v2.";
const PENDING_PREFIX = "tradementor.navigation.pending.v2.";

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
    if (uid && (legacyHyperliquid === "false" || legacyHyperliquid === "true")) {
      const owner = window.localStorage.getItem(LEGACY_HYPERLIQUID_OWNER_KEY);
      if (!owner) window.localStorage.setItem(LEGACY_HYPERLIQUID_OWNER_KEY, uid);
      if (!owner || owner === uid) fallback.hyperliquid = legacyHyperliquid === "true";
    }
  } catch {
    // Legacy preference is best-effort only and may only be claimed by one account.
  }
  return fallback;
}

export function saveNavigationPreferences(uid: string | null | undefined, value: NavigationPreferences) {
  if (typeof window === "undefined") return;
  const normalized = normalizeNavigationPreferences(value);
  try {
    if (uid) window.localStorage.setItem(storageKey(uid), JSON.stringify(normalized));
    // Keep the pre-v2 Hyperliquid preference compatible without leaking it between accounts.
    const legacyOwner = window.localStorage.getItem(LEGACY_HYPERLIQUID_OWNER_KEY);
    if (!legacyOwner && uid) window.localStorage.setItem(LEGACY_HYPERLIQUID_OWNER_KEY, uid);
    if (!uid || !legacyOwner || legacyOwner === uid) {
      window.localStorage.setItem(LEGACY_HYPERLIQUID_KEY, String(normalized.hyperliquid));
    }
  } catch {
    // Cloud remains the durable source of truth when localStorage is unavailable.
  }
  window.dispatchEvent(new CustomEvent(NAVIGATION_PREFERENCES_EVENT, { detail: normalized }));
}

export function navigationPreferencesPending(uid?: string | null) {
  if (typeof window === "undefined" || !uid) return false;
  try {
    return window.localStorage.getItem(`${PENDING_PREFIX}${encodeURIComponent(uid)}`) === "true";
  } catch {
    return false;
  }
}

export function markNavigationPreferencesPending(uid: string | null | undefined, pending: boolean) {
  if (typeof window === "undefined" || !uid) return;
  try {
    const key = `${PENDING_PREFIX}${encodeURIComponent(uid)}`;
    if (pending) window.localStorage.setItem(key, "true");
    else window.localStorage.removeItem(key);
  } catch {
    // A blocked local pending flag must never affect the running trading app.
  }
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
