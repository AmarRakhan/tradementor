"use client";

import { useEffect } from "react";
import { WEBAPP_BUILD_NUMBER, WEBAPP_VERSION } from "@/lib/app-version";

export function PwaRegistration() {
  const buildNumber = WEBAPP_BUILD_NUMBER;

  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    let disposed = false;
    let registration: ServiceWorkerRegistration | undefined;

    const updateWorker = () => {
      if (disposed || !registration) return;
      void registration.update().catch(() => undefined);
    };

    navigator.serviceWorker.register(`/sw.js?v=${WEBAPP_VERSION}&build=${buildNumber}`, {
      scope: "/",
      updateViaCache: "none",
    }).then((value) => {
      registration = value;
      // Registration itself is sufficient on startup. Do not force waiting
      // workers to activate and never navigate/reload while Firebase restores
      // the signed-in session.
    }).catch(() => undefined);

    const onVisibility = () => {
      if (document.visibilityState === "visible") updateWorker();
    };
    document.addEventListener("visibilitychange", onVisibility);

    // Background update discovery only. A discovered worker waits safely until
    // the app is next opened or the user explicitly requests an update.
    const timer = window.setInterval(updateWorker, 5 * 60_000);

    return () => {
      disposed = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [buildNumber]);

  return null;
}
