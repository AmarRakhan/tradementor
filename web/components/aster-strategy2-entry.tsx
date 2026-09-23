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

const BetaConfigurator = lazy(() => import("@/components/aster-bot-configurator-v2").then((module) => ({ default: module.AsterBotConfiguratorV2 })));

class BetaBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: unknown) { console.error("[BotConfiguratorV2] isolated beta failure", error); }
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

  const betaEnabled = release?.features?.bot_configurator_v2?.enabled === true;
  if (!betaEnabled) return <AsterStrategy2Maker {...props} />;

  const fallback = (
    <article className="strategy-card" style={{ border: "1px solid rgba(214,181,90,.45)", borderRadius: 16, padding: 14 }}>
      <span className="kicker">BETA · alleen zichtbaar voor jou</span>
      <h2>Botconfigurator V2 kon niet worden geladen</h2>
      <p>De fout is geïsoleerd. De rest van de app en de stabiele configurator blijven beschikbaar.</p>
      <AsterStrategy2Maker {...props} />
    </article>
  );

  return (
    <BetaBoundary fallback={fallback}>
      <Suspense fallback={<div className="strategy-card"><span className="kicker">BETA</span><p>Botconfigurator V2 laden…</p></div>}>
        <BetaConfigurator {...props} release={release ?? { channel: "BETA", features: {} }} />
      </Suspense>
    </BetaBoundary>
  );
}
