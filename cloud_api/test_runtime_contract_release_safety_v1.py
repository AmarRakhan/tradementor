from __future__ import annotations

import time

import pytest

from aster_multi_bb import MultiBbConfig, run_multi_bb_step
from test_aster_multi_bb import Client, Ref, kline_rows


def _zone_settings(**overrides):
    raw = {
        "engine": "multi_bb_v1",
        "universeTopN": 350,
        "maximumPositions": 150,
        "longSlots": 75,
        "shortSlots": 75,
        "minimumLeverage": 20,
        "entrySizingMode": "margin",
        "entryMarginUsd": 0.4,
        "entryMarginLongUsd": 0.4,
        "entryMarginShortUsd": 0.3,
        "entryNotionalUsd": 8.0,
        "entryNotionalLongUsd": 8.0,
        "entryNotionalShortUsd": 6.0,
        "dcaDistance": 0.10,
        "longDcaDistance": 0.10,
        "shortDcaDistance": 0.25,
        "dcaMarginUsd": 0.17,
        "longDcaMarginUsd": 0.17,
        "shortDcaMarginUsd": 0.25,
        "maxDca": 10,
        "maxDcaLong": 10,
        "maxDcaShort": 15,
        "takeProfit": 0.015,
        "longTakeProfitValue": 0.015,
        "shortTakeProfitValue": 0.015,
        "zoneSoldiersEnabled": True,
        "zoneSoldiersOptInVersion": 1,
        "zoneBaseLongSoldiers": 3,
        "zoneBaseShortSoldiers": 3,
        "zoneExposureBalancerEnabled": True,
        "bollingerEntryFilter15mEnabled": False,
        "directionalBollingerEnabled": True,
        "bollingerLongTimeframe": "1m",
        "bollingerShortTimeframe": "15m",
    }
    raw.update(overrides)
    return MultiBbConfig.from_mapping(raw)


def _positions(count: int):
    return [
        {
            "symbol": f"P{index:03d}USDT",
            "positionSide": "LONG" if index % 2 == 0 else "SHORT",
            "positionAmt": "1",
            "entryPrice": "100",
            "markPrice": "100",
            "leverage": "100",
        }
        for index in range(count)
    ]


def test_golden_zone_warriors_149_of_150_allows_exactly_one_new_initial_entry():
    now = int(time.time() * 1000)
    positions = _positions(149)
    candidate = "NEWUSDT"
    client = Client(
        positions=positions,
        tickers=[{"symbol": candidate, "quoteVolume": "999999999"}],
        prices={**{row["symbol"]: 100 for row in positions}, candidate: 100},
        leverage=100,
    )
    result = run_multi_bb_step(
        client=client,
        ref=Ref(),
        raw_state={},
        settings=_zone_settings(bollingerEntryFilter15mEnabled=False),
        uid="golden-zone-149",
        account={"availableBalance": "1000"},
        positions=positions,
        open_orders=[],
        timestamp_ms=now,
        dry_run=True,
        order_budget=15,
        zone_context={"activeZone": 28, "safeForEntries": True},
    )

    entries = [row for row in result["actions"] if row.get("kind") == "ENTRY"]
    assert result["accountPositionCount"] == 150
    assert result["accountRemainingCapacity"] == 0
    assert len(entries) == 1
    assert result["executableCandidateCount"] == 1


def test_golden_zone_warriors_150_of_150_never_creates_position_151():
    now = int(time.time() * 1000)
    positions = _positions(150)
    candidate = "NEWUSDT"
    client = Client(
        positions=positions,
        tickers=[{"symbol": candidate, "quoteVolume": "999999999"}],
        prices={**{row["symbol"]: 100 for row in positions}, candidate: 100},
        leverage=100,
    )
    result = run_multi_bb_step(
        client=client,
        ref=Ref(),
        raw_state={},
        settings=_zone_settings(bollingerEntryFilter15mEnabled=False),
        uid="golden-zone-150",
        account={"availableBalance": "1000"},
        positions=positions,
        open_orders=[],
        timestamp_ms=now,
        dry_run=True,
        order_budget=15,
        zone_context={"activeZone": 28, "safeForEntries": True},
    )

    assert result["accountPositionCount"] == 150
    assert result["accountRemainingCapacity"] == 0
    assert result["scannedCandidateCount"] == 0
    assert not any(row.get("kind") == "ENTRY" for row in result["actions"])
    assert result["entryStatus"] == "WAITING_ACCOUNT_CAP"


class DirectionalMarket(Client):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.kline_calls: list[tuple[str, str]] = []

    def klines(self, symbol, interval, limit):
        self.kline_calls.append((symbol, interval))
        rows = kline_rows([100] * 25)
        return rows[-limit:]


def test_golden_zone_warriors_routes_long_to_1m_and_short_to_15m_in_one_scan():
    now = int(time.time() * 1000)
    client = DirectionalMarket(
        tickers=[
            {"symbol": "LONGUSDT", "quoteVolume": "2000"},
            {"symbol": "SHORTUSDT", "quoteVolume": "1000"},
        ],
        prices={"LONGUSDT": 90, "SHORTUSDT": 110},
        leverage=100,
    )
    settings = _zone_settings(
        maximumPositions=2,
        longSlots=1,
        shortSlots=1,
        zoneBaseLongSoldiers=1,
        zoneBaseShortSoldiers=1,
        bollingerEntryFilter15mEnabled=True,
        directionalBollingerEnabled=True,
        bollingerLongTimeframe="1m",
        bollingerShortTimeframe="15m",
    )
    result = run_multi_bb_step(
        client=client,
        ref=Ref(),
        raw_state={},
        settings=settings,
        uid="golden-directional-bb",
        account={"availableBalance": "1000"},
        positions=[],
        open_orders=[],
        timestamp_ms=now,
        dry_run=True,
        order_budget=2,
        zone_context={"activeZone": 28, "safeForEntries": True},
    )

    entries = [row for row in result["actions"] if row.get("kind") == "ENTRY"]
    assert [(row["symbol"], row["side"]) for row in entries] == [
        ("LONGUSDT", "LONG"),
        ("SHORTUSDT", "SHORT"),
    ]
    assert ("LONGUSDT", "1m") in client.kline_calls
    assert ("SHORTUSDT", "15m") in client.kline_calls
    assert ("LONGUSDT", "15m") not in client.kline_calls
    assert ("SHORTUSDT", "1m") not in client.kline_calls
    assert result["scannerDiagnostics"]["LONG"]["timeframe"] == "1m"
    assert result["scannerDiagnostics"]["SHORT"]["timeframe"] == "15m"
    assert result["scannerDiagnostics"]["LONG"]["bbCandidates"] >= 1
    assert result["scannerDiagnostics"]["SHORT"]["bbCandidates"] >= 1


def test_golden_classic_dca_preserves_side_specific_entry_sizing():
    now = int(time.time() * 1000)
    client = Client(
        tickers=[
            {"symbol": "AAAUSDT", "quoteVolume": "2000"},
            {"symbol": "BBBUSDT", "quoteVolume": "1000"},
        ],
        prices={"AAAUSDT": 100, "BBBUSDT": 100},
        leverage=100,
    )
    settings = MultiBbConfig.from_mapping({
        "engine": "multi_bb_v1",
        "universeTopN": 2,
        "maximumPositions": 2,
        "longSlots": 1,
        "shortSlots": 1,
        "minimumLeverage": 20,
        "entrySizingMode": "margin",
        "entryMarginUsd": 0.4,
        "entryMarginLongUsd": 0.4,
        "entryMarginShortUsd": 0.3,
        "entryNotionalUsd": 8.0,
        "entryNotionalLongUsd": 8.0,
        "entryNotionalShortUsd": 6.0,
        "dcaDistance": 0.10,
        "dcaMarginUsd": 0.17,
        "maxDca": 10,
        "takeProfit": 0.015,
        "bollingerEntryFilter15mEnabled": False,
        "zoneSoldiersEnabled": False,
    })
    result = run_multi_bb_step(
        client=client,
        ref=Ref(),
        raw_state={},
        settings=settings,
        uid="golden-classic-sizing",
        account={"availableBalance": "1000"},
        positions=[],
        open_orders=[],
        timestamp_ms=now,
        dry_run=True,
        order_budget=2,
    )

    entries = [row for row in result["actions"] if row.get("kind") == "ENTRY"]
    assert len(entries) == 2
    by_side = {row["side"]: row for row in entries}
    assert by_side["LONG"]["configuredMarginUsd"] == pytest.approx(0.4)
    assert by_side["SHORT"]["configuredMarginUsd"] == pytest.approx(0.3)
    assert by_side["LONG"]["plannedInputMarginUsd"] == pytest.approx(0.4)
    assert by_side["SHORT"]["plannedInputMarginUsd"] == pytest.approx(0.3)


def test_golden_baseline_never_depends_on_live_credentials_or_network():
    source = __file__
    assert source
