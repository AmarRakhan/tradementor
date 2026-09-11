from copy import deepcopy

from aster_dynamic_hedge_api import DynamicHedgeToggleRequest, install_aster_dynamic_hedge_routes


class FakeSnapshot:
    def __init__(self, data): self._data = deepcopy(data)
    def to_dict(self): return deepcopy(self._data)


class FakeRef:
    def __init__(self): self.data = {}
    def get(self): return FakeSnapshot(self.data)
    def set(self, payload, merge=False):
        if merge: self.data.update(deepcopy(payload))
        else: self.data = deepcopy(payload)


class FakeRoot:
    def __init__(self, ref): self.ref = ref
    def collection(self, _name): return self
    def document(self, _name): return self.ref


class FakeApp:
    def __init__(self): self.routes = {}
    def get(self, path):
        def decorate(fn): self.routes[("GET", path)] = fn; return fn
        return decorate
    def put(self, path):
        def decorate(fn): self.routes[("PUT", path)] = fn; return fn
        return decorate


class FakeClient:
    def __init__(self, account, positions, orders=None):
        self.account = deepcopy(account); self.positions = deepcopy(positions); self.orders = deepcopy(orders or [])
        self.order_calls = 0
    def account_information(self): return deepcopy(self.account)
    def position_risk(self): return deepcopy(self.positions)
    def open_orders(self): return deepcopy(self.orders)


def pos(symbol, side, notional, mark=100):
    qty = notional / mark
    return {"symbol": symbol, "positionSide": side, "positionAmt": qty if side == "LONG" else -qty,
            "markPrice": mark, "entryPrice": mark, "leverage": 20, "marginType": "cross"}


def setup(available=0):
    app = FakeApp(); store = FakeRef()
    account = {"totalMarginBalance": 300, "totalWalletBalance": 300,
               "totalUnrealizedProfit": 0, "totalMaintMargin": 30,
               "availableBalance": available}
    client = FakeClient(account, [pos("BTCUSDT", "LONG", 1000), pos("ETHUSDT", "SHORT", 300)])
    install_aster_dynamic_hedge_routes(
        app,
        authenticated_user=lambda: {"uid": "u"},
        user_reference=lambda _user: FakeRoot(store),
        client_factory=lambda _user, _live: client,
    )
    return app, store, client


def test_monitoring_works_when_dynamic_mode_is_off_and_available_is_zero():
    app, store, client = setup(available=0)
    state = app.routes[("GET", "/v1/me/aster/dynamic-hedge/state")]({"uid": "u"})
    assert state["monitoringAlwaysActive"] is True
    assert state["enabled"] is False
    assert state["safetyStatus"] == "VEILIG"
    assert state["marginBufferUsd"] == 270
    assert state["hedgeCoveragePercent"] == 30
    assert client.order_calls == 0


def test_enable_only_adopts_and_never_opens_or_closes_positions():
    app, store, client = setup()
    enable = app.routes[("PUT", "/v1/me/aster/dynamic-hedge/enabled")]
    state = enable(DynamicHedgeToggleRequest(enabled=True, confirm=True), {"uid": "u"})
    assert state["enabled"] is True
    assert state["adoptedPositionCount"] == 2
    assert store.data["lastAction"] in {"ADOPTION_STARTED", "ADOPTION_CONFIRMED"}
    assert client.order_calls == 0


def test_two_stable_reads_confirm_ownership_without_trading():
    app, store, client = setup()
    enable = app.routes[("PUT", "/v1/me/aster/dynamic-hedge/enabled")]
    get_state = app.routes[("GET", "/v1/me/aster/dynamic-hedge/state")]
    enable(DynamicHedgeToggleRequest(enabled=True, confirm=True), {"uid": "u"})
    state = get_state({"uid": "u"})
    assert state["ownershipState"] == "DYNAMIC_HEDGE_ACTIVE"
    assert client.order_calls == 0


def test_exchange_change_reenters_adoption_before_any_action():
    app, store, client = setup()
    enable = app.routes[("PUT", "/v1/me/aster/dynamic-hedge/enabled")]
    get_state = app.routes[("GET", "/v1/me/aster/dynamic-hedge/state")]
    enable(DynamicHedgeToggleRequest(enabled=True, confirm=True), {"uid": "u"})
    get_state({"uid": "u"})
    client.positions[0]["positionAmt"] *= 1.1
    state = get_state({"uid": "u"})
    assert state["ownershipState"] == "ADOPTING"
    assert state["lastAction"] == "ADOPTION_RECONCILE"
    assert client.order_calls == 0


def test_disable_leaves_exchange_positions_untouched():
    app, store, client = setup()
    enable = app.routes[("PUT", "/v1/me/aster/dynamic-hedge/enabled")]
    before = deepcopy(client.positions)
    enable(DynamicHedgeToggleRequest(enabled=True, confirm=True), {"uid": "u"})
    state = enable(DynamicHedgeToggleRequest(enabled=False, confirm=True), {"uid": "u"})
    assert state["enabled"] is False
    assert state["ownershipState"] == "NORMAL"
    assert client.positions == before
    assert client.order_calls == 0


def test_unreliable_maintenance_data_cannot_enable():
    app, store, client = setup()
    del client.account["totalMaintMargin"]
    enable = app.routes[("PUT", "/v1/me/aster/dynamic-hedge/enabled")]
    try:
        enable(DynamicHedgeToggleRequest(enabled=True, confirm=True), {"uid": "u"})
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409
    else:
        raise AssertionError("Expected fail-closed enable rejection")
