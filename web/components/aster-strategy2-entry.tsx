"use client";

import { Component, Suspense, lazy, useEffect, useState, type ReactNode } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { AsterStrategy2Maker } from "@/components/aster-strategy2-maker";

type Props = {
  snapshot: Record<string, unknown> | null;
  serverConfirmed: boolean;
  onConfirmed: (strategy2: Record<string, unknown>) => void;
  onChanged: () => void;
};

type ReleaseState = {
  channel?: "BETA" | "STABLE";
  features?: Record<string, { enabled?: boolean }>;
};

const BetaConfiguratorV2 = lazy(() => import("@/components/aster-bot-configurator-v2").then((module) => ({ default: module.AsterBotConfiguratorV2 })));
const BetaConfiguratorV3 = lazy(() => import("@/components/aster-bot-configurator-v3").then((module) => ({ default: module.AsterBotConfiguratorV3 })));

class BetaBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: unknown) { console.error("[BotConfigurator] isolated configurator failure", error); }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export function AsterStrategy2Entry(props: Props) {
  const [release, setRelease] = useState<ReleaseState | null>(null);

  useEffect(() => {
    let cancelled = false;
    authenticatedRequest("/api/releases/me", { cache: "no-store" })
      .then((value) => { if (!cancelled) setRelease(value as ReleaseState); })
      .catch(() => { if (!cancelled) setRelease({ channel: "STABLE", features: {} }); });
    return () => { cancelled = true; };
  }, []);

  const releaseEnabled = release?.features?.bot_configurator_v2?.enabled === true;
  if (!releaseEnabled) return <AsterStrategy2Maker {...props} />;

  const betaV3Enabled = release?.channel === "BETA";
  const label = betaV3Enabled ? "BOTCONFIGURATOR 3.0" : "BOTCONFIGURATOR V2";
  const fallback = (
    <article className="strategy-card" style={{ border: "1px solid rgba(214,181,90,.45)", borderRadius: 16, padding: 14 }}>
      <span className="kicker">{label}</span>
      <h2>{label} kon niet worden geladen</h2>
      <p>De fout is geïsoleerd. De rest van de app en de stabiele configurator blijven beschikbaar.</p>
      <AsterStrategy2Maker {...props} />
    </article>
  );

  return (
    <BetaBoundary fallback={fallback}>
      <Suspense fallback={<div className="strategy-card"><span className="kicker">{label}</span><p>{label} laden…</p></div>}>
        {betaV3Enabled
          ? <BetaConfiguratorV3 {...props} release={release} />
          : <BetaConfiguratorV2 {...props} release={release} />}
      </Suspense>
    </BetaBoundary>
  );
}
