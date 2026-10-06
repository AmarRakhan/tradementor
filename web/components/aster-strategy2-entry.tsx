"use client";

import { AsterStrategy2Maker } from "@/components/aster-strategy2-maker";

type Props = {
  snapshot: Record<string, unknown> | null;
  serverConfirmed: boolean;
  onConfirmed: (strategy2: Record<string, unknown>) => void;
  onChanged: () => void;
};

export function AsterStrategy2Entry(props: Props) {
  return <AsterStrategy2Maker {...props} />;
}
