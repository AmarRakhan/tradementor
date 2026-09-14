from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import main
from aster_smart_rescue import build_position_state


class Snap:
    def __init__(self, ref): self.ref=ref
    def to_dict(self): return deepcopy(self.ref.data)


class Collection:
    def __init__(self): self.rows=[]
    def add(self,row): self.rows.append(deepcopy(row))


class Ref:
    def __init__(self,data): self.data=deepcopy(data); self.updates=[]; self.audit=Collection()
    def get(self): return Snap(self)
    def set(self,row,merge=True):
        self.updates.append((deepcopy(row),merge))
        if isinstance(merge,list):
            for key in merge: self.data[key]=deepcopy(row[key])
        elif merge:
            self.data.update(deepcopy(row))
        else: self.data=deepcopy(row)
    def collection(self,name):
        assert name=="audit"; return self.audit


class ReadOnlyClient:
    def __init__(self,position): self.position=position; self.order_calls=0
    def position_risk(self,symbol=None):
        return [deepcopy(self.position)] if symbol in {None,self.position["symbol"]} else []
    def submit_order_once(self,*_args,**_kwargs):
        self.order_calls+=1; raise AssertionError("Smart Rescue extension mag nooit een order versturen")


def smart_outer():
    smart=build_position_state(initial_entry_price=100,start_margin_usd=.15,rescue_range_percent=5,
        dca_count=10,order_growth_multiplier=1.35,trailing_recovery_percent=.1,config_version=7)
    return {"cycleId":"sol-cycle-1","smartRescue":smart,"lastKnownQty":1.5,"lastKnownEntry":97.25,"leverage":100}


def install(monkeypatch,ref,client):
    monkeypatch.setattr(main,"aster_strategy2_reference",lambda _uid:ref)
    monkeypatch.setattr(main,"load_aster_secret",lambda _user:SimpleNamespace(signer_address="0x1"))
    monkeypatch.setattr(main,"local_eip712_signer",lambda _secret:None)
    monkeypatch.setattr(main,"AsterV3Client",lambda **_kwargs:client)
    monkeypatch.setattr(main,"_strategy2_order_queue_enabled",lambda _raw:False)
    monkeypatch.setattr(main,"_acquire_mexc_automation_lease",lambda _ref:True)


def test_get_and_extend_active_cycle_without_order_submission(monkeypatch):
    outer=smart_outer(); original=deepcopy(outer["smartRescue"]["levels"])
    ref=Ref({"multiBbPositions":{"SOLUSDT|LONG":outer}})
    client=ReadOnlyClient({"symbol":"SOLUSDT","positionSide":"LONG","positionAmt":"1.5","entryPrice":"97.25","markPrice":"95","leverage":"100"})
    install(monkeypatch,ref,client)
    current=main.get_smart_rescue_active_cycle("SOL/USDT",{"uid":"u"})
    assert current["active"] is True and current["ordersSent"]==0
    result=main.extend_smart_rescue_active_cycle("SOLUSDT",{
        "cycleId":"sol-cycle-1","newTotalDca":25,"newRescueRangePercent":8,"futureGrowthMultiplier":1.1,
    },{"uid":"u"})
    assert result["saved"] is True and result["ordersSent"]==0 and client.order_calls==0
    saved=ref.data["multiBbPositions"]["SOLUSDT|LONG"]["smartRescue"]
    assert saved["levels"][:10]==original
    assert len(saved["levels"])==25
    assert ref.audit.rows[-1]["event"]=="SMART_RESCUE_LADDER_EXTENDED"


def test_stale_cycle_id_fails_before_state_update(monkeypatch):
    outer=smart_outer(); ref=Ref({"multiBbPositions":{"SOLUSDT|LONG":outer}})
    client=ReadOnlyClient({"symbol":"SOLUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"100","markPrice":"99","leverage":"100"})
    install(monkeypatch,ref,client)
    with pytest.raises(HTTPException) as exc:
        main.extend_smart_rescue_active_cycle("SOLUSDT",{
            "cycleId":"old-cycle","newTotalDca":25,"newRescueRangePercent":8,"futureGrowthMultiplier":1.1,
        },{"uid":"u"})
    assert exc.value.status_code==409
    assert len(ref.data["multiBbPositions"]["SOLUSDT|LONG"]["smartRescue"]["levels"])==10


def test_closed_or_non_smart_position_is_rejected(monkeypatch):
    ref=Ref({"multiBbPositions":{"SOLUSDT|LONG":{"cycleId":"legacy"}}})
    client=ReadOnlyClient({"symbol":"SOLUSDT","positionSide":"LONG","positionAmt":"0","entryPrice":"100","markPrice":"99","leverage":"100"})
    install(monkeypatch,ref,client)
    with pytest.raises(HTTPException) as exc:
        main.get_smart_rescue_active_cycle("SOLUSDT",{"uid":"u"})
    assert exc.value.status_code==409
