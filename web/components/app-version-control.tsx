"use client";

import { useState } from "react";
import { WEBAPP_VERSION, WEBAPP_VERSION_LABEL } from "@/lib/app-version";

export function AppVersionControl() {
  const [label, setLabel] = useState(WEBAPP_VERSION_LABEL);
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

      if (availableVersion && availableVersion !== WEBAPP_VERSION) {
        setLabel(`Versie ${availableVersion} laden…`);
        window.location.reload();
        return;
      }

      setLabel(`Versie ${WEBAPP_VERSION} is actueel`);
    } catch {
      setLabel("Updatecontrole mislukt");
    } finally {
      setChecking(false);
      window.setTimeout(() => setLabel(WEBAPP_VERSION_LABEL), 3500);
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
