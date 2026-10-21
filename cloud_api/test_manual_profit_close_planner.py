import unittest
from manual_profit_close_planner import build_profit_close_plan

F = {"BTCUSDT":{"stepSize":"1","minQty":"2","minNotional":"0"}}
def row(side, pnl, qty=100):
    return {"symbol":"BTCUSDT","positionSide":side,"positionAmt":str(qty),"unRealizedProfit":str(pnl),"markPrice":"10"}

class ProfitClosePlannerTests(unittest.TestCase):
    def test_short_alone_despite_losing_long(self):
        p=build_profit_close_plan([row("SHORT",2),row("LONG",-5)],25,F,hedge_links={"BTCUSDT":True})
        self.assertEqual([(x["side"], x["quantity"]) for x in p["selected"]],[("SHORT","25")])
    def test_profitable_pair_closes_both(self):
        p=build_profit_close_plan([row("SHORT",-1),row("LONG",3)],50,F,hedge_links={"BTCUSDT":True})
        self.assertEqual({x["side"] for x in p["selected"]},{"LONG","SHORT"})
    def test_insufficient_minimum_skips_without_trade(self):
        p=build_profit_close_plan([row("SHORT",1,qty=4)],25,F)
        self.assertFalse(p["selected"])
        self.assertEqual(p["skipped"][0]["reason"],"below_exchange_minimum")
    def test_more_percentage_enables_minimum(self):
        p=build_profit_close_plan([row("SHORT",1,qty=4)],50,F)
        self.assertEqual(p["selected"][0]["quantity"],"2")
    def test_exact_fifty_cents_not_eligible(self):
        self.assertFalse(build_profit_close_plan([row("SHORT",0.50)],100,F)["selected"])
    def test_unverified_link_protects_long_not_short(self):
        p=build_profit_close_plan([row("LONG",3),row("SHORT",1)],25,F)
        self.assertEqual([x["side"] for x in p["selected"]],["SHORT"])
    def test_explicit_unverified_pair_never_closes_long_alone(self):
        p=build_profit_close_plan([row("LONG",3),row("SHORT",1)],25,F,hedge_links={"BTCUSDT":False})
        self.assertEqual([x["side"] for x in p["selected"]],["SHORT"])
    def test_exchange_info_contract_filters(self):
        from manual_profit_close_planner import filters_from_aster_exchange_info
        info = {"symbols":[{"symbol":"BTCUSDT","status":"TRADING","filters":[{"filterType":"LOT_SIZE","minQty":"2","maxQty":"1000","stepSize":"1"},{"filterType":"MARKET_LOT_SIZE","minQty":"2","maxQty":"200","stepSize":"1"},{"filterType":"MIN_NOTIONAL","notional":"10"}]}]}
        filters=filters_from_aster_exchange_info(info)
        self.assertEqual(filters["BTCUSDT"]["minQty"],"2")
        self.assertEqual(filters["BTCUSDT"]["minNotional"],"10")
        self.assertEqual(build_profit_close_plan([row("SHORT",1,qty=4)],25,filters)["selected"],[])
    def test_reversed_order_same_pair(self):
        p=build_profit_close_plan([row("SHORT",-1),row("LONG",3)],25,F,hedge_links={"BTCUSDT":True})
        self.assertEqual({x["side"] for x in p["selected"]},{"SHORT","LONG"})

if __name__=="__main__": unittest.main()
