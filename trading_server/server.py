"""Local TradeMentor execution gateway.

Real trading is deliberately locked until the operator starts the server with
TRADEMENTOR_ALLOW_ONE_TEST_ORDER=true and supplies the one-time confirmation
token printed at startup. No secret is written to disk.
"""
from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

from eth_account import Account
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants

DEFAULT_MAX_ACTIVE_POSITIONS = 40
ABSOLUTE_MAX_ACTIVE_POSITIONS = 400
MAX_TEST_POSITION_USD = 20.0
MAX_SLIPPAGE = 0.01


@dataclass
class Runtime:
    master_address: str
    info: Info
    exchange: Exchange
    confirmation_token: str
    test_order_consumed: bool = False
    positions_cache: list[dict[str, Any]] | None = None
    positions_cache_at: float = 0.0
    max_active_positions: int = DEFAULT_MAX_ACTIVE_POSITIONS
    added_symbols: set[str] | None = None


runtime: Runtime | None = None
runtime_lock = threading.Lock()
app = FastAPI(title="TradeMentor Local Trading Gateway", version="0.1.0")


class TestOrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    short: bool
    position_value_usd: float = Field(gt=0, le=MAX_TEST_POSITION_USD)
    leverage: int = Field(ge=1, le=100)
    signal_price: float = Field(gt=0)
    profit_percentage: float = Field(gt=0, le=25)


class RuntimeSettingsRequest(BaseModel):
    max_active_positions: int = Field(ge=1, le=ABSOLUTE_MAX_ACTIVE_POSITIONS)


class ClosePositionRequest(BaseModel):
    confirm: bool


class TakeProfitRequest(BaseModel):
    profit_percentage: float = Field(gt=0, le=25)


class AddOnOrderRequest(TestOrderRequest):
    pass


def configure(master_address: str, api_private_key: str) -> str:
    global runtime
    master = master_address.strip().lower()
    if not (master.startswith("0x") and len(master) == 42):
        raise ValueError("Ongeldig hoofdwalletadres")
    wallet = Account.from_key(api_private_key.strip())
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    exchange = Exchange(wallet, constants.MAINNET_API_URL, account_address=master)
    token = os.getenv("TRADEMENTOR_SESSION_TOKEN", "").strip() or secrets.token_urlsafe(18)
    runtime = Runtime(master, info, exchange, token)
    return token


def state() -> dict[str, Any]:
    if runtime is None:
        raise HTTPException(503, "Server is nog niet gekoppeld aan een API-wallet")
    return runtime.info.user_state(runtime.master_address)


def positions() -> list[dict[str, Any]]:
    if runtime is None:
        raise HTTPException(503, "Server is nog niet gekoppeld aan een API-wallet")
    now = time.monotonic()
    if runtime.positions_cache is not None and now - runtime.positions_cache_at < 8.0:
        return runtime.positions_cache

    states = [state()]
    # MetaMask Perps can also hold positions on Hyperliquid builder/HIP-3 DEXes.
    # They must count toward the same 40-position cap as standard perps.
    for dex in runtime.info.perp_dexs():
        name = dex.get("name", "") if isinstance(dex, dict) else str(dex)
        if not name:
            continue
        time.sleep(0.175)
        try:
            states.append(runtime.info.user_state(runtime.master_address, name))
        except Exception:
            # A temporarily rate-limited auxiliary DEX must not erase the
            # already known positions from the safety count.
            continue

    current: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for account_state in states:
        for item in account_state.get("assetPositions", []):
            position = item.get("position", {})
            if float(position.get("szi", "0")) == 0.0:
                continue
            key = (str(position.get("coin", "")), str(position.get("szi", "")), str(position.get("entryPx", "")))
            if key not in seen:
                seen.add(key)
                current.append(position)
    runtime.positions_cache = current
    runtime.positions_cache_at = now
    return current


@app.get("/health")
def health() -> dict[str, Any]:
    current = positions() if runtime else []
    return {
        "status": "ready" if runtime else "unconfigured",
        "environment": "mainnet",
        "tradingEnabled": bool(runtime and (
            os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() == "true" or
            (os.getenv("TRADEMENTOR_ALLOW_ONE_TEST_ORDER", "").lower() == "true" and not runtime.test_order_consumed)
        )),
        "oneTestOrderArmed": bool(os.getenv("TRADEMENTOR_ALLOW_ONE_TEST_ORDER", "").lower() == "true"),
        "activePositions": len(current),
        "remainingSlots": max(0, (runtime.max_active_positions if runtime else DEFAULT_MAX_ACTIVE_POSITIONS) - len(current)),
    }


@app.get("/preflight")
def preflight() -> dict[str, Any]:
    current = positions()
    longs = sum(float(p["szi"]) > 0 for p in current)
    shorts = sum(float(p["szi"]) < 0 for p in current)
    return {
        "masterAddress": runtime.master_address if runtime else None,
        "activePositions": len(current),
        "maxActivePositions": runtime.max_active_positions if runtime else DEFAULT_MAX_ACTIVE_POSITIONS,
        "remainingSlots": max(0, (runtime.max_active_positions if runtime else DEFAULT_MAX_ACTIVE_POSITIONS) - len(current)),
        "longs": longs,
        "shorts": shorts,
        "symbols": sorted(p["coin"] for p in current),
        "safeToPrepareTest": len(current) < (runtime.max_active_positions if runtime else DEFAULT_MAX_ACTIVE_POSITIONS),
    }


def _authorized(x_confirmation_token: str | None) -> None:
    if runtime is None:
        raise HTTPException(503, "API-wallet ontbreekt")
    if x_confirmation_token != runtime.confirmation_token:
        raise HTTPException(403, "Ongeldige lokale serversessie")


@app.post("/settings")
def update_settings(request: RuntimeSettingsRequest, x_confirmation_token: str | None = Header(default=None)) -> dict[str, Any]:
    _authorized(x_confirmation_token)
    runtime.max_active_positions = request.max_active_positions
    return {"maxActivePositions": runtime.max_active_positions, "activePositions": len(positions())}


def _assert_order_safety(request: TestOrderRequest) -> tuple[str, float, float]:
    if runtime is None:
        raise HTTPException(503, "API-wallet ontbreekt")
    current = positions()
    if len(current) >= runtime.max_active_positions:
        raise HTTPException(409, f"Maximum van {runtime.max_active_positions} posities is bereikt")
    symbol = request.symbol.strip()
    normalized = symbol.upper()
    if any(str(p.get("coin", "")).upper() == normalized for p in current):
        raise HTTPException(409, "Deze pair heeft al een open positie")
    longs = sum(float(p["szi"]) > 0 for p in current)
    shorts = sum(float(p["szi"]) < 0 for p in current)
    prospective_longs = longs + (0 if request.short else 1)
    prospective_shorts = shorts + (1 if request.short else 0)
    if abs(prospective_longs - prospective_shorts) > 5:
        raise HTTPException(409, "Deze order zou het maximale LONG/SHORT-verschil van 5 overschrijden")
    dex = symbol.split(":", 1)[0] if ":" in symbol else ""
    mids = runtime.info.all_mids(dex)
    mark = float(mids[symbol])
    drift = abs(mark / request.signal_price - 1.0)
    if drift > 0.005:
        raise HTTPException(409, f"Koers is {drift * 100:.2f}% van het signal afgeweken")
    size = request.position_value_usd / mark
    size_decimals = runtime.info.asset_to_sz_decimals[runtime.info.name_to_asset(symbol)]
    size = round(size, size_decimals)
    if size <= 0 or size * mark < 10:
        raise HTTPException(422, "Ordergrootte is na afronding kleiner dan $10")
    return symbol, mark, size


def _filled_order(response: dict[str, Any]) -> tuple[float, float, int | None]:
    try:
        status = response["response"]["data"]["statuses"][0]
        filled = status["filled"]
        return float(filled["avgPx"]), float(filled["totalSz"]), filled.get("oid")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise HTTPException(502, f"Instap is niet als volledig uitgevoerd bevestigd: {response}") from exc


def _valid_perp_price(symbol: str, price: float) -> float:
    asset = runtime.info.name_to_asset(symbol)
    decimals = max(0, 6 - runtime.info.asset_to_sz_decimals[asset])
    return round(float(f"{price:.5g}"), decimals)


@app.post("/orders/one-test-order")
def one_test_order(request: TestOrderRequest, x_confirmation_token: str | None = Header(default=None)) -> dict[str, Any]:
    if runtime is None:
        raise HTTPException(503, "API-wallet ontbreekt")
    live_mode = os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() == "true"
    test_mode = os.getenv("TRADEMENTOR_ALLOW_ONE_TEST_ORDER", "").lower() == "true"
    if not live_mode and not test_mode:
        raise HTTPException(423, "Echte orderverzending is vergrendeld")
    _authorized(x_confirmation_token)
    with runtime_lock:
        if not live_mode and runtime.test_order_consumed:
            raise HTTPException(409, "De eenmalige testorder is al gebruikt")
        symbol, mark, size = _assert_order_safety(request)
        runtime.exchange.update_leverage(request.leverage, symbol, is_cross=True)
        entry_response = runtime.exchange.market_open(symbol, not request.short, size, px=mark, slippage=MAX_SLIPPAGE)
        fill_price, filled_size, entry_oid = _filled_order(entry_response)
        target = _valid_perp_price(symbol, fill_price * (1.0 - request.profit_percentage / 100.0 if request.short else 1.0 + request.profit_percentage / 100.0))
        tp_response = runtime.exchange.order(
            symbol,
            request.short,
            filled_size,
            target,
            {"trigger": {"triggerPx": target, "isMarket": True, "tpsl": "tp"}},
            reduce_only=True,
        )
        try:
            tp_status = tp_response["response"]["data"]["statuses"][0]
            if "error" in tp_status or "resting" not in tp_status:
                raise ValueError(tp_status["error"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            if not live_mode:
                runtime.test_order_consumed = True
            raise HTTPException(502, f"Instap uitgevoerd, maar take-profit niet bevestigd. Handel gepauzeerd: {tp_response}") from exc
        if not live_mode:
            runtime.test_order_consumed = True
        runtime.positions_cache = None
        return {
            "accepted": True,
            "symbol": symbol,
            "short": request.short,
            "filledSize": filled_size,
            "fillPrice": fill_price,
            "targetPrice": target,
            "entryOrderId": entry_oid,
            "takeProfit": tp_response,
        }


@app.post("/positions/add-on")
def add_on_position(request: AddOnOrderRequest, x_confirmation_token: str | None = Header(default=None)) -> dict[str, Any]:
    if runtime is None or os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() != "true":
        raise HTTPException(423, "Echte orderverzending is vergrendeld")
    _authorized(x_confirmation_token)
    with runtime_lock:
        normalized = request.symbol.strip().upper()
        runtime.added_symbols = runtime.added_symbols or set()
        if normalized in runtime.added_symbols:
            raise HTTPException(409, "Deze pair is al één keer bijgekocht")
        current = next((p for p in positions() if str(p.get("coin", "")).upper() == normalized), None)
        if current is None:
            raise HTTPException(404, "De actieve positie bestaat niet meer")
        current_short = float(current.get("szi", "0")) < 0
        if current_short != request.short:
            raise HTTPException(409, "De bijkooprichting wijkt af van de actieve positie")
        symbol = request.symbol.strip()
        dex = symbol.split(":", 1)[0] if ":" in symbol else ""
        mark = float(runtime.info.all_mids(dex)[symbol])
        drift = abs(mark / request.signal_price - 1.0)
        if drift > 0.003:
            raise HTTPException(409, f"Koers is {drift * 100:.2f}% veranderd; analyse opnieuw uitvoeren")
        size_decimals = runtime.info.asset_to_sz_decimals[runtime.info.name_to_asset(symbol)]
        add_size = round(request.position_value_usd / mark, size_decimals)
        if add_size <= 0 or add_size * mark < 10:
            raise HTTPException(422, "Bijkoop is na afronding kleiner dan $10")
        runtime.exchange.update_leverage(request.leverage, symbol, is_cross=True)
        entry_response = runtime.exchange.market_open(symbol, not request.short, add_size, px=mark, slippage=MAX_SLIPPAGE)
        fill_price, filled_size, _ = _filled_order(entry_response)
        runtime.positions_cache = None
        refreshed = next((p for p in positions() if str(p.get("coin", "")).upper() == normalized), None)
        if refreshed is None:
            raise HTTPException(502, "Bijkoop gevuld, maar de nieuwe positie kon niet worden gelezen")
        for order in runtime.info.open_orders(runtime.master_address, dex):
            if str(order.get("coin", "")).upper() == normalized:
                runtime.exchange.cancel(symbol, int(order["oid"]))
        total_size = abs(float(refreshed["szi"]))
        average_entry = float(refreshed["entryPx"])
        target = _valid_perp_price(symbol, average_entry * (1.0 - request.profit_percentage / 100.0 if request.short else 1.0 + request.profit_percentage / 100.0))
        tp_response = runtime.exchange.order(symbol, request.short, total_size, target, {"trigger": {"triggerPx": target, "isMarket": True, "tpsl": "tp"}}, reduce_only=True)
        try:
            tp_status = tp_response["response"]["data"]["statuses"][0]
            if "error" in tp_status or "resting" not in tp_status:
                raise ValueError(tp_status.get("error", "onbekende fout"))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise HTTPException(502, f"Bijkoop gevuld, maar take-profit voor de totale positie ontbreekt: {tp_response}") from exc
        runtime.added_symbols.add(normalized)
        return {"accepted": True, "symbol": symbol, "short": request.short, "filledSize": filled_size, "fillPrice": fill_price, "targetPrice": target}


@app.post("/positions/{symbol}/close")
def close_position(symbol: str, request: ClosePositionRequest, x_confirmation_token: str | None = Header(default=None)) -> dict[str, Any]:
    _authorized(x_confirmation_token)
    if not request.confirm:
        raise HTTPException(400, "Handmatige bevestiging ontbreekt")
    with runtime_lock:
        normalized = symbol.strip().upper()
        current = next((p for p in positions() if str(p.get("coin", "")).upper() == normalized), None)
        if current is None:
            raise HTTPException(404, "Positie bestaat niet meer")
        unrealized_pnl = float(current.get("unrealizedPnl", "0") or 0)
        position_value = abs(float(current.get("positionValue", "0") or 0))
        # A market close has fees and can slip between the check and the fill.
        # Require a conservative positive buffer instead of merely PNL > 0.
        minimum_positive_buffer = max(0.05, position_value * 0.0015)
        if unrealized_pnl <= minimum_positive_buffer:
            raise HTTPException(
                409,
                f"Positie blijft open: PNL ${unrealized_pnl:.4f} is niet hoog genoeg voor een gegarandeerd positieve app-sluiting "
                f"(veiligheidsbuffer ${minimum_positive_buffer:.4f}).",
            )
        dex = symbol.split(":", 1)[0] if ":" in symbol else ""
        open_orders = runtime.info.open_orders(runtime.master_address, dex)
        cancelled: list[Any] = []
        for order in open_orders:
            if str(order.get("coin", "")).upper() == normalized:
                cancelled.append(runtime.exchange.cancel(symbol, int(order["oid"])))
        response = runtime.exchange.market_close(symbol, sz=abs(float(current["szi"])), slippage=MAX_SLIPPAGE)
        runtime.positions_cache = None
        return {"closed": response.get("status") == "ok", "symbol": symbol, "cancelledOrders": len(cancelled), "response": response}


@app.post("/positions/{symbol}/take-profit")
def place_position_take_profit(symbol: str, request: TakeProfitRequest, x_confirmation_token: str | None = Header(default=None)) -> dict[str, Any]:
    _authorized(x_confirmation_token)
    with runtime_lock:
        normalized = symbol.strip().upper()
        current = next((p for p in positions() if str(p.get("coin", "")).upper() == normalized), None)
        if current is None:
            raise HTTPException(404, "Positie bestaat niet meer")
        size = float(current["szi"])
        entry = float(current["entryPx"])
        short = size < 0
        target = _valid_perp_price(symbol, entry * (1.0 - request.profit_percentage / 100.0 if short else 1.0 + request.profit_percentage / 100.0))
        response = runtime.exchange.order(
            symbol,
            short,
            abs(size),
            target,
            {"trigger": {"triggerPx": target, "isMarket": True, "tpsl": "tp"}},
            reduce_only=True,
        )
        try:
            status = response["response"]["data"]["statuses"][0]
            if "resting" not in status:
                raise ValueError(status)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise HTTPException(502, f"Take-profit is niet als open order bevestigd: {response}") from exc
        return {"placed": True, "symbol": symbol, "entryPrice": entry, "targetPrice": target, "response": response}
