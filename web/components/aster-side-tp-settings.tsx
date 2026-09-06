"use client";

/**
 * Retired compatibility mount.
 *
 * LONG/SHORT entry, DCA and Take Profit settings now live directly inside
 * AsterStrategy2Maker. Keeping this export avoids breaking older page imports
 * while guaranteeing that no popup/submenu is mounted.
 */
export function AsterSideTpSettings() {
  return null;
}
