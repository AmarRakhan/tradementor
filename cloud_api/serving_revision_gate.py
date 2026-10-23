"""Build 626: alleen de Cloud Run-revisie die het verkeer krijgt, doet bot-werk op de achtergrond.

Probleem (gezien 23-10-2026): na een release blijven instanties van de oude revisie nog
tientallen minuten draaien. Hun achtergrondtaken (periodieke tick, realtime-workers,
Spike, Auto Hedge, noodhedge) blijven dan met oude code handelen. Ook een nieuwe
kandidaat-revisie (nog zonder verkeer) start die taken al vóór de omschakeling.

Oplossing: elke instantie vraagt ``/health`` op de publieke service-URL. Dat verzoek komt
altijd bij de revisie met verkeer terecht, die haar eigen naam (``K_REVISION``) en commit
meldt. Komt dat niet overeen met deze instantie, dan staat deze instantie in STANDBY: geen
achtergrondwerk, geen orders. HTTP-verzoeken (app, scheduler) blijven gewoon werken;
die komen toch alleen bij de serverende revisie binnen.

Bij twijfel (URL onbereikbaar, onleesbaar antwoord) blijft het oude gedrag gelden: de
instantie werkt gewoon door (fail-open). Een kapotte controle mag de bot nooit stilleggen.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from typing import Any, Callable

DEFAULT_HEALTH_URL = "https://tradementor-api-cyyaq5otyq-ez.a.run.app/health"
CACHE_SECONDS = 20.0
# Zo lang blijft een eerder STANDBY-besluit geldig als de controle tijdelijk mislukt.
STANDBY_HOLD_ON_ERROR_SECONDS = 120.0
FETCH_TIMEOUT_SECONDS = 4.0


def _default_fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "tradementor-serving-gate"})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


class ServingGate:
    def __init__(self, *, revision: str | None = None, commit: str | None = None,
                 url: str | None = None, enabled: bool | None = None,
                 fetch: Callable[[str], dict[str, Any]] = _default_fetch,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.revision = (os.getenv("K_REVISION", "") if revision is None else revision).strip()
        self.commit = (os.getenv("TRADEMENTOR_SOURCE_COMMIT", "") if commit is None else commit).strip()
        self.url = url or os.getenv("SERVING_GATE_HEALTH_URL", DEFAULT_HEALTH_URL)
        if enabled is None:
            enabled = os.getenv("SERVING_GATE_ENABLED", "true").lower() == "true"
        # Buiten Cloud Run (tests, lokaal) is er geen revisienaam: altijd actief.
        self.enabled = bool(enabled) and bool(self.revision)
        self._fetch = fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._checked_at = float("-inf")
        self._serving = True
        self._last_standby_at = float("-inf")
        self._reason = "not-checked"

    def _decide(self, payload: dict[str, Any]) -> tuple[bool | None, str]:
        serving_revision = str(payload.get("revision") or "").strip()
        if serving_revision:
            return serving_revision == self.revision, f"serving={serving_revision}"
        # Serverende revisie is nog oude code zonder "revision": vergelijk de commit.
        serving_commit = str(payload.get("sourceCommit") or "").strip()
        if serving_commit and self.commit:
            if serving_commit != self.commit:
                return False, f"serving-commit={serving_commit[:8]}"
            return True, "same-commit"
        return None, "health-without-identity"

    def is_serving(self) -> bool:
        if not self.enabled:
            return True
        now = self._clock()
        with self._lock:
            if now - self._checked_at < CACHE_SECONDS:
                return self._serving
            self._checked_at = now
            previous = self._serving
        try:
            decision, reason = self._decide(self._fetch(self.url))
        except Exception as exc:  # netwerk/JSON: twijfel
            decision, reason = None, f"check-failed:{type(exc).__name__}"
        with self._lock:
            if decision is None:
                # Twijfel: een recent STANDBY-besluit even aanhouden, anders doorwerken.
                serving = not (not previous and now - self._last_standby_at < STANDBY_HOLD_ON_ERROR_SECONDS)
            else:
                serving = decision
            if not serving:
                self._last_standby_at = now
            self._serving = serving
            self._reason = reason
        if serving != previous:
            print(f"SERVING_GATE {'ACTIVE' if serving else 'STANDBY'} revision={self.revision} reason={reason}", flush=True)
        return serving

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"enabled": self.enabled, "revision": self.revision or None,
                    "serving": self._serving, "reason": self._reason}


GATE = ServingGate()


def is_serving() -> bool:
    try:
        return GATE.is_serving()
    except Exception:
        return True
