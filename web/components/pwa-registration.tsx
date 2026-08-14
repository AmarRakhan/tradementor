"use client";

import { useEffect } from "react";

const pwaVersion = "31";

export function PwaRegistration() {
  useEffect(() => {
    const standalone = window.matchMedia("(display-mode: standalone)").matches;
    const params = new URLSearchParams(window.location.search);
    if (standalone && params.get("source") === "pwa" && params.get("appVersion") !== pwaVersion) {
      window.location.replace(`/?source=pwa&appVersion=${pwaVersion}`);
      return;
    }
    if (!("serviceWorker" in navigator)) return;
    const reloadKey = `amar-pwa-reloaded-v${pwaVersion}`;
    const onControllerChange = () => {
      if (window.sessionStorage.getItem(reloadKey)) return;
      window.sessionStorage.setItem(reloadKey, "1");
      window.location.reload();
    };
    navigator.serviceWorker.addEventListener("controllerchange", onControllerChange);
    navigator.serviceWorker.register(`/sw.js?v=${pwaVersion}`, { scope: "/", updateViaCache: "none" })
      .then((registration) => {
        registration.waiting?.postMessage({ type: "SKIP_WAITING" });
        return registration.update();
      })
      .catch(() => undefined);
    return () => navigator.serviceWorker.removeEventListener("controllerchange", onControllerChange);
  }, []);
  return null;
}
