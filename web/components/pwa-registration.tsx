"use client";

import { useEffect } from "react";
import { WEBAPP_BUILD_NUMBER, WEBAPP_VERSION } from "@/lib/app-version";

export function PwaRegistration() {
  const buildNumber = WEBAPP_BUILD_NUMBER;

  useEffect(() => {
    const standalone = window.matchMedia("(display-mode: standalone)").matches;
    const params = new URLSearchParams(window.location.search);
    const declaredVersion = params.get("appVersion");

    // A normal installed launch may omit appVersion on older manifests. Missing
    // metadata is never a reason to navigate during the auth splash. Only an
    // explicitly stale version marker may replace the URL once.
    if (standalone && params.get("source") === "pwa" && declaredVersion && declaredVersion !== WEBAPP_VERSION) {
      window.location.replace(`/?source=pwa&appVersion=${WEBAPP_VERSION}`);
      return;
    }

    if (!("serviceWorker" in navigator)) return;
    let disposed = false;

    const loadCanonicalBuild = async () => {
      try {
        const response = await fetch(`/?versionCheck=${Date.now()}`, { cache: "no-store" });
        const html = await response.text();
        if (disposed) return;
        const availableVersion = html.match(/data-webapp-version="([^"]+)"/)?.[1];
        const availableBuild = html.match(/data-webapp-build="([^"]+)"/)?.[1];
        const mismatch = (availableVersion && availableVersion !== WEBAPP_VERSION)
          || (availableBuild && availableBuild !== buildNumber);
        if (!mismatch) return;

        const targetVersion = availableVersion || WEBAPP_VERSION;
        const targetBuild = availableBuild || "latest";
        const guardKey = `amar-pwa-canonical-refresh-v${targetVersion}-b${targetBuild}`;
        if (window.sessionStorage.getItem(guardKey)) return;
        window.sessionStorage.setItem(guardKey, "1");

        const target = new URL("/", window.location.origin);
        if (standalone) {
          target.searchParams.set("source", "pwa");
          target.searchParams.set("appVersion", targetVersion);
        }
        target.searchParams.set("build", targetBuild);
        target.searchParams.set("refresh", String(Date.now()));
        window.location.replace(target.toString());
      } catch { /* keep the currently working app when the update check is offline */ }
    };

    // Do not reload on service-worker controllerchange. sw.js uses skipWaiting +
    // clients.claim, so forcing a reload here creates a startup reload loop on
    // Samsung/Android while Firebase is still restoring the session.
    const onVisibility = () => {
      if (document.visibilityState === "visible") void loadCanonicalBuild();
    };

    document.addEventListener("visibilitychange", onVisibility);
    navigator.serviceWorker.register(`/sw.js?v=${WEBAPP_VERSION}&build=${buildNumber}`, { scope: "/", updateViaCache: "none" })
      .then((registration) => {
        registration.waiting?.postMessage({ type: "SKIP_WAITING" });
        return registration.update();
      })
      // No canonical-build navigation during initial mount. A standalone
      // navigation already comes from the network; later checks happen on
      // visibility changes or the bounded 60-second timer below.
      .catch(() => undefined);

    const timer = window.setInterval(() => void loadCanonicalBuild(), 60_000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [buildNumber]);
  return null;
}
