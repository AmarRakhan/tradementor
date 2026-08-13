from order_coordinator import ExistingIntent, OrderIntent, coordinate_order
from portfolio_risk import PortfolioRiskDecision


NOW = 1_000_000
APPROVED = PortfolioRiskDecision(True, ("ok",), 100, 80, 20, 5, .1, .3)
REJECTED = PortfolioRiskDecision(False, ("risk",), 100, 5, 200, 100, .8, 2.1)


def intent(action="OPEN"):
    return OrderIntent("tm-1", "aster", "BTCUSDT", "LONG", action, 10, NOW)


def decide(item, **overrides):
    args = dict(
        existing=None, adapter_ready=True, reconciliation_ready=True,
        automation_enabled=True, risk=APPROVED, now_ms=NOW,
    )
    args.update(overrides)
    return coordinate_order(item, **args)


def test_new_risk_increasing_order_requires_every_gate():
    assert decide(intent()).action == "PROCEED"
    assert decide(intent(), adapter_ready=False).action == "BLOCK"
    assert decide(intent(), reconciliation_ready=False).action == "BLOCK"
    assert decide(intent(), automation_enabled=False).action == "BLOCK"
    assert decide(intent(), risk=REJECTED).action == "BLOCK"


def test_accepted_or_filled_intent_replays_instead_of_submitting_again():
    accepted = decide(intent(), existing=ExistingIntent("tm-1", "accepted", "order-9"))
    filled = decide(intent(), existing=ExistingIntent("tm-1", "filled", "order-9"))
    assert accepted.action == "REPLAY"
    assert filled.action == "REPLAY"
    assert accepted.exchange_order_id == "order-9"


def test_uncertain_intent_is_blocked_until_exchange_reconciliation():
    result = decide(intent(), existing=ExistingIntent("tm-1", "uncertain"))
    assert result.action == "BLOCK"
    assert "onzeker" in result.reason


def test_close_remains_available_when_automation_and_risk_budget_are_off():
    result = decide(intent("CLOSE"), automation_enabled=False, risk=REJECTED)
    assert result.action == "PROCEED"


def test_stale_intent_cannot_be_submitted():
    old = OrderIntent("tm-old", "aster", "BTCUSDT", "LONG", "OPEN", 10, NOW - 31_000)
    assert decide(old).action == "BLOCK"

