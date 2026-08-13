"use client";

import { useEffect, useState } from "react";
import { DEMO_MODE_KEY, demoModeEnabled } from "@/lib/demo-data";

export function DemoModeControl() {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => setEnabled(demoModeEnabled()), []);

  const toggle = () => {
    const next = !enabled;
    window.localStorage.setItem(DEMO_MODE_KEY, String(next));
    window.location.reload();
  };

  return <button className={`demo-mode-control ${enabled ? "enabled" : ""}`} type="button" aria-pressed={enabled} onClick={toggle}>
    <i />{enabled ? "DEMO ACTIEF · ALLEEN LEZEN" : "TEST MET DEMODATA"}
  </button>;
}
