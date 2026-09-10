from __future__ import annotations

from copy import deepcopy

import aster_dynamic_hedge_sequence as sequence


class FakeSnapshot:
    def __init__(self, data): self.data = deepcopy(data)
    def to_dict(self): return deepcopy(self.data)


class FakeRef:
    def __init__(self, data=None): self.data = deepcopy(data or {}); self.writes = []
    def get(self): return FakeSnapshot(self.data)
    def set(self, value, merge=False):
        if merge: self.data.update(deepcopy(value))
        else: self.data = deepcopy(value)
        self.writes.append(deepcopy(value))


class FakeClient:
    def __init__(self):
        self.rows = [
            {"symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": 10, "markPrice": 100, "entryPrice": 100, "leverage": 20, "marginType": "cross"},
            {"symbol": "ETHUSDT", "positionSide": "SHORT", "positionAmt": -1, "markPrice": 100, "entryPrice": 100, "leverage": 20, "marginType": "cross"},
        ]
        self.account = {
            "totalMarginBalance": 500,
            "totalWalletBalance": 500,
            "totalUnrealizedProfit": 0,
            "totalMaintMargin": 20,
            "availableBalance": 200,
        }
        self.orders = []
        self.position_reads = 0
        self.account_reads = 0
    def position_risk(self):
        self.position_reads += 1
        return deepcopy(self.rows)
    def account_information(self):
        self.account_reads += 1
        return deepcopy(self.account)
    def open_orders(self): return deepcopy(self.orders)


class Clock:
    def __init__(self): self.value = 0.0
    def monotonic(self): return self.value
    def sleep(self, seconds): self.value += seconds


def test_delay_is_clamped_to_user_approved_two_to_five_seconds(monkeypatch):
    monkeypatch.setenv("ASTER_DYNAMIC_HEDGE_ACTION_DELAY_SECONDS", "0.2")
    assert sequence._delay_seconds() == 2.0
    monkeypatch.setenv("ASTER_DYNAMIC_HEDGE_ACTION_DELAY_SECONDS", "3.5")
    assert sequence._delay_seconds() == 3.5
    monkeypatch.setenv("ASTER_DYNAMIC_HEDGE_ACTION_DELAY_SECONDS", "9")
    assert sequence._delay_seconds() == 5.0


def test_sequence_executes_twenty_actions_in_one_scheduler_tick_even_with_budget_one(monkeypatch):
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE", "pendingIntent": {}})
    client = FakeClient()
    clock = Clock()
    calls = []

    def single_action(**kwargs):
        calls.append(kwargs)
        index = len(calls)
        if index <= 20:
            # Mimic the primitive's successful post-fill transition.
            ref.set({"ownershipState": "ADOPTING", "pendingIntent": {}}, merge=True)
            client.rows[1]["positionAmt"] -= 0.1
            return {
                "handled": True,
                "ordersSent": 1,
                "status": "ok",
                "action": "OPEN_SHORT",
                "symbol": "ETHUSDT",
                "proof": {"side": "SHORT", "sequence": index},
            }
        return {
            "handled": True,
            "ordersSent": 0,
            "status": "waiting",
            "action": "HOLD",
            "reason": "HEDGE_STABLE",
            "safetyStatus": "VEILIG",
        }

    monkeypatch.setattr(sequence, "run_dynamic_hedge_overlay", single_action)
    monkeypatch.setenv("ASTER_DYNAMIC_HEDGE_ACTION_DELAY_SECONDS", "2")
    monkeypatch.setenv("ASTER_DYNAMIC_HEDGE_SEQUENCE_WINDOW_SECONDS", "180")

    out = sequence.run_dynamic_hedge_sequence(
        client=client,
        control_ref=ref,
        settings=object(),
        uid="u",
        account=client.account_information(),
        positions=client.position_risk(),
        open_orders=[],
        timestamp_ms=1,
        order_budget=1,
        sleep_fn=clock.sleep,
        monotonic_fn=clock.monotonic,
    )

    assert out["ordersSent"] == 20
    assert out["sequenceOrdersSent"] == 20
    assert out["oneOrderPerTick"] is False
    assert len(out["sequenceActions"]) == 20
    assert len(calls) == 21
    assert all(call["order_budget"] is None for call in calls)
    assert clock.value == 40.0
    assert out["reason"] == "HEDGE_STABLE"
    assert ref.data["ownershipState"] == "DYNAMIC_HEDGE_ACTIVE"
    assert client.position_reads >= 41


def test_sequence_stops_immediately_when_manual_lock_appears_during_delay(monkeypatch):
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE", "pendingIntent": {}})
    client = FakeClient()
    clock = Clock()
    calls = []

    def single_action(**kwargs):
        calls.append(kwargs)
        ref.set({"ownershipState": "ADOPTING", "pendingIntent": {}}, merge=True)
        return {"handled": True, "ordersSent": 1, "status": "ok", "action": "OPEN_SHORT", "symbol": "ETHUSDT"}

    def sleep_and_lock(seconds):
        clock.sleep(seconds)
        ref.set({"ownershipState": "MANUAL_ACTION_LOCK"}, merge=True)

    monkeypatch.setattr(sequence, "run_dynamic_hedge_overlay", single_action)
    out = sequence.run_dynamic_hedge_sequence(
        client=client, control_ref=ref, settings=object(), uid="u",
        account=client.account_information(), positions=client.position_risk(), open_orders=[], timestamp_ms=1,
        order_budget=0, sleep_fn=sleep_and_lock, monotonic_fn=clock.monotonic,
    )
    assert out["ordersSent"] == 1
    assert out["reason"] == "MANUAL_OR_UNCERTAIN_LOCK_DURING_SEQUENCE"
    assert len(calls) == 1
    assert ref.data["ownershipState"] == "MANUAL_ACTION_LOCK"


def test_sequence_stops_fail_closed_if_post_action_exchange_state_is_not_stable(monkeypatch):
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE", "pendingIntent": {}})
    client = FakeClient()
    clock = Clock()

    def single_action(**kwargs):
        ref.set({"ownershipState": "ADOPTING", "pendingIntent": {}}, merge=True)
        return {"handled": True, "ordersSent": 1, "status": "ok", "action": "OPEN_SHORT", "symbol": "ETHUSDT"}

    reads = {"count": 0}
    original = client.position_risk
    def unstable_rows():
        rows = original()
        reads["count"] += 1
        if reads["count"] % 2 == 0:
            rows[1]["positionAmt"] -= 0.5
        return rows

    monkeypatch.setattr(sequence, "run_dynamic_hedge_overlay", single_action)
    client.position_risk = unstable_rows
    initial_positions = deepcopy(client.rows)
    out = sequence.run_dynamic_hedge_sequence(
        client=client, control_ref=ref, settings=object(), uid="u",
        account=client.account_information(), positions=initial_positions, open_orders=[], timestamp_ms=1,
        sleep_fn=clock.sleep, monotonic_fn=clock.monotonic,
    )
    assert out["ordersSent"] == 1
    assert out["reason"] == "POST_ACTION_RECONCILIATION_NOT_STABLE"
    assert ref.data["ownershipState"] == "ADOPTING"


def test_dry_run_never_loops_without_real_exchange_mutation(monkeypatch):
    ref = FakeRef({"enabled": True, "ownershipState": "DYNAMIC_HEDGE_ACTIVE"})
    client = FakeClient()
    calls = []
    def single_action(**kwargs):
        calls.append(kwargs)
        return {"handled": True, "ordersSent": 0, "wouldSendCount": 1, "status": "simulated", "action": "OPEN_SHORT"}
    monkeypatch.setattr(sequence, "run_dynamic_hedge_overlay", single_action)
    out = sequence.run_dynamic_hedge_sequence(
        client=client, control_ref=ref, settings=object(), uid="u",
        account=client.account_information(), positions=client.position_risk(), open_orders=[], timestamp_ms=1,
        dry_run=True, order_budget=1,
    )
    assert len(calls) == 1
    assert calls[0]["order_budget"] is None
    assert out["oneOrderPerTick"] is False
