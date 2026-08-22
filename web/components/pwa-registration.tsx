"use client";

import { useEffect } from "react";
import { WEBAPP_VERSION } from "@/lib/app-version";

export function PwaRegistration({ buildNumber }: { buildNumber: string }) {
  useEffect(() => {
    const standalone = window.matchMedia("(display-mode: standalone)").matches;
    const params = new URLSearchParams(window.location.search);
    if (standalone && params.get("source") === "pwa" && params.get("appVersion") !== WEBAPP_VERSION) {
      window.location.replace(`/?source=pwa&appVersion=${WEBAPP_VERSION}`);
      return;
    }
    if (!("serviceWorker" in navigator)) return;
    let disposed = false;
    const reloadKey = `amar-pwa-reloaded-v${WEBAPP_VERSION}-b${buildNumber}`;
    const loadCanonicalBuild = async () => {
      try {
        const response = await fetch(`/?versionCheck=${Date.now()}`, { cache: "no-store" });
        const html = await response.text();
        if (disposed) return;
        const availableVersion = html.match(/data-webapp-version="([^"]+)"/)?.[1];
        const availableBuild = html.match(/data-webapp-build="([^"]+)"/)?.[1];
        if ((availableVersion && availableVersion !== WEBAPP_VERSION) || (availableBuild && availableBuild !== buildNumber)) {
          const target = new URL("/", window.location.origin);
          if (standalone) { target.searchParams.set("source", "pwa"); target.searchParams.set("appVersion", availableVersion || WEBAPP_VERSION); }
          target.searchParams.set("build", availableBuild || "latest");
          target.searchParams.set("refresh", String(Date.now()));
          window.location.replace(target.toString());
        }
      } catch { /* keep the currently working app when the update check is offline */ }
    };
    const onControllerChange = () => {
      if (window.sessionStorage.getItem(reloadKey)) return;
      window.sessionStorage.setItem(reloadKey, "1");
      window.location.reload();
    };
    const onVisibility = () => { if (document.visibilityState === "visible") void loadCanonicalBuild(); };
    navigator.serviceWorker.addEventListener("controllerchange", onControllerChange);
    document.addEventListener("visibilitychange", onVisibility);
    navigator.serviceWorker.register(`/sw.js?v=${WEBAPP_VERSION}&build=${buildNumber}`, { scope: "/", updateViaCache: "none" })
      .then((registration) => { registration.waiting?.postMessage({ type: "SKIP_WAITING" }); return registration.update(); })
      .then(() => loadCanonicalBuild())
      .catch(() => undefined);
    const timer = window.setInterval(() => void loadCanonicalBuild(), 60_000);
    return () => { disposed = true; window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisibility); navigator.serviceWorker.removeEventListener("controllerchange", onControllerChange); };
  }, []);
  return null;
}
