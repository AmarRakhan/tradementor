"""Strict read-through policy for staging access to existing user data.

The bridge deliberately forwards only a small allowlist of authenticated GET
requests.  It cannot forward settings changes, bot controls, order routes or
internal scheduler calls.
"""

from __future__ import annotations

from urllib.parse import urlsplit


READ_ONLY_PATHS = frozenset(
    {
        "/v1/me/wallet",
        "/v1/me/preflight",
        "/v1/me/hyperliquid/account-state",
        "/v1/me/hyperliquid/closed-trades",
        "/v1/me/dca/deals",
        "/v1/me/agent/status",
        "/v1/me/execution/preflight",
        "/v1/me/mexc/status",
        "/v1/me/aster/status",
        "/v1/me/aster/closed-trades",
        "/v1/me/aster/trade-events",
    }
)

# Strategy 2 controls in the shared live-test runtime are stored in that
# runtime's own Firestore project.  Forwarding the combined Aster status to the
# production read source would make GET disagree with start/stop mutations.
LOCAL_STATE_PATHS_BY_ENVIRONMENT = {
    "strategy2-test-live": frozenset({"/v1/me/aster/status"}),
}


def read_source_url(
    base_url: str,
    method: str,
    path: str,
    query: str = "",
    *,
    environment: str = "",
) -> str | None:
    """Return a safe upstream URL, or ``None`` when forwarding is forbidden."""

    local_paths = LOCAL_STATE_PATHS_BY_ENVIRONMENT.get(environment.strip().lower(), frozenset())
    if path in local_paths:
        return None
    if method.upper() not in {"GET", "HEAD"} or path not in READ_ONLY_PATHS:
        return None
    parsed = urlsplit(base_url.strip())
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return None
    target = f"{parsed.scheme}://{parsed.netloc}{path}"
    return f"{target}?{query}" if query else target
