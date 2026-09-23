"use client";

import { AsterStrategy2Maker } from "@/components/aster-strategy2-maker";
import { ReleaseCenter } from "@/components/release-center";

export default function AsterBotConfiguratorV2(props: {
  snapshot: Record<string, unknown> | null;
  serverConfirmed: boolean;
  onConfirmed: (strategy2: Record<string, unknown>) => void;
  onChanged: () => void;
}) {
  return (
    <div className="botconfig-v2-shell" data-visual-reference="file_000000003e34820a9d0c8dc22b84ac47">
      <AsterStrategy2Maker {...props} betaV2 />
      <ReleaseCenter />
    </div>
  );
}
