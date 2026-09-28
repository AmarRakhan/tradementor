import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { AsterBotConfiguratorV3 } from "../../components/aster-bot-configurator-v3";

const settings = {
  engine: "multi_bb_v1",
  strategyKind: "multi_bb_v1",
  name: "Aster Multi DCA",
  universeTopN: 350,
  maximumPositions: 130,
  longSlots: 69,
  shortSlots: 30,
  minimumLeverage: 20,
  maximumLeverage: 50,
  zoneSoldiersEnabled: true,
  zoneSoldiersOptInVersion: 1,
  zoneBaseLongSoldiers: 3,
  zoneBaseShortSoldiers: 3,
  entrySizingMode: "margin",
  entryMarginUsd: 0.40,
  entryMarginLongUsd: 0.40,
  entryMarginShortUsd: 0.30,
  longDcaMarginUsd: 0.17,
  shortDcaMarginUsd: 0.25,
  longDcaDistance: 0.001,
  shortDcaDistance: 0.0025,
  maxDcaLong: 10,
  maxDcaShort: 15,
  takeProfitMode: "PORTFOLIO",
  takeProfitEnabled: true,
  portfolioTpValue: 15,
  portfolioTpInputMode: "USD",
  portfolioTpBaseMode: "CYCLE_START",
  resetSeatsAfterPortfolioTp: true,
  longTakeProfitValue: 0.015,
  shortTakeProfitValue: 0.015,
  bollingerEntryFilter15mEnabled: true,
  directionalBollingerEnabled: true,
  bollingerLongTimeframe: "15m",
  bollingerShortTimeframe: "15m",
  exposureRefillEnabled: true,
  exposureRefillLongTimeframe: "1m",
  exposureRefillShortTimeframe: "1m",
  exposureRefillTriggerPercent: 20,
  exposureRefillReleasePercent: 8,
  shortRequiresLongEnabled: false,
  stopLossEnabled: false,
  smartRescueEnabled: false,
};

const release = {
  channel: "BETA" as const,
  features: {
    bot_configurator_v2: { enabled: true, beta: true, stable: false, status: "TESTEN" },
    zone_soldiers: { enabled: true, beta: true, stable: false, status: "TESTEN" },
    directional_bollinger: { enabled: true, beta: true, stable: false, status: "TESTEN" },
    exposure_refill: { enabled: true, beta: true, stable: false, status: "TESTEN" },
    margin_summary: { enabled: true, beta: true, stable: false, status: "TESTEN" },
    price_zones: { enabled: false, beta: false, stable: false, status: "IN_BOUW" },
  },
};

function Fixture() {
  const [snapshot, setSnapshot] = useState<Record<string, unknown>>({
    equity: 341.51,
    availableBalance: 238.71,
    strategy2: {
      enabled: true,
      settings,
      zoneSoldierLifecycle: "ACTIVE",
      multiBbCycle: { cycleId: "visual-cycle", cycleStartEquity: 104.23, cycleStartLongSlots: 3, cycleStartShortSlots: 3, cycleStartMaximumPositions: 6, cycleStatus: "RUNNING" },
      multiBbReport: { activeLong: 60, activeShort: 30, netExposureNotional: 0, exposureImbalancePercent: 0 },
      priceZoneSeats: { activeZone: 2, seatModel: { activeZone: 2, occupiedLongActiveZone: 2, occupiedShortActiveZone: 2, openFromOldZones: 14, strategyOpenLong: 30, strategyOpenShort: 25, strategyOpenTotal: 55 } },
    },
  });

  return <main className="qa-shell">
    <AsterBotConfiguratorV3
      snapshot={snapshot}
      serverConfirmed
      release={release}
      onConfirmed={(strategy2) => setSnapshot((current) => ({ ...current, strategy2 }))}
      onChanged={() => undefined}
    />
  </main>;
}

createRoot(document.getElementById("root")!).render(<Fixture />);
