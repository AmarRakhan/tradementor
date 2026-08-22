"use client";

import { useEffect, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type Event = {
  eventId: string;
  lastDetectedAt?: string;
  errorCode?: string;
  category?: string;
  component?: string;
  recoveryAction?: string;
  status?: string;
};

type Health = {
  status: string;
  lastSuccessfulScan?: string;
  yourBot: {
    found: number;
    autoRecovered: number;
    softwareFixed: number;
    open: number;
    safetyHolds: number;
  };
  platform: {
    activeBots: number;
    trackedBots: number;
    autoRecovered: number;
    openIncidents: number;
  };
  incidents: Event[];
};

const when = (value?: string) => value
  ? new Date(value).toLocaleString("nl-NL", { dateStyle: "short", timeStyle: "medium" })
  : "Nog niet bewezen";

function statusClass(status: string) {
  if (status === "OK") return "ok";
  if (status === "RECOVERED") return "recovered";
  return "action-required";
}

export function BotHealthCard() {
  const [data, setData] = useState<Health | null>(null);
  const [open, setOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () => authenticatedRequest("/api/bot-health")
      .then((value) => { if (alive) setData(value as Health); })
      .catch(() => {});
    load();
    const id = window.setInterval(load, 12000);
    return () => { alive = false; window.clearInterval(id); };
  }, []);

  const tone = data ? statusClass(data.status) : "loading";

  return (
    <>
      <style>{compactHealthStyles}</style>
      <section className={`bot-health-card compact-health ${tone}`}>
        <button
          type="button"
          className="bot-health-summary"
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          <span className="bot-health-dot" aria-label={data?.status === "OK" ? "Status goed" : data?.status === "RECOVERED" ? "Probleem hersteld" : "Actie nodig"} />
          <span className="bot-health-title">BOT HEALTH</span>
          <span className="bot-health-chevron" aria-hidden="true">{open ? "▴" : "▾"}</span>
        </button>

        {open && (
          <div className="bot-health-expanded">
            {!data ? (
              <p>Healthinformatie wordt geladen…</p>
            ) : (
              <>
                <div className="bot-health-columns">
                  <div>
                    <h4>Jouw bot</h4>
                    <span>Laatste succesvolle scan <b>{when(data.lastSuccessfulScan)}</b></span>
                    <span>Problemen gevonden vandaag <b>{data.yourBot.found}</b></span>
                    <span>Automatisch hersteld vandaag <b>{data.yourBot.autoRecovered}</b></span>
                    <span>Softwarefixes vandaag <b>{data.yourBot.softwareFixed}</b></span>
                    <span>Open problemen <b>{data.yourBot.open}</b></span>
                    <span>Safety holds <b>{data.yourBot.safetyHolds}</b></span>
                  </div>
                  <div>
                    <h4>Platform</h4>
                    <span>Actieve bots <b>{data.platform.activeBots}</b></span>
                    <span>Gevolgde bots <b>{data.platform.trackedBots}</b></span>
                    <span>Automatisch hersteld vandaag <b>{data.platform.autoRecovered}</b></span>
                    <span>Open incidenten <b>{data.platform.openIncidents}</b></span>
                  </div>
                </div>

                <button type="button" className="bot-health-report-button" onClick={() => setReportOpen((current) => !current)}>
                  {reportOpen ? "Rapport sluiten" : "Bekijk rapport"}
                </button>

                {reportOpen && (
                  <div className="bot-health-report">
                    {data.incidents.length ? data.incidents.map((event) => (
                      <p key={event.eventId}>
                        <time>{when(event.lastDetectedAt)}</time> · <b>{event.errorCode || event.category}</b> · {event.component} · {event.recoveryAction || "geen automatische actie"} · <strong>{event.status === "SOFTWARE_FIXED" ? "✓ softwarefix" : event.status === "AUTO_RECOVERED" ? "✓ automatisch hersteld" : event.status}</strong>
                      </p>
                    )) : <p>Vandaag zijn geen reliability-incidenten geregistreerd.</p>}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </section>
    </>
  );
}

const compactHealthStyles = `
  .bot-health-card.compact-health {
    padding: 0 !important;
    min-height: 0 !important;
    overflow: hidden;
    border-radius: 14px !important;
  }
  .bot-health-card.compact-health > .bot-health-summary {
    width: 100%;
    min-height: 42px;
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 9px;
    padding: 8px 12px;
    border: 0;
    background: transparent;
    text-align: left;
    cursor: pointer;
  }
  .bot-health-card.compact-health .bot-health-dot {
    width: 12px;
    height: 12px;
    border-radius: 999px;
    background: #d29a42;
    box-shadow: 0 0 9px rgba(210,154,66,.45);
  }
  .bot-health-card.compact-health.ok .bot-health-dot {
    background: #35d98a;
    box-shadow: 0 0 10px rgba(53,217,138,.55);
  }
  .bot-health-card.compact-health.recovered .bot-health-dot {
    background: #e6a23c;
    box-shadow: 0 0 10px rgba(230,162,60,.55);
  }
  .bot-health-card.compact-health.action-required .bot-health-dot {
    background: #ff5c70;
    box-shadow: 0 0 10px rgba(255,92,112,.55);
  }
  .bot-health-card.compact-health .bot-health-title {
    font-size: 10px;
    font-weight: 800;
    letter-spacing: .09em;
    color: #c8d0dc;
  }
  .bot-health-card.compact-health .bot-health-chevron {
    color: #7f8a9b;
    font-size: 12px;
  }
  .bot-health-card.compact-health .bot-health-expanded {
    padding: 4px 12px 13px;
  }
  .bot-health-card.compact-health .bot-health-expanded > p {
    margin: 4px 0 8px;
    font-size: 10px;
    color: #8f9baa;
  }
  .bot-health-card.compact-health .bot-health-columns {
    margin-top: 0 !important;
  }
  .bot-health-card.compact-health .bot-health-report-button {
    margin-top: 10px;
  }
  @media (max-width: 600px) {
    .bot-health-card.compact-health > .bot-health-summary {
      min-height: 40px;
      padding: 7px 10px;
    }
    .bot-health-card.compact-health .bot-health-title { font-size: 9px; }
    .bot-health-card.compact-health .bot-health-dot { width: 11px; height: 11px; }
  }
`;
