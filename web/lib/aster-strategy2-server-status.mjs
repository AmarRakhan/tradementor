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

export function strategy2ServerStatus(strategy2, confirmedStrategy2, serverConfirmed) {
  const confirmed = record(confirmedStrategy2);
  const hasConfirmedMutation = Object.keys(confirmed).length > 0;
  const authoritative = hasConfirmedMutation ? confirmed : record(strategy2);
  const pending = !hasConfirmedMutation && serverConfirmed !== true;
  return {
    state: authoritative,
    pending,
    enabled: pending ? null : authoritative.enabled === true,
    liveReady: pending ? null : authoritative.liveReady === true,
    label: pending ? "Serverstatus controleren…" : authoritative.enabled === true ? "AAN" : "UIT",
  };
}
