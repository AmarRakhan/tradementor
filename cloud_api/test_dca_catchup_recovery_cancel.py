import time
import pytest

from aster_multi_bb import run_multi_bb_step
from test_aster_multi_bb import Client, Ref, cfg


def _state(mark):
    pos={"symbol":"AAAUSDT","positionSide":"SHORT","positionAmt":"5","entryPrice":"100","markPrice":str(mark),"leverage":"100"}
    raw={"multiBbPositions":{"AAAUSDT|SHORT":{
        "cycleId":"c1","dcaCount":2,"lastBotFillPrice":100.4,"lastDcaFillPrice":100.4,
        "lastKnownQty":5,"lastKnownEntry":100,"cycleStartedAtMs":1,
        # Legacy backlog left behind by the old catch-up implementation.
        "dcaCatchupTargetCount":4,"dcaCatchupBaseAnchor":100.0,
        "dcaCatchupStartCount":0,"dcaCatchupDistance":.002,"dcaCatchupRemaining":2,
    }}}
    return pos,raw


def test_recovered_short_ignores_stale_catchup_and_does_not_chase_old_levels():
    pos,raw=_state(99.9)
    result=run_multi_bb_step(
        client=Client(positions=[pos],prices={"AAAUSDT":99.9},leverage=100),
        ref=Ref(),raw_state=raw,
        settings=cfg(dcaDistance=.002,maxDca=10,maximumPositions=1,longSlots=0,shortSlots=1),
        uid="u",account={"availableBalance":"100"},positions=[pos],open_orders=[],
        timestamp_ms=int(time.time()*1000),dry_run=True,
    )
    assert not any(a["kind"]=="DCA" for a in result["actions"])
    assert not any(a["kind"]=="DCA_CATCHUP_QUEUED" for a in result["actions"])
    assert not any(a["kind"]=="DCA_CATCHUP_CANCELLED_ON_RECOVERY" for a in result["actions"])


def test_crossed_short_executes_only_next_fill_anchored_dca():
    pos,raw=_state(100.7)
    result=run_multi_bb_step(
        client=Client(positions=[pos],prices={"AAAUSDT":100.7},leverage=100),
        ref=Ref(),raw_state=raw,
        settings=cfg(dcaDistance=.002,maxDca=10,maximumPositions=1,longSlots=0,shortSlots=1),
        uid="u",account={"availableBalance":"100"},positions=[pos],open_orders=[],
        timestamp_ms=int(time.time()*1000),dry_run=True,
    )
    dcas=[a for a in result["actions"] if a["kind"]=="DCA"]
    assert len(dcas)==1
    assert dcas[0]["number"]==3
    assert dcas[0]["trigger"]==pytest.approx(100.4*1.002)
    assert dcas[0]["catchup"] is False
    assert dcas[0]["catchupTargetCount"]==3
    assert not any(a["kind"]=="DCA_CATCHUP_QUEUED" for a in result["actions"])
