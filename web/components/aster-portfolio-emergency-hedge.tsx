"use client";

/**
 * P0 2026-09-16 — Portfolio Noodhedge is globally disabled.
 *
 * Keep this exported component as an inert compatibility shim so existing
 * imports do not break while the feature is disabled. The backend runtime,
 * API routes and order guard are disabled separately.
 */
export function AsterPortfolioEmergencyHedge() {
  return null;
}
