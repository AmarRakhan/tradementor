"""Profit sparen 3.0 — exchange-truth close scan.

Rule (owner, 2026-10-23): every close that ends green contributes the
configured percentage (now 5%) of its new money to the Profit Pot. Small
contributions accumulate in ``pendingSavings``; only whole blocks of the
minimum transfer (default US$ 1) are moved Futures -> Spot.

Why a scan instead of a per-order hook: the old hook prepared evidence *before*
each close and silently skipped the close when that evidence did not line up
(DCA history, partial hedge closes, slow fill visibility, process-local signer
mapping). Here the source of truth is what Aster itself reports afterwards:
the confirmed closing fills (``realizedPnl`` != 0) grouped per exchange order.

Per close order:
    gross        = sum(realizedPnl of the closing fills)
    close_fee    = sum(|commission| of the closing fills)
    entry_fee    = close_fee (estimate: same fee rate on roughly the same size)
    net          = gross - close_fee - entry_fee
    contribution = net * percent / 100   (only when net > 0, rounded down)

Every order is booked at most once (document per symbol+orderId, transactional)
and never when the previous hook already booked that same exchange order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from typing import Any, Iterable
from zoneinfo import ZoneInfo

try:  # pragma: no cover - exercised in production only
    from google.cloud import firestore
except Exception:  # pragma: no cover
    firestore = None  # type: ignore[assignment]

LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
QUANTUM = Decimal("0.00000001")
SETTLE_MS = 10_000          # only fills older than this are scanned (order complete)
OVERLAP_MS = 120_000        # re-read window behind the cursor; idempotency makes it safe
MAX_PAGES = 10
MAX_LOOKBACK_MS = 6 * 24 * 60 * 60 * 1000
FEE_ASSETS = {"USDT", "USDC", "USD"}
ORDERS_COLLECTION = "asterProfitSweepOrders"
STATE_COLLECTION = "asterProfitSweepState"
LEGACY_LEDGER_COLLECTION = "asterProfitSweeps"


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _plain(value: Decimal) -> str:
    text = format(value.quantize(QUANTUM, rounding=ROUND_DOWN).normalize(), "f")
    return "0" if text in {"-0", ""} else text


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def local_day_start_ms(now_ms: int) -> int:
    local = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).astimezone(LOCAL_TZ)
    start = datetime(local.year, local.month, local.day, tzinfo=LOCAL_TZ)
    return int(start.timestamp() * 1000)


@dataclass(frozen=True)
class CloseOrder:
    symbol: str
    order_id: str
    position_side: str
    gross: Decimal
    close_fee: Decimal
    closed_at_ms: int
    fill_count: int

    @property
    def entry_fee_estimate(self) -> Decimal:
        return self.close_fee

    @property
    def net(self) -> Decimal:
        return self.gross - self.close_fee - self.entry_fee_estimate

    @property
    def doc_id(self) -> str:
        return f"{self.symbol}_{self.order_id}"


def contribution_for(net: Decimal, percent: Decimal) -> Decimal:
    if net <= 0 or percent <= 0:
        return Decimal("0")
    return (net * percent / Decimal("100")).quantize(QUANTUM, rounding=ROUND_DOWN)


def group_close_orders(fills: Iterable[dict[str, Any]], *, until_ms: int) -> list[CloseOrder]:
    """Group confirmed closing fills (non-zero realizedPnl) per exchange order."""
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in fills:
        if not isinstance(row, dict):
            continue
        pnl = _d(row.get("realizedPnl", row.get("realizedProfit")))
        if pnl == 0:
            continue  # opening fill (or a flat close with nothing to save)
        order_id = str(row.get("orderId", "")).strip()
        symbol = str(row.get("symbol", "")).upper().strip()
        if not order_id or not symbol:
            continue
        stamp = int(_d(row.get("time")))
        asset = str(row.get("commissionAsset", "USDT")).upper().strip() or "USDT"
        bucket = buckets.setdefault((symbol, order_id), {
            "side": str(row.get("positionSide", "")).upper(),
            "gross": Decimal("0"), "fee": Decimal("0"), "time": 0, "count": 0,
            "fills": set(), "foreignFee": False,
        })
        fill_key = str(row.get("id", "")) or f"{stamp}:{row.get('qty')}:{row.get('price')}"
        if fill_key in bucket["fills"]:
            continue
        bucket["fills"].add(fill_key)
        bucket["gross"] += pnl
        if asset in FEE_ASSETS:
            bucket["fee"] += abs(_d(row.get("commission")))
        else:
            bucket["foreignFee"] = True
        bucket["time"] = max(bucket["time"], stamp)
        bucket["count"] += 1
    orders = []
    for (symbol, order_id), bucket in buckets.items():
        if bucket["time"] > until_ms or bucket["foreignFee"]:
            continue  # not settled yet, or fee not reliably in USD
        orders.append(CloseOrder(
            symbol=symbol, order_id=order_id, position_side=bucket["side"],
            gross=bucket["gross"], close_fee=bucket["fee"],
            closed_at_ms=bucket["time"], fill_count=bucket["count"],
        ))
    orders.sort(key=lambda order: (order.closed_at_ms, order.doc_id))
    return orders


def _paged(fetch, *, start_ms: int, end_ms: int, time_key: str = "time") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = start_ms
    for _ in range(MAX_PAGES):
        page = fetch(cursor, end_ms)
        if not isinstance(page, list):
            raise ValueError("Aster gaf geen lijst terug")
        rows.extend(row for row in page if isinstance(row, dict))
        if len(page) < 1000:
            return rows
        last = max(int(_d(row.get(time_key))) for row in page if isinstance(row, dict))
        if last <= cursor:
            raise ValueError("Aster-historie loopt niet door; scan wordt herhaald")
        cursor = last  # inclusive; duplicates are removed by fill id
    raise ValueError("Te veel Aster-historie in één scan; volgende minuut verder")


def read_close_orders(client: Any, *, start_ms: int, end_ms: int) -> list[CloseOrder]:
    income = _paged(
        lambda s, e: client.income_history(income_type="REALIZED_PNL", start_time=s, end_time=e, limit=1000),
        start_ms=start_ms, end_ms=end_ms,
    )
    symbols = sorted({str(row.get("symbol", "")).upper() for row in income if str(row.get("symbol", "")).strip()})
    fills: list[dict[str, Any]] = []
    for symbol in symbols:
        fills.extend(_paged(
            lambda s, e, sym=symbol: client.user_trades(sym, start_time=s, end_time=e, limit=1000),
            start_ms=start_ms, end_ms=end_ms,
        ))
    return group_close_orders(fills, until_ms=end_ms)


def _legacy_already_booked(user_ref: Any, order_id: str) -> bool:
    """True when the previous per-order hook already credited this exchange order."""
    query = user_ref.collection(LEGACY_LEDGER_COLLECTION).where("exchangeOrderId", "==", str(order_id)).limit(10)
    for snapshot in query.stream():
        row = snapshot.to_dict() or {}
        if row.get("bufferBooked") is True:
            return True
    return False


def _book_order(user_ref: Any, order: CloseOrder, *, percent: Decimal, asset: str,
                minimum: Decimal, legacy_booked: bool) -> str:
    order_ref = user_ref.collection(ORDERS_COLLECTION).document(order.doc_id)
    state_ref = user_ref.collection(STATE_COLLECTION).document("current")
    contribution = Decimal("0") if legacy_booked else contribution_for(order.net, percent)
    client = getattr(state_ref, "_client", None)

    def apply(transaction: Any | None = None) -> str:
        read = (lambda ref: ref.get()) if transaction is None else (lambda ref: ref.get(transaction=transaction))
        existing = read(order_ref).to_dict() or {}
        if existing.get("status") in {"BOOKED", "SKIPPED_NONPOSITIVE", "BOOKED_BY_LEGACY_HOOK"}:
            return "ALREADY"
        state = read(state_ref).to_dict() or {}
        now = datetime.now(timezone.utc)
        status = (
            "BOOKED_BY_LEGACY_HOOK" if legacy_booked
            else "BOOKED" if contribution > 0
            else "SKIPPED_NONPOSITIVE"
        )
        row = {
            "status": status,
            "symbol": order.symbol,
            "exchangeOrderId": order.order_id,
            "positionSide": order.position_side,
            "closedAtMs": order.closed_at_ms,
            "fillCount": order.fill_count,
            "grossRealizedPnl": _plain(order.gross),
            "closeFee": _plain(order.close_fee),
            "entryFeeEstimate": _plain(order.entry_fee_estimate),
            "netProfit": _plain(order.net),
            "sweepPercent": _plain(percent),
            "contribution": _plain(contribution),
            "asset": asset,
            "source": "CLOSE_SCAN_V3",
            "bookedAt": now,
        }
        writes = [(order_ref, row)]
        if status == "BOOKED":
            pending = _d(state.get("pendingSavings")) + contribution
            writes.append((state_ref, {
                "pendingSavings": _plain(pending),
                "minimumTransfer": _plain(minimum),
                "asset": asset,
                "lastContributionAt": now,
                "lastContributionAmount": _plain(contribution),
                "updatedAt": now,
            }))
        for ref, data in writes:
            if transaction is None:
                ref.set(data, merge=True)
            else:
                transaction.set(ref, data, merge=True)
        return status

    if client is None or firestore is None:
        return apply()

    @firestore.transactional
    def run(transaction: Any) -> str:
        return apply(transaction)

    return run(client.transaction())


def scan_and_book_closes(*, user_ref: Any, client: Any, percent: Decimal, asset: str,
                         minimum: Decimal, now_ms: int | None = None) -> dict[str, Any]:
    """Book every settled green close since the cursor; advance the cursor only on full success."""
    now_ms = _now_ms() if now_ms is None else int(now_ms)
    state_ref = user_ref.collection(STATE_COLLECTION).document("current")
    state = state_ref.get().to_dict() or {}
    end_ms = now_ms - SETTLE_MS
    cursor = int(_d(state.get("closeScanCursorMs")))
    if cursor <= 0:
        # First run: pick up today's closes (the old hook missed part of them).
        cursor = local_day_start_ms(now_ms)
        start_ms = cursor
    else:
        # Aster fill history accepts at most a 7-day window.
        start_ms = max(cursor - OVERLAP_MS, now_ms - MAX_LOOKBACK_MS)
    if end_ms <= start_ms:
        return {"status": "WAITING", "booked": 0, "contribution": "0"}

    orders = read_close_orders(client, start_ms=start_ms, end_ms=end_ms)
    booked = 0
    total = Decimal("0")
    for order in orders:
        existing = user_ref.collection(ORDERS_COLLECTION).document(order.doc_id).get().to_dict() or {}
        if existing.get("status"):
            continue
        legacy = _legacy_already_booked(user_ref, order.order_id)
        status = _book_order(user_ref, order, percent=percent, asset=asset, minimum=minimum, legacy_booked=legacy)
        if status == "BOOKED":
            booked += 1
            total += contribution_for(order.net, percent)
    state_ref.set({"closeScanCursorMs": end_ms, "closeScanAt": datetime.now(timezone.utc)}, merge=True)
    return {"status": "OK", "orders": len(orders), "booked": booked, "contribution": _plain(total)}
