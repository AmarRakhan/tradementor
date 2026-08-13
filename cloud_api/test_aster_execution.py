from decimal import Decimal
import pytest
from aster_execution import plan_pair, execute_pair_once, execute_leg_once, execute_harvest_reset, execute_close_all, is_definite_contract_rejection, contract_brackets, planning_brackets, client_order_id
from aster_gateway import PositionSide


SYMBOL={"symbol":"BTCUSDT","filters":[
    {"filterType":"PRICE_FILTER","minPrice":"1","maxPrice":"1000000","tickSize":"0.1"},
    {"filterType":"LOT_SIZE","minQty":"0.00001","maxQty":"100","stepSize":"0.00001"},
    {"filterType":"MARKET_LOT_SIZE","minQty":"0.00001","maxQty":"100","stepSize":"0.00001"},
    {"filterType":"MIN_NOTIONAL","notional":"5"},
]}
BRACKETS=[{"notionalFloor":"0","notionalCap":"1000","initialLeverage":200,"maintMarginRatio":"0.004"}]


class Fake:
    def __init__(self, fail_short=False, fail_close=False): self.calls=[];self.fail_short=fail_short;self.fail_close=fail_close
    def change_margin_type(self,*a): self.calls.append(("margin",)+a)
    def change_leverage(self,*a): self.calls.append(("leverage",)+a)
    def submit_order_once(self,intent,**kwargs):
        self.calls.append((intent.action,intent.position_side.value))
        if self.fail_short and intent.action=="OPEN" and intent.position_side.value=="SHORT": raise RuntimeError("short failed")
        if self.fail_close and intent.action=="CLOSE": raise RuntimeError("close failed")
        return {"orderId":len(self.calls)},False


def test_plan_uses_exchange_minimums_and_max_leverage():
    p=plan_pair(SYMBOL,BRACKETS,65000,10)
    assert p.quantity==Decimal("0.00016") and p.leverage==200


def test_configured_twenty_five_is_not_halved_into_twelve_dollar_order():
    p=plan_pair(SYMBOL,BRACKETS,65000,25)
    assert Decimal("25") <= p.notional_per_leg <= Decimal("26.25")


def test_exchange_minimum_may_never_silently_inflate_user_amount():
    too_large={**SYMBOL,"filters":[
        {"filterType":"PRICE_FILTER","minPrice":"1","maxPrice":"1000000","tickSize":"0.1"},
        {"filterType":"LOT_SIZE","minQty":"0.001","maxQty":"100","stepSize":"0.001"},
        {"filterType":"MARKET_LOT_SIZE","minQty":"0.001","maxQty":"100","stepSize":"0.001"},
        {"filterType":"MIN_NOTIONAL","notional":"5"}]}
    with pytest.raises(ValueError,match="overschrijdt ingesteld bedrag"):
        plan_pair(too_large,BRACKETS,65000,10)


def test_pair_is_opened_long_then_short():
    f=Fake(); p=plan_pair(SYMBOL,BRACKETS,65000,10)
    result=execute_pair_once(f,p,id_prefix="tm-test",confirm=True,risk_approved=lambda _:True)
    assert [r["side"] for r in result]==["LONG","SHORT"]
    assert f.calls[-2:]==[("OPEN","LONG"),("OPEN","SHORT")]


def test_account_specific_notional_limit_steps_down_to_highest_accepted_leverage():
    class Limited(Fake):
        def change_leverage(self, symbol, leverage):
            self.calls.append(("leverage", symbol, leverage))
            if leverage > 100: raise RuntimeError("Aster -5018: maximum notional value limit")
    f=Limited();p=plan_pair(SYMBOL,BRACKETS,65000,10)
    result=execute_pair_once(f,p,id_prefix="tm-limit",confirm=True,risk_approved=lambda margin:margin<1)
    assert result[0]["leverage"]==100
    assert ("leverage","BTCUSDT",100) in f.calls


def test_single_leg_steps_down_on_aster_2027_before_opening():
    class Limited(Fake):
        def change_leverage(self, symbol, leverage):
            self.calls.append(("leverage", symbol, leverage))
            if leverage > 20:
                raise RuntimeError("Aster -2027: The current symbol's leverage exceeds the maximum supported leverage")
    f=Limited();p=plan_pair(SYMBOL,BRACKETS,65000,25)
    result=execute_leg_once(f,p,side=PositionSide.LONG,action="OPEN",id_prefix="tm-leg",confirm=True)
    assert result["leverage"]==20
    assert f.calls[-1]==("OPEN","LONG")


def test_long_initial_build_prefix_produces_valid_deterministic_client_order_id():
    prefix="s2i-Taby-1786305046145-49-bananas31"
    first=client_order_id(prefix,"open","long")
    second=client_order_id(prefix,"open","long")
    short=client_order_id(prefix,"open","short")
    assert first==second
    assert len(first)<=36
    assert first!=short


def test_long_initial_build_prefix_is_accepted_by_order_payload():
    class RecordingFake(Fake):
        def submit_order_once(self,intent,**kwargs):
            self.intent_id=intent.intent_id
            return super().submit_order_once(intent,**kwargs)
    f=RecordingFake();p=plan_pair(SYMBOL,BRACKETS,65000,20)
    execute_leg_once(f,p,side=PositionSide.LONG,action="OPEN",
                     id_prefix="s2i-Taby-1786305046145-49-bananas31",confirm=True)
    assert len(f.intent_id)<=36


def test_only_explicit_contract_rejections_may_skip_a_candidate():
    assert is_definite_contract_rejection(RuntimeError("Aster -5018: maximum notional value limit"))
    assert is_definite_contract_rejection(RuntimeError("Aster -2027: leverage exceeds maximum supported leverage"))
    assert is_definite_contract_rejection(RuntimeError(
        "Aster -4131: The counterparty's best price does not meet the PERCENT_PRICE filter limit."
    ))
    assert not is_definite_contract_rejection(RuntimeError("gateway timeout; order status unknown"))
    assert not is_definite_contract_rejection(RuntimeError("HTTP 503"))


def test_wrapped_definite_contract_rejection_remains_safe_to_skip():
    error = RuntimeError("SOLUSDT: geen door Aster geaccepteerde leverage gevonden")
    error.__cause__ = RuntimeError("Aster -5018: maximum notional value limit")
    assert is_definite_contract_rejection(error)


def test_missing_bulk_brackets_are_fetched_for_the_candidate_symbol():
    class BracketClient:
        def __init__(self): self.calls=[]
        def leverage_brackets(self,symbol):
            self.calls.append(symbol)
            return [{"symbol":symbol,"brackets":BRACKETS}]
    client=BracketClient()
    assert contract_brackets(client,[{"symbol":"BTCUSDT","brackets":BRACKETS}],"ETHUSDT")==BRACKETS
    assert client.calls==["ETHUSDT"]


def test_available_bulk_brackets_avoid_an_extra_exchange_request():
    class BracketClient:
        def leverage_brackets(self,symbol): raise AssertionError("geen extra request verwacht")
    assert contract_brackets(BracketClient(),[{"symbol":"BTCUSDT","brackets":BRACKETS}],"BTCUSDT")==BRACKETS


def test_missing_exchange_brackets_use_only_a_planning_ceiling():
    class EmptyBracketClient:
        def leverage_brackets(self,symbol): return []
    rows=planning_brackets(EmptyBracketClient(),[],"NEWUSDT",50)
    plan=plan_pair({**SYMBOL,"symbol":"NEWUSDT"},rows,65000,12)
    assert plan.leverage==50


def test_half_open_pair_is_compensated():
    f=Fake(fail_short=True);p=plan_pair(SYMBOL,BRACKETS,65000,10)
    with pytest.raises(RuntimeError,match="direct gecompenseerd"):
        execute_pair_once(f,p,id_prefix="tm-test",confirm=True,risk_approved=lambda _:True)
    assert f.calls[-1]==("CLOSE","LONG")


def test_uncertain_compensation_escalates():
    f=Fake(fail_short=True,fail_close=True);p=plan_pair(SYMBOL,BRACKETS,65000,10)
    with pytest.raises(RuntimeError,match="noodcontrole"):
        execute_pair_once(f,p,id_prefix="tm-test",confirm=True,risk_approved=lambda _:True)


def test_harvest_closes_then_reopens_same_side():
    f=Fake();p=plan_pair(SYMBOL,BRACKETS,65000,10)
    execute_harvest_reset(f,p,p,side=PositionSide.LONG,opposite_plan=p,id_prefix="tm-h",confirm=True)
    actions=[call for call in f.calls if call[0] in {"OPEN","CLOSE"}]
    assert actions[-2:]==[("CLOSE","LONG"),("OPEN","LONG")]


def test_failed_harvest_reset_flattens_opposite_side():
    class ResetFail(Fake):
        def submit_order_once(self,intent,**kwargs):
            self.calls.append((intent.action,intent.position_side.value))
            if intent.action=="OPEN": raise RuntimeError("reset failed")
            return {"orderId":len(self.calls)},False
    f=ResetFail();p=plan_pair(SYMBOL,BRACKETS,65000,10)
    with pytest.raises(RuntimeError,match="veilig gesloten"):
        execute_harvest_reset(f,p,p,side=PositionSide.LONG,opposite_plan=p,id_prefix="tm-h",confirm=True)
    assert f.calls[-1]==("CLOSE","SHORT")


def test_close_all_requires_confirmation_and_closes_every_leg():
    f=Fake();p=plan_pair(SYMBOL,BRACKETS,65000,10)
    with pytest.raises(ValueError): execute_close_all(f,[(p,PositionSide.LONG)],id_prefix="tm-all",confirm=False)
    result=execute_close_all(f,[(p,PositionSide.LONG),(p,PositionSide.SHORT)],id_prefix="tm-all",confirm=True)
    assert len(result)==2 and f.calls[-2:]==[("CLOSE","LONG"),("CLOSE","SHORT")]
