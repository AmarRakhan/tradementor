import time
from aster_multi_bb import run_multi_bb_step
from test_aster_multi_bb import Client, Ref, cfg

def _state(mark):
    pos={"symbol":"AAAUSDT","positionSide":"SHORT","positionAmt":"5","entryPrice":"100","markPrice":str(mark),"leverage":"100"}
    raw={"multiBbPositions":{"AAAUSDT|SHORT":{"cycleId":"c1","dcaCount":2,"lastBotFillPrice":100.4,"lastDcaFillPrice":100.4,"lastKnownQty":5,"lastKnownEntry":100,"cycleStartedAtMs":1,"dcaCatchupTargetCount":4,"dcaCatchupBaseAnchor":100.0,"dcaCatchupStartCount":0,"dcaCatchupDistance":.002,"dcaCatchupRemaining":2}}}
    return pos,raw

def test_recovered_short_cancels_remaining_catchup_instead_of_chasing():
    pos,raw=_state(99.9)
    result=run_multi_bb_step(client=Client(positions=[pos],prices={"AAAUSDT":99.9},leverage=100),ref=Ref(),raw_state=raw,settings=cfg(dcaDistance=.002,maxDca=10,maximumPositions=1,longSlots=0,shortSlots=1),uid="u",account={"availableBalance":"100"},positions=[pos],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    assert any(a["kind"]=="DCA_CATCHUP_CANCELLED_ON_RECOVERY" and a["cancelledLevels"]==2 for a in result["actions"])
    assert not any(a["kind"]=="DCA" for a in result["actions"])

def test_still_crossed_short_keeps_catchup_active():
    pos,raw=_state(100.7)
    result=run_multi_bb_step(client=Client(positions=[pos],prices={"AAAUSDT":100.7},leverage=100),ref=Ref(),raw_state=raw,settings=cfg(dcaDistance=.002,maxDca=10,maximumPositions=1,longSlots=0,shortSlots=1),uid="u",account={"availableBalance":"100"},positions=[pos],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    assert any(a["kind"]=="DCA" and a["number"]==3 for a in result["actions"])
    assert not any(a["kind"]=="DCA_CATCHUP_CANCELLED_ON_RECOVERY" for a in result["actions"])
