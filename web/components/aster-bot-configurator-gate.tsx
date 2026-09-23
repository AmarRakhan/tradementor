"use client";

import { Component, useEffect, useState, type ComponentType, type ReactNode } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

export type AsterConfiguratorProps = {
  snapshot: Record<string, unknown> | null;
  serverConfirmed: boolean;
  onConfirmed: (strategy2: Record<string, unknown>) => void;
  onChanged: () => void;
};

type GateProps = AsterConfiguratorProps & { legacy: ReactNode };
type GateState = "checking" | "stable" | "beta" | "failed";

class BetaBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: unknown) { console.error("[Botconfigurator V2] component failure", error); }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export function AsterBotConfiguratorGate(props: GateProps) {
  const [mode, setMode] = useState<GateState>("checking");
  const [BetaConfigurator, setBetaConfigurator] = useState<ComponentType<AsterConfiguratorProps> | null>(null);
  const [forceStable, setForceStable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    authenticatedRequest("/api/releases")
      .then((payload) => {
        if (cancelled) return;
        const features = payload && typeof payload.features === "object" ? payload.features as Record<string, any> : {};
        const feature = features.bot_configurator_v2;
        const beta = String(payload?.channel || "").toUpperCase() === "BETA" && feature?.enabled === true;
        if (!beta) { setMode("stable"); return; }
        setMode("beta");
        import("@/components/aster-bot-configurator-v2")
          .then((module) => {
            if (!cancelled) setBetaConfigurator(() => module.AsterBotConfiguratorV2);
          })
          .catch((error) => {
            console.error("[Botconfigurator V2] lazy load failed", error);
            if (!cancelled) setMode("failed");
          });
      })
      .catch((error) => {
        console.warn("[Botconfigurator V2] release check failed; using stable", error);
        if (!cancelled) setMode("stable");
      });
    return () => { cancelled = true; };
  }, []);

  if (forceStable || mode === "stable" || mode === "failed") return <>{props.legacy}</>;
  if (mode === "checking" || !BetaConfigurator) {
    return <article style={{border:"1px solid rgba(214,181,90,.28)",borderRadius:16,padding:18,background:"rgba(4,11,9,.92)",color:"#dce9e2"}}>
      <b>Botconfigurator controleren…</b>
      <p style={{margin:"6px 0 0",fontSize:12,color:"#87978f"}}>Releasekanaal wordt veilig bepaald. Stable trading blijft onaangeraakt.</p>
    </article>;
  }
  const betaProps: AsterConfiguratorProps = {
    snapshot: props.snapshot,
    serverConfirmed: props.serverConfirmed,
    onConfirmed: props.onConfirmed,
    onChanged: props.onChanged,
  };
  const fallback = <article style={{border:"1px solid rgba(255,120,146,.38)",borderRadius:16,padding:18,background:"rgba(32,8,13,.92)",color:"#f7e5e9"}}>
    <b>Botconfigurator BETA kon niet worden geladen.</b>
    <p style={{fontSize:12,color:"#c9aeb5"}}>De rest van de app blijft actief. Je kunt direct terug naar de stabiele instellingen.</p>
    <button type="button" onClick={() => setForceStable(true)} style={{minHeight:40,borderRadius:10,border:"1px solid rgba(214,181,90,.45)",background:"#101712",color:"#f0d784",padding:"0 14px"}}>Terug naar stabiele instellingen</button>
  </article>;
  return <BetaBoundary fallback={fallback}><BetaConfigurator {...betaProps} /></BetaBoundary>;
}
