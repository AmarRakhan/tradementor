"use client";

import { Component, lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { AsterStrategy2Maker } from "@/components/aster-strategy2-maker";

const BetaConfigurator = lazy(() => import("@/components/aster-bot-configurator-v2"));

type Props = {
  snapshot: Record<string, unknown> | null;
  serverConfirmed: boolean;
  onConfirmed: (strategy2: Record<string, unknown>) => void;
  onChanged: () => void;
};

type ReleaseSnapshot = {
  channel?: string;
  features?: Record<string, { enabled?: boolean }>;
};

class BetaBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: unknown) { console.error("[Botconfigurator V2]", error); }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export function AsterStrategy2ConfiguratorGate(props: Props) {
  const [release, setRelease] = useState<ReleaseSnapshot | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    authenticatedRequest("/api/releases", { cache: "no-store" })
      .then((value) => { if (!cancelled) setRelease(value as ReleaseSnapshot); })
      .catch(() => { if (!cancelled) setRelease({ channel: "STABLE", features: {} }); });
    return () => { cancelled = true; };
  }, [retryKey]);

  const enabled = release?.features?.bot_configurator_v2?.enabled === true;
  if (!enabled) return <AsterStrategy2Maker {...props} />;

  return (
    <BetaBoundary
      key={retryKey}
      fallback={
        <section className="botconfig-v2-fallback">
          <span>BETA</span>
          <h3>Botconfigurator V2 kon niet worden geladen</h3>
          <p>De rest van de app blijft actief. Je kunt opnieuw proberen of tijdelijk de stabiele instellingen gebruiken.</p>
          <div><button type="button" onClick={() => setRetryKey((v) => v + 1)}>Opnieuw proberen</button><AsterStrategy2Maker {...props} /></div>
        </section>
      }
    >
      <Suspense fallback={<section className="botconfig-v2-loading">Botconfigurator V2 laden…</section>}>
        <BetaConfigurator {...props} />
      </Suspense>
    </BetaBoundary>
  );
}
