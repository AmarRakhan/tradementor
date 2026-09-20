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
    def __init__(self, *, enabled=True, percent=25):
        self.collections = {}
        control = self.collection("executionControls").document("aster")
        control.set({
            "masterAddress": "0x" + "a" * 40,
            "profitSweep": {"enabled": enabled, "sweepPercent": percent},
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
    user = FakeUserRef(enabled=True, percent=25)
    client = FakeClient()
    prepared = prepare_close_sweep(
        uid="u1", user_ref=user, client=client, intent_id="close-btc-1", symbol="BTCUSDT",
        position_side="LONG", close_quantity="1",
    )
    assert prepared is not None
    result = finalize_close_sweep(prepared, client=client, confirmed_order={
        "orderId": 99, "positionSide": "LONG", "side": "SELL", "status": "FILLED",
    })
    assert result == {"status": "SUCCEEDED", "contribution": "0.9625", "tranId": "777"}
    assert len(client.transfers) == 1
    method, path, payload = client.transfers[0]
    assert method == "POST" and path == TRANSFER_PATH
    assert payload["kindType"] == "FUTURE_SPOT"
    assert payload["asset"] == "USDT"
    assert payload["amount"] == "0.9625"
    assert "user" not in payload
    assert payload["clientTranId"].startswith("tmpp-")
    # Same logical close cannot create a second sweep booking or transfer.
    duplicate = prepare_close_sweep(
        uid="u1", user_ref=user, client=client, intent_id="close-btc-1", symbol="BTCUSDT",
        position_side="LONG", close_quantity="1",
    )
    assert duplicate is None
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


def test_uncertain_transfer_is_never_blind_retried(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    monkeypatch.setattr("profit_sweep_live.time.sleep", lambda _: None)
    user = FakeUserRef(enabled=True, percent=25)
    client = FakeClient(uncertain=True)
    prepared = prepare_close_sweep(
        uid="u3", user_ref=user, client=client, intent_id="close-uncertain", symbol="BTCUSDT",
        position_side="LONG", close_quantity="1",
    )
    result = finalize_close_sweep(prepared, client=client, confirmed_order={
        "orderId": 99, "positionSide": "LONG", "side": "SELL", "status": "FILLED",
    })
    assert result == {"status": "UNCERTAIN", "reconciliationStatus": "NOT_FOUND"}
    assert len(client.transfers) == 1


def test_uncertain_transfer_reconciles_from_authoritative_income_history(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    user = FakeUserRef(enabled=True, percent=25)
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
    assert result == {
        "status": "SUCCEEDED",
        "contribution": "0.9625",
        "tranId": "888",
        "reconciled": True,
    }
    assert len(client.transfers) == 1


def test_uncertain_transfer_reconciles_from_spot_transaction_history(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")
    user = FakeUserRef(enabled=True, percent=25)
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
    assert result == {
        "status": "SUCCEEDED",
        "contribution": "0.9625",
        "tranId": "889",
        "reconciled": True,
    }
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
