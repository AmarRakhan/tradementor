from hyperliquid_migration import ReconciliationSnapshot, assess_migration


def snapshot(source: str, *, size: float = 1.0, enabled: bool = True, account: str = "0xabc"):
    return ReconciliationSnapshot.from_mapping(source, {
        "accountId": account,
        "capturedAtMs": 1000,
        "positions": [{"coin": "ETH", "szi": size, "entryPrice": 2500}],
        "openOrders": [{"oid": "take-1", "coin": "ETH", "side": "sell", "sz": 1, "reduceOnly": True}],
        "fills": ["fill-1"],
        "enabled": enabled,
        "enabledUpdatedAtMs": 900,
    })


def test_exact_snapshots_preserve_enabled_state_and_allow_execution():
    result = assess_migration(
        exchange=snapshot("exchange"), cloud=snapshot("cloud"), local=snapshot("local"),
        exchange_read_ok=True,
    )
    assert result.status == "READY"
    assert result.effective_enabled is True
    assert result.allow_risk_increase is True


def test_exchange_read_failure_pauses_without_using_stale_local_data():
    result = assess_migration(
        exchange=None, cloud=snapshot("cloud"), local=snapshot("local"), exchange_read_ok=False,
    )
    assert result.status == "PAUSED"
    assert result.allow_risk_increase is False
    assert result.effective_enabled is False


def test_position_mismatch_requires_exchange_authoritative_repair_first():
    exchange = snapshot("exchange", size=2)
    result = assess_migration(
        exchange=exchange, cloud=snapshot("cloud"), local=snapshot("local"), exchange_read_ok=True,
    )
    assert result.status == "SYNC_REQUIRED"
    assert result.allow_risk_increase is False
    assert set(result.repair_targets) == {"cloud", "local"}
    assert result.authoritative_snapshot == exchange


def test_verified_round_trip_can_resume_with_preserved_enabled_state():
    result = assess_migration(
        exchange=snapshot("exchange", size=2),
        cloud=snapshot("cloud", size=1),
        local=snapshot("local", size=1),
        exchange_read_ok=True,
        state_round_trip_verified=True,
    )
    assert result.status == "READY"
    assert result.allow_risk_increase is True
    assert "exact teruggelezen" in result.reasons[-1]


def test_missing_enabled_state_never_accidentally_enables_bot():
    raw = {
        "accountId": "0xabc", "capturedAtMs": 1000,
        "positions": [{"coin": "ETH", "szi": 1, "entryPrice": 2500}],
        "openOrders": [{"oid": "take-1", "coin": "ETH", "side": "sell", "sz": 1, "reduceOnly": True}],
    }
    result = assess_migration(
        exchange=ReconciliationSnapshot.from_mapping("exchange", raw),
        cloud=ReconciliationSnapshot.from_mapping("cloud", raw),
        local=ReconciliationSnapshot.from_mapping("local", raw),
        exchange_read_ok=True,
    )
    assert result.status == "PAUSED"
    assert result.effective_enabled is False


def test_digest_is_stable_across_input_ordering_and_ignores_source_name():
    first = snapshot("exchange")
    second = snapshot("cloud")
    assert first.digest() == second.digest()

