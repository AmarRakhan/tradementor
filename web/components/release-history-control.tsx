"use client";

import { useEffect, useMemo, useState } from "react";
import { WEBAPP_BUILD_NUMBER, WEBAPP_VERSION } from "@/lib/app-version";
import { getReleaseHistory, releaseSearchText, type ReleaseHistoryEntry } from "@/lib/release-history";

const READ_BUILD_KEY = "amar.releaseHistory.lastReadBuild.v1";

function numericBuild(value: string | null) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatReleasedAt(value: string) {
  const hasTime = value.includes("T");
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value;
  return new Intl.DateTimeFormat("nl-NL", hasTime
    ? { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }
    : { day: "numeric", month: "short", year: "numeric" }
  ).format(date);
}

function releaseLabel(entry: ReleaseHistoryEntry) {
  return entry.build ? `v${entry.version} · build ${entry.build}` : `v${entry.version} · mijlpaal`;
}

function HistorySection({ tone, label, values }: { tone: string; label: string; values: string[] }) {
  if (!values.length) return null;
  return (
    <section className={`release-history-section ${tone}`}>
      <strong>{label}</strong>
      <div>{values.map((value) => <p key={value}>{value}</p>)}</div>
    </section>
  );
}

export function ReleaseHistoryControl() {
  const history = useMemo(() => getReleaseHistory(), []);
  const currentBuild = Number(WEBAPP_BUILD_NUMBER);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [lastReadBuild, setLastReadBuild] = useState<number | null>(null);
  const [readStateReady, setReadStateReady] = useState(false);
  const [latestSeen, setLatestSeen] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(
    () => new Set(history.slice(0, 3).map((entry) => entry.id)),
  );

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(READ_BUILD_KEY);
      const parsed = stored === null ? null : Number(stored);
      setLastReadBuild(parsed !== null && Number.isFinite(parsed) ? parsed : null);
    } catch {
      setLastReadBuild(null);
    } finally {
      setReadStateReady(true);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const timer = window.setTimeout(() => setLatestSeen(true), 250);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeHistory();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  const unreadCount = useMemo(() => {
    if (!readStateReady) return 0;
    if (lastReadBuild === null) return 1;
    return history.reduce((count, entry) => {
      const build = numericBuild(entry.build);
      return build !== null && build > lastReadBuild ? count + 1 : count;
    }, 0);
  }, [history, lastReadBuild, readStateReady]);

  const filteredHistory = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("nl-NL");
    if (!normalized) return history;
    return history.filter((entry) => releaseSearchText(entry).includes(normalized));
  }, [history, query]);

  function openHistory() {
    setLatestSeen(false);
    setQuery("");
    setExpandedIds(new Set(history.slice(0, 3).map((entry) => entry.id)));
    setOpen(true);
  }

  function closeHistory() {
    if (latestSeen && Number.isFinite(currentBuild)) {
      try {
        window.localStorage.setItem(READ_BUILD_KEY, String(currentBuild));
        setLastReadBuild(currentBuild);
      } catch {
        // A blocked local preference must never affect the running trading app.
      }
    }
    setOpen(false);
  }

  function toggleEntry(id: string) {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function isUnread(entry: ReleaseHistoryEntry) {
    const build = numericBuild(entry.build);
    if (build === null || !readStateReady) return false;
    if (lastReadBuild === null) return build === currentBuild;
    return build > lastReadBuild;
  }

  return (
    <>
      <button type="button" className="release-history-trigger" onClick={openHistory} aria-haspopup="dialog">
        <span className="release-history-trigger-icon" aria-hidden="true">↺</span>
        <span>Versiegeschiedenis</span>
        {unreadCount > 0 && <b className="release-history-unread-badge" aria-label={`${unreadCount} nieuwe builds`}>{unreadCount}</b>}
      </button>

      {open && (
        <div className="release-history-overlay" role="dialog" aria-modal="true" aria-labelledby="release-history-title">
          <header className="release-history-header">
            <div>
              <span className="release-history-kicker">CRYPTO BOT 2026 · v{WEBAPP_VERSION}</span>
              <h1 id="release-history-title">Versiegeschiedenis</h1>
              <p>Bekijk wat er per versie is veranderd en waarom. Nieuwste updates staan bovenaan.</p>
            </div>
            <button type="button" className="release-history-close" onClick={closeHistory} aria-label="Versiegeschiedenis sluiten">
              <span aria-hidden="true">×</span><small>Sluiten</small>
            </button>
          </header>

          <div className="release-history-toolbar">
            <label>
              <span aria-hidden="true">⌕</span>
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Zoek: DCA, short, liquidatie…"
                aria-label="Zoek in versiegeschiedenis"
              />
            </label>
            <span className="release-history-current-build">Nu: v{WEBAPP_VERSION} · build {WEBAPP_BUILD_NUMBER}</span>
          </div>

          <main className="release-history-list">
            {filteredHistory.length === 0 && (
              <div className="release-history-empty">
                <strong>Geen resultaten</strong>
                <span>Probeer een andere zoekterm.</span>
              </div>
            )}
            {filteredHistory.map((entry, index) => {
              const expanded = query.trim().length > 0 || expandedIds.has(entry.id);
              const unread = isUnread(entry);
              const live = entry.id === history[0]?.id;
              return (
                <article key={entry.id} className={`release-history-card ${unread ? "unread" : ""} ${live ? "live" : ""}`}>
                  <button type="button" className="release-history-card-head" onClick={() => toggleEntry(entry.id)} aria-expanded={expanded}>
                    <div>
                      <strong>{releaseLabel(entry)}</strong>
                      <span>{formatReleasedAt(entry.releasedAt)}</span>
                    </div>
                    <div className="release-history-head-badges">
                      {live && <b className="release-status live">LIVE</b>}
                      {unread && <b className="release-status new">NIEUW</b>}
                      {entry.confidence === "reconstructed" && <b className="release-status reconstructed">GERECONSTRUEERD</b>}
                      <i aria-hidden="true">{expanded ? "⌃" : "⌄"}</i>
                    </div>
                  </button>

                  {expanded && (
                    <div className="release-history-card-body">
                      <h2>{entry.title}</h2>
                      <HistorySection tone="new" label="Nieuw" values={entry.newItems} />
                      <HistorySection tone="problem" label="Probleem" values={entry.problems} />
                      <HistorySection tone="cause" label="Oorzaak" values={entry.causes} />
                      <HistorySection tone="fix" label="Oplossing" values={entry.fixes} />
                      <HistorySection tone="now" label="Nu" values={entry.now} />

                      {(entry.before || entry.after) && (
                        <div className="release-history-before-after">
                          {entry.before && <div><span>Voorheen</span><p>{entry.before}</p></div>}
                          {entry.after && <div><span>Nu</span><p>{entry.after}</p></div>}
                        </div>
                      )}

                      {entry.technicalDetails?.length ? (
                        <details className="release-history-technical">
                          <summary>Technische details</summary>
                          <ul>{entry.technicalDetails.map((detail) => <li key={detail}>{detail}</li>)}</ul>
                        </details>
                      ) : null}

                      <footer>
                        {entry.confidence === "confirmed"
                          ? "Bevestigd uit code, Git, build of deployment."
                          : "Gereconstrueerde historie · exacte builddetails zijn niet overal bewaard."}
                      </footer>
                    </div>
                  )}
                </article>
              );
            })}
          </main>
        </div>
      )}
    </>
  );
}
