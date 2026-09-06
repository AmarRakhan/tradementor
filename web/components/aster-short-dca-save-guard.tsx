"use client";

import { useEffect } from "react";

/**
 * Keeps the LONG/SHORT settings footer reachable on mobile keyboards.
 * The existing settings component owns all values and API writes; this helper
 * only makes its save controls sticky so a changed SHORT DCA cannot be lost by
 * closing the sheet before the save button becomes reachable.
 */
export function AsterShortDcaSaveGuard() {
  useEffect(() => {
    const apply = () => {
      const dialogs = Array.from(document.querySelectorAll('[role="dialog"]'));
      for (const dialog of dialogs) {
        const heading = dialog.textContent || "";
        if (!heading.includes("LONG / SHORT") || !heading.includes("DCA")) continue;
        const footer = dialog.querySelector("footer") as HTMLElement | null;
        if (!footer) continue;
        Object.assign(footer.style, {
          position: "sticky",
          bottom: "0",
          zIndex: "4",
          padding: "10px 0 calc(8px + env(safe-area-inset-bottom))",
          background: "linear-gradient(180deg,rgba(2,5,4,.72),#020504 34%)",
          backdropFilter: "blur(8px)",
        });
      }
    };
    apply();
    const observer = new MutationObserver(apply);
    observer.observe(document.body, { subtree: true, childList: true });
    return () => observer.disconnect();
  }, []);
  return null;
}
