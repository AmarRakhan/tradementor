"use client";

import { useState } from "react";
import { WEBAPP_VERSION, webappVersionLabel } from "@/lib/app-version";

export function AppVersionControl({ buildNumber }: { buildNumber: string }) {
  const versionLabel = webappVersionLabel(buildNumber);
  const [label, setLabel] = useState(versionLabel);
  const [checking, setChecking] = useState(false);

  async function checkForUpdate() {
    if (checking) return;
    setChecking(true);
    setLabel("Update controleren…");

    try {
      const registration = "serviceWorker" in navigator
        ? await navigator.serviceWorker.getRegistration("/")
        : undefined;
      await registration?.update();

      if (registration?.waiting) {
        setLabel("Update installeren…");
        registration.waiting.postMessage({ type: "SKIP_WAITING" });
        return;
      }

      const response = await fetch(`/?versionCheck=${Date.now()}`, { cache: "no-store" });
      const html = await response.text();
      const availableVersion = html.match(/data-webapp-version="([^"]+)"/)?.[1];
      const availableBuild = html.match(/data-webapp-build="([^"]+)"/)?.[1];

      if ((availableVersion && availableVersion !== WEBAPP_VERSION) ||
          (availableBuild && availableBuild !== buildNumber)) {
        setLabel(`Versie ${availableVersion || WEBAPP_VERSION} · build ${availableBuild || "?"} laden…`);
        window.location.reload();
        return;
      }

      setLabel(`Versie ${WEBAPP_VERSION} · build ${buildNumber} is actueel`);
    } catch {
      setLabel("Updatecontrole mislukt");
    } finally {
      setChecking(false);
      window.setTimeout(() => setLabel(versionLabel), 3500);
    }
  }

  return (
    <button
      type="button"
      className="webapp-version-badge"
      onClick={checkForUpdate}
      disabled={checking}
      title="Controleer of een nieuwere webappversie beschikbaar is"
      aria-live="polite"
    >
      {label}
    </button>
  );
}
