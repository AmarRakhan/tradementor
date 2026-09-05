from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"Expected snippet not found in {path}: {old[:180]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


multi = "cloud_api/aster_multi_bb.py"
replace_once(
    multi,
    '    active_pair_count = sum(1 for key, row in state.items() if key.endswith("|LONG") and row.get("asymmetricHedge") and key in active and (row.get("pairedShortPending") or str(row.get("pairedShortKey") or "") in active))',
    '    active_pair_count = sum(1 for key, row in state.items() if key.endswith("|LONG") and row.get("asymmetricHedge") and key in active)',
)

# A logical asymmetric cycle remains occupied for as long as its LONG leg is
# alive. The paired SHORT may be pending, open, or intentionally released at
# LONG max-DCA; none of those states may free a scanner pair seat.

test_path = Path("cloud_api/test_asymmetric_hedge_20260904.py")
text = test_path.read_text(encoding="utf-8")
marker = "def test_released_shorts_do_not_free_pair_slots_or_refill_to_account_cap():"
if marker not in text:
    text += r'''


def test_released_shorts_do_not_free_pair_slots_or_refill_to_account_cap():
    from test_aster_multi_bb import Client, Ref
    import time
    from aster_multi_bb import run_multi_bb_step

    positions = []
    state = {}
    for i in range(15):
        symbol = f"PAIR{i}USDT"
        positions.append({"symbol": symbol, "positionSide": "LONG", "positionAmt": "1", "entryPrice": "100", "markPrice": "100", "leverage": "100"})
        state[f"{symbol}|LONG"] = {
            "cycleId": f"cycle-{i}", "asymmetricHedge": True,
            "pairedShortKey": f"{symbol}|SHORT", "pairedShortPending": False,
            "pairedShortOpened": True, "pairedShortClosedAtMs": 123456,
            "botManaged": True, "dcaCount": 15, "lastBotFillPrice": 100,
            "lastKnownQty": 1, "lastKnownEntry": 100, "cycleStartedAtMs": 1,
        }

    c = Client(
        positions=positions,
        tickers=[{"symbol": "NEWUSDT", "quoteVolume": "999999"}],
        prices={"NEWUSDT": 100, **{p["symbol"]: 100 for p in positions}},
        leverage=100,
    )
    settings = cfg(
        maximumPositions=30, longSlots=15, shortSlots=15,
        universeTopN=50, entryMarginUsd=.1, shortStartMultiplier=1,
        maxDca=15,
    )
    r = run_multi_bb_step(
        client=c, ref=Ref(), raw_state={"multiBbPositions": state},
        settings=settings, uid="u", account={"availableBalance": "1000"},
        positions=positions, open_orders=[], timestamp_ms=int(time.time() * 1000),
        dry_run=True,
    )

    assert r["asymmetricHedgeActivePairs"] == 15
    assert r["remainingPairs"] == 0
    assert r["entryStatus"] == "WAITING_CAPACITY"
    assert not any(x["kind"] in {"ENTRY", "ASYM_SHORT_ENTRY"} for x in r["actions"])


def test_one_full_cycle_slot_only_frees_after_long_is_gone():
    from test_aster_multi_bb import Client, Ref
    import time
    from aster_multi_bb import run_multi_bb_step

    positions = []
    state = {}
    for i in range(14):
        symbol = f"PAIR{i}USDT"
        positions.append({"symbol": symbol, "positionSide": "LONG", "positionAmt": "1", "entryPrice": "100", "markPrice": "100", "leverage": "100"})
        state[f"{symbol}|LONG"] = {
            "cycleId": f"cycle-{i}", "asymmetricHedge": True,
            "pairedShortKey": f"{symbol}|SHORT", "pairedShortPending": False,
            "pairedShortClosedAtMs": 123456, "botManaged": True,
            "dcaCount": 15, "lastBotFillPrice": 100, "lastKnownQty": 1,
            "lastKnownEntry": 100, "cycleStartedAtMs": 1,
        }

    c = Client(
        positions=positions,
        tickers=[{"symbol": "NEWUSDT", "quoteVolume": "999999"}],
        prices={"NEWUSDT": 100, **{p["symbol"]: 100 for p in positions}},
        leverage=100,
    )
    settings = cfg(
        maximumPositions=30, longSlots=15, shortSlots=15,
        universeTopN=50, entryMarginUsd=.1, shortStartMultiplier=1,
        maxDca=15,
    )
    r = run_multi_bb_step(
        client=c, ref=Ref(), raw_state={"multiBbPositions": state},
        settings=settings, uid="u", account={"availableBalance": "1000"},
        positions=positions, open_orders=[], timestamp_ms=int(time.time() * 1000),
        dry_run=True,
    )

    entries = [x for x in r["actions"] if x["kind"] in {"ENTRY", "ASYM_SHORT_ENTRY"}]
    assert {(x["symbol"], x["side"]) for x in entries} == {("NEWUSDT", "LONG"), ("NEWUSDT", "SHORT")}
    assert r["asymmetricHedgeActivePairs"] == 15
    assert r["remainingPairs"] == 0
'''
    test_path.write_text(text, encoding="utf-8")
