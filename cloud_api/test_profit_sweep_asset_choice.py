"""Profit Sparen 3.1 (build 647): drempeltransfer kiest zelf het asset met vrij Futures-saldo.

Oorzaak 24-10: een account met marge in USDC en transferAsset=USDT bleef sinds 16-10 hangen op
Aster -1006/032206 ("exceeds the limit for futures account available balance"), als UNCERTAIN.
"""
from decimal import Decimal

from aster_gateway import AsterApiError
from profit_sweep_live import (
    PreparedSweep,
    TRANSFER_PATH,
    _definite_transfer_rejection,
    asset_free_balances,
    choose_transfer_asset,
    drain_profit_savings_buffer,
)
from test_profit_sweep_live import FakeUserRef

REJECT = "Aster Spot -1006: 032206:Transfer amount exceeds the limit for futures account available balance"


def _account(usdt="0", usdc="50"):
    return {
        "availableBalance": "100", "totalMarginBalance": "100", "totalMaintMargin": "10",
        "assets": [
            {"asset": "USDT", "availableBalance": usdt, "maxWithdrawAmount": usdt},
            {"asset": "USDC", "availableBalance": usdc, "maxWithdrawAmount": usdc},
            {"asset": "BTC", "availableBalance": "1", "maxWithdrawAmount": "1"},
        ],
    }


class AssetClient:
    """Aster-fake: weigert een transfer als het asset niet genoeg vrij saldo heeft."""

    def __init__(self, account, *, history=None):
        self.account = account
        self.transfers = []
        self.history = list(history or [])

    def account_information(self):
        return self.account

    def income_history(self, **kwargs):
        return list(self.history)

    def signed_spot_request(self, method, path, params):
        if method.upper() == "GET":
            return []
        assert path == TRANSFER_PATH
        self.transfers.append(dict(params))
        free = asset_free_balances(self.account).get(params["asset"], Decimal("0"))
        if free < Decimal(params["amount"]):
            raise AsterApiError(REJECT)
        return {"tranId": 9000 + len(self.transfers), "status": "SUCCESS"}


def _prepared(user_ref, asset="USDT"):
    return PreparedSweep(
        uid="u1", sweep_id="buffer-reconcile", intent_id="buffer-reconcile", client_tran_id="",
        symbol="", position_side="", sweep_percent=Decimal("5"), transfer_asset=asset,
        minimum_transfer=Decimal("1"), user_ref=user_ref,
        ledger_ref=user_ref.collection("asterProfitSweeps").document("_buffer_reconcile"),
        open_quantity=Decimal("0"), entry_commission_pool=Decimal("0"), cycle_start_ms=0,
        negative_funding=Decimal("0"), evidence_entry_fees=Decimal("0"),
        evidence_funding=Decimal("0"), evidence_other_costs=Decimal("0"),
    )


def _state(user_ref):
    return user_ref.collection("asterProfitSweepState").document("current").data


def _live(monkeypatch):
    monkeypatch.setenv("ASTER_PROFIT_SWEEP_LIVE_ENABLED", "true")


def test_rejection_text_is_definite_not_unknown():
    assert _definite_transfer_rejection(REJECT)
    assert not _definite_transfer_rejection("Aster Spot gaf 503; uitvoeringsstatus is onbekend")


def test_choose_prefers_stored_asset_then_other():
    assert choose_transfer_asset(_account("5", "5"), Decimal("1"), "USDT")[0] == "USDT"
    assert choose_transfer_asset(_account("5", "5"), Decimal("1"), "USDC")[0] == "USDC"
    assert choose_transfer_asset(_account("0", "5"), Decimal("1"), "USDT")[0] == "USDC"
    assert choose_transfer_asset(_account("5", "0"), Decimal("1"), "USDC")[0] == "USDT"
    assert choose_transfer_asset(_account("0.5", "0.5"), Decimal("1"), "USDT")[0] is None
    assert choose_transfer_asset(_account("0", "5"), Decimal("1"), "USDT", allow_switch=False)[0] is None


def test_without_asset_rows_old_behaviour_is_kept():
    acc = {"availableBalance": "100", "totalMarginBalance": "100", "totalMaintMargin": "10"}
    assert choose_transfer_asset(acc, Decimal("1"), "USDT")[0] == "USDT"


def test_conservative_min_of_max_withdraw_and_available():
    acc = {"assets": [{"asset": "USDT", "availableBalance": "5", "maxWithdrawAmount": "0.4"}]}
    assert asset_free_balances(acc)["USDT"] == Decimal("0.4")


def test_usdt_user_with_usdc_margin_now_transfers_usdc(monkeypatch):
    _live(monkeypatch)
    ref = FakeUserRef(asset="USDT")
    _state(ref).update({"pendingSavings": "2.04"})
    client = AssetClient(_account(usdt="0", usdc="50"))
    out = drain_profit_savings_buffer(_prepared(ref, "USDT"), client=client)
    assert out["transferCount"] == 2 and out["pendingSavings"] == "0.04"
    assert [t["asset"] for t in client.transfers] == ["USDC", "USDC"]
    assert _state(ref)["lastTransferAsset"] == "USDC"
    assert _state(ref)["inFlight"] is None


def test_existing_usdt_and_usdc_users_unchanged(monkeypatch):
    _live(monkeypatch)
    for stored in ("USDT", "USDC"):
        ref = FakeUserRef(asset=stored)
        _state(ref).update({"pendingSavings": "1.2"})
        client = AssetClient(_account(usdt="50", usdc="50"))
        out = drain_profit_savings_buffer(_prepared(ref, stored), client=client)
        assert out["transferCount"] == 1
        assert [t["asset"] for t in client.transfers] == [stored]


def test_stuck_rejected_claim_from_16_10_is_released_and_switches(monkeypatch):
    """Exact de vastgelopen claim van de melder: UNCERTAIN met 032206-reden, al ingediend in USDT."""
    _live(monkeypatch)
    ref = FakeUserRef(asset="USDT")
    claim = {
        "claimId": "c1", "sequence": 1, "amount": "1", "asset": "USDT", "clientTranId": "tmpp2-x",
        "status": "UNCERTAIN", "reconciliationStatus": "NOT_FOUND",
        "reason": REJECT + "; uitvoeringsstatus is onbekend en mag niet blind opnieuw worden verstuurd",
        "submittedAt": "2026-10-24T06:10:07.096017+00:00",
    }
    _state(ref).update({"pendingSavings": "2.03710714", "transferSequence": 1, "inFlight": claim})
    ref.collection("asterProfitSweepTransfers").document("c1").set(dict(claim))
    client = AssetClient(_account(usdt="0", usdc="50"))
    out = drain_profit_savings_buffer(_prepared(ref, "USDT"), client=client)
    assert out["transferCount"] == 2
    assert client.transfers[0]["asset"] == "USDC"
    assert client.transfers[0]["clientTranId"] == "tmpp2-x"
    assert Decimal(out["pendingSavings"]) == Decimal("0.03710714")


def test_truly_unknown_claim_never_switches_asset(monkeypatch):
    """Onbekende uitkomst (503): mag nog landen in USDT, dus nooit een tweede transfer in USDC."""
    _live(monkeypatch)
    ref = FakeUserRef(asset="USDT")
    claim = {
        "claimId": "c2", "sequence": 1, "amount": "1", "asset": "USDT", "clientTranId": "tmpp2-y",
        "status": "UNCERTAIN", "reason": "Aster Spot gaf 503; uitvoeringsstatus is onbekend",
        "submittedAt": "2026-10-24T06:10:07.096017+00:00",
    }
    _state(ref).update({"pendingSavings": "1.5", "transferSequence": 1, "inFlight": claim})
    ref.collection("asterProfitSweepTransfers").document("c2").set(dict(claim))
    client = AssetClient(_account(usdt="0", usdc="50"))
    out = drain_profit_savings_buffer(_prepared(ref, "USDT"), client=client)
    assert out["status"] == "BLOCKED_ASSET_BALANCE"
    assert client.transfers == []


def test_no_free_balance_anywhere_blocks_without_submitting(monkeypatch):
    _live(monkeypatch)
    ref = FakeUserRef(asset="USDT")
    _state(ref).update({"pendingSavings": "1.5"})
    client = AssetClient(_account(usdt="0.2", usdc="0.3"))
    out = drain_profit_savings_buffer(_prepared(ref, "USDT"), client=client)
    assert out["status"] == "BLOCKED_ASSET_BALANCE"
    assert client.transfers == []
    flight = _state(ref)["inFlight"]
    assert flight["status"] == "BLOCKED_ASSET_BALANCE"
    assert flight["assetBalances"] == {"USDT": "0.2", "USDC": "0.3"}


def test_aster_refusal_is_not_replayed(monkeypatch):
    """Aster weigert ondanks onze check: één poging, geen replay met hetzelfde id, status REJECTED_BALANCE."""
    _live(monkeypatch)
    ref = FakeUserRef(asset="USDT")
    _state(ref).update({"pendingSavings": "1.5"})

    class Refusing(AssetClient):
        def signed_spot_request(self, method, path, params):
            if method.upper() == "GET":
                return []
            self.transfers.append(dict(params))
            raise AsterApiError(REJECT)

    client = Refusing(_account(usdt="50", usdc="0"))
    out = drain_profit_savings_buffer(_prepared(ref, "USDT"), client=client)
    assert out["status"] == "REJECTED_BALANCE"
    assert len(client.transfers) == 1
    assert _state(ref)["inFlight"]["status"] == "REJECTED_BALANCE"
    assert Decimal(_state(ref)["pendingSavings"]) == Decimal("1.5")
