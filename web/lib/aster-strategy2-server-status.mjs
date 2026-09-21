export function createLatestAsterRequestGate() {
  let generation = 0;
  let latestRequestId = 0;

  return {
    begin() {
      latestRequestId += 1;
      return { generation, requestId: latestRequestId };
    },
    confirmMutation() {
      generation += 1;
      latestRequestId += 1;
      return generation;
    },
    accepts(token) {
      return Boolean(token)
        && token.generation === generation
        && token.requestId === latestRequestId;
    },
    generation() {
      return generation;
    },
  };
}

const record = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};

function configVersion(value) {
  const state = record(value);
  const settings = record(state.settings);
  const parsed = Number(state.configVersion ?? settings.version ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function strategy2ServerStatus(strategy2, confirmedStrategy2, serverConfirmed) {
  const server = record(strategy2);
  const confirmed = record(confirmedStrategy2);
  const hasConfirmedMutation = Object.keys(confirmed).length > 0;
  // A confirmed mutation is authoritative only until the server publishes a
  // newer configVersion. This prevents an old browser snapshot from restoring
  // stale settings after a server-side repair or a change from another client.
  const useConfirmed = hasConfirmedMutation && configVersion(confirmed) >= configVersion(server);
  const authoritative = useConfirmed ? confirmed : server;
  const pending = !hasConfirmedMutation && serverConfirmed !== true;
  return {
    state: authoritative,
    pending,
    enabled: pending ? null : authoritative.enabled === true,
    liveReady: pending ? null : authoritative.liveReady === true,
    label: pending ? "Serverstatus controleren…" : authoritative.enabled === true ? "AAN" : "UIT",
  };
}
