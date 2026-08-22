"use client";

import { useEffect } from "react";
import { WEBAPP_BUILD_NUMBER, WEBAPP_VERSION } from "@/lib/app-version";

export function PwaRegistration() {
  useEffect(() => {
    const standalone = window.matchMedia("(display-mode: standalone)").matches;
    const params = new URLSearchParams(window.location.search);
    if (standalone && params.get("source") === "pwa" && params.get("appVersion") !== WEBAPP_VERSION) {
      window.location.replace(`/?source=pwa&appVersion=${WEBAPP_VERSION}`);
      return;
    }
    if (!("serviceWorker" in navigator)) return;
    const reloadKey = `amar-pwa-reloaded-v${WEBAPP_VERSION}-b${WEBAPP_BUILD_NUMBER}`;
    const onControllerChange = () => {
      if (window.sessionStorage.getItem(reloadKey)) return;
      window.sessionStorage.setItem(reloadKey, "1");
      window.location.reload();
    };
    navigator.serviceWorker.addEventListener("controllerchange", onControllerChange);
    navigator.serviceWorker.register(`/sw.js?v=${WEBAPP_VERSION}&build=${WEBAPP_BUILD_NUMBER}`, { scope: "/", updateViaCache: "none" })
      .then((registration) => {
        registration.waiting?.postMessage({ type: "SKIP_WAITING" });
        return registration.update();
      })
      .catch(() => undefined);
    return () => navigator.serviceWorker.removeEventListener("controllerchange", onControllerChange);
  }, []);
  return null;
}
