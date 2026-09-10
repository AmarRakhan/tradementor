"""P0 fail-closed guard for the Aster bulk-profit close endpoint.

The current production entrypoint registers secure extension routes through
``withdraw_app``. This wrapper preserves that entrypoint while requiring every
bulk-profit close to carry exactly one explicit ALL, LONG or SHORT scope.
"""
from __future__ import annotations

from contextvars import ContextVar
import inspect
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs

from starlette.responses import JSONResponse

import main as _main
import withdraw_app as _entry


_CLOSE_PATH = "/v1/me/aster/positions/close-profitable"
_VALID_SCOPES = {"ALL", "LONG", "SHORT"}
_ACTIVE_SCOPE: ContextVar[str] = ContextVar("aster_profit_close_scope", default="ALL")
_ORIGINAL_PROFITABLE_POSITIONS = _main.profitable_positions
_NATIVE_SIDE_SCOPE = "side" in inspect.signature(_main.close_profitable_aster_positions).parameters
_MODE = "native" if _NATIVE_SIDE_SCOPE else "legacy-filter"


def _requested_scope(query_string: bytes) -> str | None:
    try:
        values = parse_qs(query_string.decode("ascii"), keep_blank_values=True).get("side", [])
    except (UnicodeDecodeError, ValueError):
        return None
    if len(values) != 1:
        return None
    value = str(values[0]).strip().upper()
    return value if value in _VALID_SCOPES else None


def _scoped_profitable_positions(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    selected = list(_ORIGINAL_PROFITABLE_POSITIONS(*args, **kwargs))
    scope = _ACTIVE_SCOPE.get()
    if scope == "ALL":
        return selected
    return [row for row in selected if str(row.get("side", "")).upper().strip() == scope]


if not _NATIVE_SIDE_SCOPE:
    _main.profitable_positions = _scoped_profitable_positions


class CloseScopeGuard:
    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, asgi_scope: dict[str, Any], receive: Any, send: Any) -> None:
        protected = (
            asgi_scope.get("type") == "http"
            and str(asgi_scope.get("method", "")).upper() == "POST"
            and asgi_scope.get("path") == _CLOSE_PATH
        )
        if not protected:
            await self.app(asgi_scope, receive, send)
            return

        requested = _requested_scope(asgi_scope.get("query_string", b""))

        async def guarded_send(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-tradementor-profit-scope-guard", b"enforced"))
                headers.append((b"x-tradementor-profit-scope-mode", _MODE.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        if requested is None:
            response = JSONResponse(
                {"detail": "Profit close is geblokkeerd: expliciete side=ALL, LONG of SHORT ontbreekt of is ongeldig"},
                status_code=422,
                headers={"Cache-Control": "no-store"},
            )
            await response(asgi_scope, receive, guarded_send)
            return

        token = _ACTIVE_SCOPE.set(requested)
        try:
            await self.app(asgi_scope, receive, guarded_send)
        finally:
            _ACTIVE_SCOPE.reset(token)


app = CloseScopeGuard(_entry.app)
