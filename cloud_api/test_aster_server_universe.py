from datetime import datetime, timedelta, timezone

from aster_universe import build_snapshot, server_snapshot_contract
from test_aster_universe import contract, ticker


def test_bot_off_can_refresh_server_snapshot_and_strategy3_reuses_same_contract():
    rows = [contract(f"S{rank:03d}USDT") for rank in range(1, 61)]
    tickers = [ticker(f"S{rank:03d}USDT", 10_000 - rank) for rank in range(1, 61)]
    snapshot = build_snapshot({"symbols": rows}, tickers, 50,
        fetched_at=datetime(2026, 8, 15, 0, 0, tzinfo=timezone.utc))
    calls: list[int] = []

    def refresh(limit):
        calls.append(limit)
        return snapshot

    strategy2, persist2 = server_snapshot_contract(None, 50, refresh)
    strategy3, persist3 = server_snapshot_contract(None, 50, refresh)

    assert calls == [50, 50]
    assert strategy2 == strategy3
    assert strategy2["selectedMarketCount"] == 50
    assert strategy2["universeSource"] == "aster"
    assert persist2 is True and persist3 is True


def test_fresh_persisted_snapshot_does_not_need_network_refresh():
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    snapshot = build_snapshot({"symbols": [contract("BTCUSDT")]}, [ticker("BTCUSDT", 1000)], 1,
        fetched_at=now, ttl_seconds=300).public_dict()
    value, should_persist = server_snapshot_contract(snapshot, 1,
        lambda limit: (_ for _ in ()).throw(AssertionError("network refresh was not expected")), now=now)
    assert value == snapshot
    assert should_persist is False


def test_expired_or_incomplete_contract_refreshes_fail_closed():
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    fresh = build_snapshot({"symbols": [contract("ETHUSDT")]}, [ticker("ETHUSDT", 1000)], 1,
        fetched_at=now, ttl_seconds=300)
    expired = build_snapshot({"symbols": [contract("BTCUSDT")]}, [ticker("BTCUSDT", 2000)], 1,
        fetched_at=now - timedelta(minutes=10), ttl_seconds=60).public_dict()
    value, should_persist = server_snapshot_contract(expired, 1, lambda limit: fresh, now=now)
    assert value["selectedSymbols"] == ["ETHUSDT"]
    assert should_persist is True
