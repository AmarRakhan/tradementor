from decimal import Decimal
import time

from google.api_core import exceptions as google_exceptions

from aster_gateway import AsterSubmissionUncertain
from profit_sweep_live import (
    TRANSFER_PATH,
    finalize_close_sweep,
    is_closing_fill,
    net_realized_for_order,
    open_inventory,
    prepare_close_sweep,
    _recovery_client_tran_id,
    recover_failed_sweep,
    recover_blocked_close_to_buffer,
    transfer_safety,
)


class FakeSnapshot:
    def __init__(self, data): self._data = data
    def to_dict(self): return dict(self._data)


class FakeDoc:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.exists = bool(data)
    def get(self): return FakeSnapshot(self.data)
    def create(self, value):
        if self.exists:
            raise google_exceptions.AlreadyExists("exists")
        self.data = dict(value); self.exists = True
    def set(self, value, merge=False):
        if merge: self.data.update(value)
        else: self.data = dict(value)
        self.exists = True


class FakeCollection:
    def __init__(self): self.docs = {}
    def document(self, key):
        if key not in self.docs: self.docs[key] = FakeDoc()
        return self.docs[key]


class FakeUserRef:
    def __init__(self, *, enabled=True, percent=25, asset="USDT", minimum=1.0):
        self.collections = {}
        control = self.collection("executionControls").document("aster")
        control.set({
            "masterAddress": "0x" + "a" * 40,
            "profitSweep": {"enabled": enabled, "sweepPercent": percent, "transferAsset": asset, "minimumTransfer": minimum},
        })
    def collection(self, key):
        if key not in self.collections: self.collections[key] = FakeCollection()
        return self.collections[key]


class FakeClient:
    def __init__(self, *, uncertain=False, transfer_history=None, spot_history=None):
        self.calls = 0
        self.transfers = []
        self.uncertain = uncertain
        self.transfer_history = list(transfer_history or [])
        self.spot_history = list(spot_history or [])
        self.pre = [{
            "id": 1, "orderId": 10, "symbol": "BTCUSDT", "positionSide": "LONG", "side": "BUY",
            "qty": "1", "commission": "-0.10", "commissionAsset": "USDT", "realizedPnl": "0", "time": 1000,
        }]
        self.post = [*self.pre, {
            "id": 2, "orderId": 99, "symbol": "BTCUSDT", "positionSide": "LONG", "side": "SELL",
            "qty": "1", "commission": "-0.05", "commissionAsset": "USDT", "realizedPnl": "4", "time": 2000,
        }]
    def user_trades(self, symbol, **kwargs):
        self.calls += 1
        return list(self.pre if self.calls == 1 else self.post)
    def income_history(self, **kwargs):
        if str(kwargs.get("income_type", "")).upper() == "TRANSFER":
            return list(self.transfer_history)
        return []
    def account_information(self):
        return {"availableBalance": "100", "totalMarginBalance": "100", "totalMaintMargin": "10"}
    def signed_request(self, method, path, params):
        return {"ok": True}
    def signed_spot_request(self, method, path, params):
        if method.upper() == "GET":
            return list(self.spot_history)
        self.transfers.append((method, path, dict(params)))
        if self.uncertain: raise AsterSubmissionUncertain("unknown")
        return {"tranId": 777, "status": "SUCCESS"}


def test_close_direction_detection_is_exact():
    assert is_closing_fill({"positionSide": "LONG", "side": "SELL"})
    assert is_closing_fill({"positionSide": "SHORT", "side": "BUY"})
    assert not is_closing_fill({"positionSide": "LONG", "side": "BUY"})
    assert not is_closing_fill({"positionSide": "SHORT", "side": "SELL"})


def test_open_inventory_keeps_only_unallocated_entry_fee():
    rows = [
        {"id": 1, "positionSide": "LONG", "side": "BUY", "qty": "2", "commission": "-0.20", "commissionAsset": "USDT", "time": 1000},
        {"id": 2, "positionSide": "LONG", "side": "SELL", "qty": "0.5", "commission": "-0.05", "commissionAsset": "USDT", "time": 1500},
    ]
    qty, fee_pool, start = open_inventory(rows, "LONG")
    assert qty == Decimal("1.5")
    assert fee_pool == Decimal("-0.150")
    assert start == 1000


def test_actual_net_profit_deducts_entry_and_close_commission():
    net, detail = net_realized_for_order(
        target_fills=[{
            "positionSide": "LONG", "side": "SELL", "qty": "1.5", "realizedPnl": "10",
            "commission": "-0.15", "commissionAsset": "USDT",
        }],
        position_side="LONG",
        pre_open_quantity=Decimal("1.5"),
        pre_entry_commission_pool=Decimal("-0.15"),
    )
    assert net == Decimal("9.70")
    assert detail["closeCommission"] == "-0.15"
    assert detail["allocatedEntryFee"] == "-0.15"


def test_margin_projection_fails_closed_before_transfer():
    ok, reason, _ = transfer_safety(
        {"availableBalance": "1", "totalMarginBalance": "100", "totalMaintMargin": "10"}, Decimal("2")
    )
    assert not ok and reason == "INSUFFICIENT_AVAILABLE_BALANCE"
    ok, reason, projection = transfer_safety(
        {"availableBalance": "100", "totalMarginBalance": "20", "totalMaintMargin": "10"}, Decimal("1")
    )
    assert not ok and reason == "PROJECTED_LIQUIDATION_RISK_NOT_SAFE"
    assert projection["projectedRiskPct"] > 25
    ok, reason, _ = transfer_safety(
        {"availableBalance": "100", "totalMarginBalance": "100", "totalMaintMargin": "10"}, Decimal("1")
    )
    assert ok and reason == "SAFE"


def test_live_25_percent_sweep_posts_exactly_once(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    user = FakeUserRef(enabled=True, percent=25, minimum=0.9625)
    client = FakeClient()
    prepared = prepare_close_sweep(
        uid="u1", user_ref=user, client=client, intent_id="close-btc-1", symbol="BTCUSDT",
        position_side="LONG", close_quantity="1",
    )
    assert prepared is not None
    result = finalize_close_sweep(prepared, client=client, confirmed_order={
        "orderId": 99, "positionSide": "LONG", "side": "SELL", "status": "FILLED",
    })
    assert result["status"] == "SUCCEEDED"
    assert result["contribution"] == "0.9625"
    assert result["transferred"] == "0.9625"
    assert result["pendingSavings"] == "0"
    assert result["todayTransferred"] == "0.9625"
    assert len(client.transfers) == 1
    method, path, payload = client.transfers[0]
    assert method == "POST" and path == TRANSFER_PATH
    assert payload["kindType"] == "FUTURE_SPOT"
    assert payload["asset"] == "USDT"
    assert payload["amount"] == "0.9625"
    assert "user" not in payload
    assert payload["clientTranId"].startswith("tmpp2-")
    # Same logical close cannot create a second sweep booking or transfer.
    duplicate = prepare_close_sweep(
        uid="u1", user_ref=user, client=client, intent_id="close-btc-1", symbol="BTCUSDT",
        position_side="LONG", close_quantity="1",
    )
    assert duplicate is None
    assert len(client.transfers) == 1


def test_live_sweep_does_not_require_legacy_master_address(monkeypatch):
    """Spot V3 signs with the API wallet; legacy executionControls.masterAddress is not required."""
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    user = FakeUserRef(enabled=True, percent=5, minimum=0.1925)
    user.collection("executionControls").document("aster").data.pop("masterAddress", None)
    client = FakeClient()

    prepared = prepare_close_sweep(
        uid="u-no-legacy-master",
        user_ref=user,
        client=client,
        intent_id="close-without-legacy-master",
        symbol="BTCUSDT",
        position_side="LONG",
        close_quantity="1",
    )

    assert prepared is not None
    result = finalize_close_sweep(
        prepared,
        client=client,
        confirmed_order={
            "orderId": 99,
            "positionSide": "LONG",
            "side": "SELL",
            "status": "FILLED",
        },
    )
    assert result["status"] == "SUCCEEDED"
    assert result["contribution"] == "0.1925"
    assert result["transferred"] == "0.1925"
    assert len(client.transfers) == 1


def test_disabled_or_global_gate_off_never_posts(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "false")
    client = FakeClient()
    assert prepare_close_sweep(
        uid="u1", user_ref=FakeUserRef(enabled=True), client=client, intent_id="x1",
        symbol="BTCUSDT", position_side="LONG", close_quantity="1",
    ) is None
    assert client.transfers == []
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    assert prepare_close_sweep(
        uid="u2", user_ref=FakeUserRef(enabled=False), client=client, intent_id="x2",
        symbol="BTCUSDT", position_side="LONG", close_quantity="1",
    ) is None
    assert client.transfers == []


def test_uncertain_transfer_replays_at_most_once_with_same_id(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    monkeypatch.setattr("profit_sweep_live.time.sleep", lambda _: None)
    user = FakeUserRef(enabled=True, percent=25, minimum=0.9625)
    client = FakeClient(uncertain=True)
    prepared = prepare_close_sweep(
        uid="u3", user_ref=user, client=client, intent_id="close-uncertain", symbol="BTCUSDT",
        position_side="LONG", close_quantity="1",
    )
    result = finalize_close_sweep(prepared, client=client, confirmed_order={
        "orderId": 99, "positionSide": "LONG", "side": "SELL", "status": "FILLED",
    })
    assert result["status"] == "UNCERTAIN"
    assert result["contribution"] == "0.9625"
    assert result["pendingSavings"] == "0.9625"
    assert result["transferred"] == "0"
    assert len(client.transfers) == 2
    first_id = client.transfers[0][2]["clientTranId"]
    second_id = client.transfers[1][2]["clientTranId"]
    assert first_id == second_id


def test_live_unknown_replays_once_with_exact_same_client_tran_id(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    monkeypatch.setattr("profit_sweep_live.time.sleep", lambda _: None)

    class OneUnknownThenSuccessClient(FakeClient):
        def signed_spot_request(self, method, path, params):
            if method.upper() == "GET":
                return []
            self.transfers.append((method, path, dict(params)))
            if len(self.transfers) == 1:
                raise AsterSubmissionUncertain("Aster -1006: Execution status unknown")
            return {"tranId": 779, "status": "SUCCESS"}

    user = FakeUserRef(enabled=True, percent=5, minimum=0.1925)
    client = OneUnknownThenSuccessClient()
    prepared = prepare_close_sweep(
        uid="u-live-replay", user_ref=user, client=client,
        intent_id="close-live-replay", symbol="BTCUSDT",
        position_side="LONG", close_quantity="1",
    )
    result = finalize_close_sweep(
        prepared, client=client,
        confirmed_order={"orderId": 99, "positionSide": "LONG", "side": "SELL", "status": "FILLED"},
    )

    assert result["status"] == "SUCCEEDED"
    assert result["contribution"] == "0.1925"
    assert result["transferred"] == "0.1925"
    assert len(client.transfers) == 2
    assert client.transfers[0][2]["clientTranId"] == client.transfers[1][2]["clientTranId"]


def test_uncertain_transfer_reconciles_from_authoritative_income_history(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    user = FakeUserRef(enabled=True, percent=25, minimum=0.9625)
    client = FakeClient(
        uncertain=True,
        transfer_history=[{
            "incomeType": "TRANSFER",
            "income": "-0.96250000",
            "asset": "USDT",
            "time": int(time.time() * 1000),
            "tranId": "888",
        }],
    )
    prepared = prepare_close_sweep(
        uid="u4", user_ref=user, client=client, intent_id="close-reconciled", symbol="BTCUSDT",
        position_side="LONG", close_quantity="1",
    )
    result = finalize_close_sweep(prepared, client=client, confirmed_order={
        "orderId": 99, "positionSide": "LONG", "side": "SELL", "status": "FILLED",
    })
    assert result["status"] == "SUCCEEDED"
    assert result["contribution"] == "0.9625"
    assert result["transferred"] == "0.9625"
    assert result["pendingSavings"] == "0"
    assert len(client.transfers) == 1


def test_uncertain_transfer_reconciles_from_spot_transaction_history(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    user = FakeUserRef(enabled=True, percent=25, minimum=0.9625)
    client = FakeClient(
        uncertain=True,
        spot_history=[{
            "type": "TRANSFER_FUTURE_TO_SPOT",
            "balanceDelta": "0.96250000",
            "asset": "USDT",
            "time": int(time.time() * 1000),
            "tranId": "889",
        }],
    )
    prepared = prepare_close_sweep(
        uid="u5", user_ref=user, client=client, intent_id="close-spot-reconciled", symbol="BTCUSDT",
        position_side="LONG", close_quantity="1",
    )
    result = finalize_close_sweep(prepared, client=client, confirmed_order={
        "orderId": 99, "positionSide": "LONG", "side": "SELL", "status": "FILLED",
    })
    assert result["status"] == "SUCCEEDED"
    assert result["contribution"] == "0.9625"
    assert result["transferred"] == "0.9625"
    assert result["pendingSavings"] == "0"
    assert len(client.transfers) == 1


def test_failed_unknown_sweep_gets_one_idempotent_spot_recovery(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    user = FakeUserRef(enabled=True, percent=25)
    client = FakeClient()
    ledger_ref = user.collection("asterProfitSweeps").document("sweep-old")
    submitted = time.time()
    ledger = {
        "status": "FAILED_EXCHANGE",
        "reason": "Aster -1006: Execution status unknown",
        "sweepContribution": "0.75",
        "submittedAt": submitted,
    }
    ledger_ref.set(ledger)
    result = recover_failed_sweep(
        uid="u6",
        sweep_id="sweep-old",
        user_ref=user,
        ledger_ref=ledger_ref,
        ledger=ledger,
        client=client,
        spot_rows=[],
        futures_rows=[],
    )
    assert result["status"] == "SUCCEEDED"
    assert result["recovered"] is True
    assert len(client.transfers) == 1
    assert client.transfers[0][1] == TRANSFER_PATH
    assert client.transfers[0][2]["clientTranId"].startswith("tmpr-")
    second = recover_failed_sweep(
        uid="u6",
        sweep_id="sweep-old",
        user_ref=user,
        ledger_ref=ledger_ref,
        ledger={
            "status": "UNCERTAIN",
            "reason": "execution status unknown",
            "sweepContribution": "0.75",
            "submittedAt": submitted,
        },
        client=client,
        spot_rows=[],
        futures_rows=[],
    )
    assert second["status"] == "SUCCEEDED"
    assert second["recovered"] is True
    assert len(client.transfers) == 1



def test_recovery_replays_unknown_once_with_exact_same_client_tran_id(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    monkeypatch.setattr("profit_sweep_live.time.sleep", lambda _: None)

    class OneUnknownThenSuccessClient(FakeClient):
        def signed_spot_request(self, method, path, params):
            if method.upper() == "GET":
                return []
            self.transfers.append((method, path, dict(params)))
            if len(self.transfers) == 1:
                raise AsterSubmissionUncertain("Aster -1006: Execution status unknown")
            return {"tranId": 778, "status": "SUCCESS"}

    user = FakeUserRef(enabled=True, percent=25)
    client = OneUnknownThenSuccessClient()
    ledger_ref = user.collection("asterProfitSweeps").document("sweep-replay")
    ledger = {
        "status": "FAILED_EXCHANGE",
        "reason": "Aster -1006: Execution status unknown",
        "sweepContribution": "0.75",
        "submittedAt": time.time(),
    }
    ledger_ref.set(ledger)

    result = recover_failed_sweep(
        uid="u8",
        sweep_id="sweep-replay",
        user_ref=user,
        ledger_ref=ledger_ref,
        ledger=ledger,
        client=client,
        spot_rows=[],
        futures_rows=[],
    )

    assert result["status"] == "SUCCEEDED"
    assert result["recovered"] is True
    assert result["tranId"] == "778"
    assert len(client.transfers) == 2
    first_id = client.transfers[0][2]["clientTranId"]
    second_id = client.transfers[1][2]["clientTranId"]
    assert first_id == second_id
    assert first_id == _recovery_client_tran_id("u8", "sweep-replay")
    recovery = user.collection("asterProfitSweepRecoveries").document("sweep-replay").data
    assert recovery["status"] == "SUCCEEDED"
    assert recovery["submitAttempts"] == 2


def test_existing_single_unknown_recovery_claim_gets_only_same_id_replay(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    monkeypatch.setattr("profit_sweep_live.time.sleep", lambda _: None)
    user = FakeUserRef(enabled=True, percent=25)
    client = FakeClient()
    sweep_id = "sweep-existing-claim"
    recovery_id = _recovery_client_tran_id("u9", sweep_id)
    submitted = time.time()

    ledger_ref = user.collection("asterProfitSweeps").document(sweep_id)
    ledger = {
        "status": "UNCERTAIN",
        "reason": "Aster -1006: Execution status unknown",
        "sweepContribution": "0.75",
        "submittedAt": submitted - 30,
        "recoverySubmittedAt": submitted,
    }
    ledger_ref.set(ledger)
    user.collection("asterProfitSweepRecoveries").document(sweep_id).set({
        "uid": "u9",
        "sweepId": sweep_id,
        "clientTranId": recovery_id,
        "asset": "USDT",
        "kindType": "FUTURE_SPOT",
        "amount": "0.75",
        "status": "UNCERTAIN",
        "submittedAt": submitted,
        "reason": "Aster -1006: Execution status unknown",
    })

    result = recover_failed_sweep(
        uid="u9",
        sweep_id=sweep_id,
        user_ref=user,
        ledger_ref=ledger_ref,
        ledger=ledger,
        client=client,
        spot_rows=[],
        futures_rows=[],
    )

    assert result["status"] == "SUCCEEDED"
    assert result["recovered"] is True
    assert len(client.transfers) == 1
    assert client.transfers[0][2]["clientTranId"] == recovery_id
    recovery = user.collection("asterProfitSweepRecoveries").document(sweep_id).data
    assert recovery["submitAttempts"] == 2
    assert recovery["status"] == "SUCCEEDED"

def test_recovery_never_reposts_when_original_transfer_is_already_in_spot_history(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    user = FakeUserRef(enabled=True, percent=25)
    client = FakeClient()
    submitted_ms = int(time.time() * 1000)
    ledger_ref = user.collection("asterProfitSweeps").document("sweep-existing")
    ledger = {
        "status": "UNCERTAIN",
        "reason": "Aster -1007: execution status unknown",
        "sweepContribution": "0.5",
        "submittedAt": submitted_ms,
    }
    ledger_ref.set(ledger)
    result = recover_failed_sweep(
        uid="u7",
        sweep_id="sweep-existing",
        user_ref=user,
        ledger_ref=ledger_ref,
        ledger=ledger,
        client=client,
        spot_rows=[{
            "type": "TRANSFER_FUTURE_TO_SPOT",
            "balanceDelta": "0.50000000",
            "asset": "USDT",
            "time": submitted_ms + 1000,
            "tranId": "already-done",
        }],
        futures_rows=[],
    )
    assert result["status"] == "SUCCEEDED"
    assert result["tranId"] == "already-done"
    assert client.transfers == []



def test_profit_sweep_accumulates_small_parts_until_one_dollar(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    user = FakeUserRef(enabled=True, percent=5, minimum=1.0)
    client = FakeClient()
    prepared = prepare_close_sweep(
        uid="u-buffer", user_ref=user, client=client, intent_id="close-buffer-1",
        symbol="BTCUSDT", position_side="LONG", close_quantity="1",
    )
    result = finalize_close_sweep(
        prepared, client=client,
        confirmed_order={"orderId": 99, "positionSide": "LONG", "side": "SELL", "status": "FILLED"},
    )
    assert result["contribution"] == "0.1925"
    assert result["transferred"] == "0"
    assert result["pendingSavings"] == "0.1925"
    assert result["todayTransferred"] == "0"
    assert client.transfers == []


def test_profit_sweep_transfers_whole_threshold_and_keeps_remainder(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    user = FakeUserRef(enabled=True, percent=5, minimum=1.0)
    user.collection("asterProfitSweepState").document("current").set({
        "pendingSavings": "0.95",
        "todayTransferred": "0",
        "todayKey": "",
        "transferSequence": 0,
    })
    client = FakeClient()
    prepared = prepare_close_sweep(
        uid="u-remainder", user_ref=user, client=client, intent_id="close-remainder-1",
        symbol="BTCUSDT", position_side="LONG", close_quantity="1",
    )
    result = finalize_close_sweep(
        prepared, client=client,
        confirmed_order={"orderId": 99, "positionSide": "LONG", "side": "SELL", "status": "FILLED"},
    )
    assert result["contribution"] == "0.1925"
    assert result["transferred"] == "1"
    assert result["pendingSavings"] == "0.1425"
    assert result["todayTransferred"] == "1"
    assert len(client.transfers) == 1
    assert client.transfers[0][2]["amount"] == "1"


def test_profit_sweep_drains_multiple_full_blocks(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    user = FakeUserRef(enabled=True, percent=5, minimum=1.0)
    user.collection("asterProfitSweepState").document("current").set({
        "pendingSavings": "2.1775",
        "todayTransferred": "0",
        "todayKey": "",
        "transferSequence": 0,
    })
    client = FakeClient()
    prepared = prepare_close_sweep(
        uid="u-multi", user_ref=user, client=client, intent_id="close-multi-1",
        symbol="BTCUSDT", position_side="LONG", close_quantity="1",
    )
    result = finalize_close_sweep(
        prepared, client=client,
        confirmed_order={"orderId": 99, "positionSide": "LONG", "side": "SELL", "status": "FILLED"},
    )
    assert result["transferred"] == "2"
    assert result["transferCount"] == 2
    assert result["pendingSavings"] == "0.37"
    assert result["todayTransferred"] == "2"
    assert [row[2]["amount"] for row in client.transfers] == ["1", "1"]


def test_live_sweep_uses_configured_usdc_asset(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    user = FakeUserRef(enabled=True, percent=5, asset="USDC", minimum=0.1925)
    client = FakeClient()
    prepared = prepare_close_sweep(
        uid="u-usdc", user_ref=user, client=client, intent_id="close-usdc-1", symbol="BTCUSDT",
        position_side="LONG", close_quantity="1",
    )
    assert prepared is not None
    assert prepared.transfer_asset == "USDC"
    result = finalize_close_sweep(
        prepared, client=client,
        confirmed_order={"orderId": 99, "positionSide": "LONG", "side": "SELL", "status": "FILLED"},
    )
    assert result["status"] == "SUCCEEDED"
    assert len(client.transfers) == 1
    assert client.transfers[0][2]["asset"] == "USDC"
    ledger = user.collection("asterProfitSweeps").document(prepared.sweep_id).data
    assert ledger["asset"] == "USDC"


class StrategyNeutralMismatchClient(FakeClient):
    """Exchange position is authoritative even when legacy fill reconstruction disagrees."""
    def __init__(self, *, close_qty="50", realized="3"):
        super().__init__()
        self.close_qty = str(close_qty)
        self.realized = str(realized)
        self.pre = [{
            "id": 1, "orderId": 10, "symbol": "NEARUSDT", "positionSide": "LONG", "side": "BUY",
            "qty": "40", "price": "10", "commission": "-0.04", "commissionAsset": "USDT",
            "realizedPnl": "0", "time": 1000,
        }]
        self.post = [*self.pre, {
            "id": 2, "orderId": 99, "symbol": "NEARUSDT", "positionSide": "LONG", "side": "SELL",
            "qty": self.close_qty, "price": "11", "commission": "-0.03", "commissionAsset": "USDT",
            "realizedPnl": self.realized, "time": 2000,
        }]

    def position_risk(self, symbol=None):
        return [
            {"symbol": "NEARUSDT", "positionSide": "LONG", "positionAmt": "100", "entryPrice": "10"},
            # Opposite hedge/recovery leg deliberately remains open.
            {"symbol": "NEARUSDT", "positionSide": "SHORT", "positionAmt": "-80", "entryPrice": "15"},
        ]


def test_profit_sweep_uses_exchange_preclose_truth_when_legacy_inventory_mismatches(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    user = FakeUserRef(enabled=True, percent=5, asset="USDC", minimum=1.0)
    user.collection("asterProfitSweepState").document("current").set({
        "pendingSavings": "0.10396818",
        "todayTransferred": "0",
        "todayKey": "2026-10-04",
        "transferSequence": 0,
    })
    client = StrategyNeutralMismatchClient(close_qty="50", realized="3")

    prepared = prepare_close_sweep(
        uid="near-recovery",
        user_ref=user,
        client=client,
        intent_id="near-half-close",
        symbol="NEARUSDT",
        position_side="LONG",
        close_quantity="50",
    )

    assert prepared is not None
    assert prepared.open_quantity == Decimal("100")
    assert prepared.calculation_evidence == "PARTIAL_COST_EVIDENCE"

    result = finalize_close_sweep(
        prepared,
        client=client,
        confirmed_order={"orderId": 99, "positionSide": "LONG", "side": "SELL", "status": "FILLED"},
    )

    assert result["status"] == "BUFFERED"
    assert Decimal(result["contribution"]) > 0
    assert Decimal(result["pendingSavings"]) > Decimal("0.10396818")
    assert result["transferred"] == "0"
    assert client.transfers == []
    ledger = user.collection("asterProfitSweeps").document(prepared.sweep_id).data
    assert ledger["bufferBooked"] is True
    assert ledger["calculationEvidence"] == "PARTIAL_COST_EVIDENCE"
    assert ledger["calculation"]["closedQuantity"] == "50"


def test_strategy_neutral_profit_sweep_supports_25_50_75_100_percent_closes(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    for percentage, qty in ((25, "25"), (50, "50"), (75, "75"), (100, "100")):
        user = FakeUserRef(enabled=True, percent=5, asset="USDC", minimum=1.0)
        client = StrategyNeutralMismatchClient(close_qty=qty, realized="2")
        prepared = prepare_close_sweep(
            uid=f"pct-{percentage}",
            user_ref=user,
            client=client,
            intent_id=f"near-close-{percentage}",
            symbol="NEARUSDT",
            position_side="LONG",
            close_quantity=qty,
        )
        assert prepared is not None
        result = finalize_close_sweep(
            prepared,
            client=client,
            confirmed_order={"orderId": 99, "positionSide": "LONG", "side": "SELL", "status": "FILLED"},
        )
        assert result["status"] == "BUFFERED"
        assert Decimal(result["contribution"]) > 0
        assert result["transferred"] == "0"
        ledger = user.collection("asterProfitSweeps").document(prepared.sweep_id).data
        assert ledger["calculation"]["closedQuantity"] == qty


def test_strategy_neutral_fallback_never_saves_nonpositive_close(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    user = FakeUserRef(enabled=True, percent=5, asset="USDC", minimum=1.0)
    client = StrategyNeutralMismatchClient(close_qty="50", realized="-1")
    prepared = prepare_close_sweep(
        uid="near-loss",
        user_ref=user,
        client=client,
        intent_id="near-loss-half",
        symbol="NEARUSDT",
        position_side="LONG",
        close_quantity="50",
    )
    assert prepared is not None
    result = finalize_close_sweep(
        prepared,
        client=client,
        confirmed_order={"orderId": 99, "positionSide": "LONG", "side": "SELL", "status": "FILLED"},
    )
    assert result["status"] == "SKIPPED_NONPOSITIVE"
    state = user.collection("asterProfitSweepState").document("current").data
    assert Decimal(str(state.get("pendingSavings", "0"))) == Decimal("0")
    assert client.transfers == []


def test_today_blocked_recovery_adds_to_existing_buffer_once_without_spot_transfer(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    user = FakeUserRef(enabled=True, percent=5, asset="USDC", minimum=1.0)
    state = user.collection("asterProfitSweepState").document("current")
    state.set({
        "pendingSavings": "0.10396818",
        "todayTransferred": "0",
        "todayKey": "2026-10-04",
        "transferSequence": 0,
    })
    sweep_id = "blocked-near-today"
    ledger = user.collection("asterProfitSweeps").document(sweep_id)
    ledger.set({
        "uid": "u-recovery",
        "exchange": "ASTER",
        "closureId": "near-half",
        "symbol": "NEARUSDT",
        "positionSide": "LONG",
        "sweepPercent": 5.0,
        "asset": "USDC",
        "status": "BLOCKED_EVIDENCE",
        "bufferBooked": False,
        "reason": "Open inventory en sluitingshoeveelheid komen niet betrouwbaar overeen",
    })
    client = StrategyNeutralMismatchClient(close_qty="50", realized="3")
    # Recovery reads the already-confirmed fill set in one shot.
    client.calls = 1

    first = recover_blocked_close_to_buffer(
        uid="u-recovery",
        user_ref=user,
        client=client,
        sweep_id=sweep_id,
        exchange_order_id="99",
        expected_pre_close_quantity="100",
    )
    assert first["status"] == "BUFFERED"
    assert first["transferred"] == "0"
    assert Decimal(first["pendingSavings"]) > Decimal("0.10396818")
    assert client.transfers == []

    after_first = Decimal(first["pendingSavings"])
    second = recover_blocked_close_to_buffer(
        uid="u-recovery",
        user_ref=user,
        client=client,
        sweep_id=sweep_id,
        exchange_order_id="99",
        expected_pre_close_quantity="100",
    )
    assert second["status"] == "ALREADY_BOOKED"
    assert Decimal(second["pendingSavings"]) == after_first
    assert client.transfers == []
    restored = user.collection("asterProfitSweeps").document(sweep_id).data
    assert restored["recoveredProfitSweep"] is True
    assert restored["recoveryReason"] == "TODAY_BLOCKED_EVIDENCE_BACKFILL"
    assert restored["thresholdTransferStatus"] == "RECOVERY_BUFFERED_NO_TRANSFER"
