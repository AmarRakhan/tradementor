from pathlib import Path

PATH = Path("cloud_api/aster_multi_bb.py")
text = PATH.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"Expected Multi BB marker missing: {old[:160]!r}")
    text = text.replace(old, new, 1)


replace_once(
'''class _PairAwareSettings:\n    def __init__(self,base:MultiBbConfig): object.__setattr__(self,"_base",base)\n    def __getattr__(self,name:str)->Any:\n        base:MultiBbConfig=object.__getattribute__(self,"_base")\n        symbol,side=_execution_context_from_stack(); override=base.pair_overrides.get(symbol,{}) if symbol else {}\n''',
'''class _PairAwareSettings:\n    def __init__(self,base:MultiBbConfig,blocked_side:str="",blocked_side_count:int=0):\n        object.__setattr__(self,"_base",base);object.__setattr__(self,"_blocked_side",str(blocked_side).upper())\n        object.__setattr__(self,"_blocked_side_count",max(0,int(blocked_side_count)))\n    def __getattr__(self,name:str)->Any:\n        base:MultiBbConfig=object.__getattribute__(self,"_base")\n        blocked_side=object.__getattribute__(self,"_blocked_side");blocked_count=object.__getattribute__(self,"_blocked_side_count")\n        if name=="long_slots" and blocked_side=="LONG": return blocked_count\n        if name=="short_slots" and blocked_side=="SHORT": return blocked_count\n        symbol,side=_execution_context_from_stack(); override=base.pair_overrides.get(symbol,{}) if symbol else {}\n        if side==blocked_side and name=="take_profit_enabled": return False\n        if side==blocked_side and name=="max_dca": return -1\n''')

replace_once(
'''    core_kwargs=dict(kwargs); core_kwargs["before_order"]=guarded_before_order\n''',
'''    blocked_side=str(kwargs.get("dynamic_hedge_blocked_side","")).upper()\n    blocked_count=sum(1 for row in positions if str(row.get("positionSide","")).upper()==blocked_side and abs(_finite(row.get("positionAmt",0)))>0) if blocked_side in {"LONG","SHORT"} else 0\n    core_kwargs=dict(kwargs); core_kwargs.pop("dynamic_hedge_blocked_side",None); core_kwargs["before_order"]=guarded_before_order\n''')

replace_once(
'''    extra={"pairOverrideCount":len(settings.pair_overrides),"takeProfitMode":settings.take_profit_mode,\n''',
'''    extra={"pairOverrideCount":len(settings.pair_overrides),"takeProfitMode":settings.take_profit_mode,\n        "dynamicHedgeBlockedSide":blocked_side or None,\n''')

replace_once(
'''    core_kwargs["ref"]=_CoreWriteProxy(ref,extra)\n    try: report=_core.run_multi_bb_step(settings=_PairAwareSettings(settings),**core_kwargs)\n''',
'''    core_kwargs["ref"]=_CoreWriteProxy(ref,extra)\n    try: report=_core.run_multi_bb_step(settings=_PairAwareSettings(settings,blocked_side,blocked_count),**core_kwargs)\n''')

PATH.write_text(text, encoding="utf-8")
print("Multi BB Dynamic Hedge side-ownership filter installed")
