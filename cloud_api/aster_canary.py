"""Safety helpers for the explicitly confirmed Aster open/fill/close canary."""
from __future__ import annotations
from typing import Any

def existing_canary_action(status:str|None)->str:
    value=str(status or "").upper()
    if value in {"OPENING","OPENED","CLOSING","UNKNOWN"}: return "block"
    if value=="COMPLETED": return "replay"
    return "proceed"

def choose_flat_symbol(exchange_info:dict[str,Any],prices:dict[str,float],active_symbols:set[str])->dict[str,Any]:
    rows=[x for x in exchange_info.get("symbols",[]) if isinstance(x,dict)]
    preferred=("BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT")
    by_symbol={str(x.get("symbol","")).upper():x for x in rows}
    ordered=[by_symbol[x] for x in preferred if x in by_symbol]+[x for x in rows if str(x.get("symbol","")).upper() not in preferred]
    for row in ordered:
        symbol=str(row.get("symbol","")).upper()
        if symbol and symbol not in active_symbols and prices.get(symbol,0)>0 and str(row.get("status","TRADING")).upper()=="TRADING":
            return row
    raise ValueError("Geen vlak, verhandelbaar Aster-contract beschikbaar voor de canary")
