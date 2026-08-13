from startup_recovery import ExchangeStartupState, recover_startup, retry_delay_seconds


def state(exchange, *, configured=True, read=True, reconciled=True, stream=True, enabled=True, protective=True):
    return ExchangeStartupState(exchange, configured, read, reconciled, stream, enabled, protective)


def test_new_aster_install_remains_off_and_does_not_block_ready_existing_exchanges():
    result = recover_startup((
        state("mexc"), state("hyperliquid"), state("aster", configured=False, enabled=None),
    ))
    assert result.status == "READY"
    aster = next(item for item in result.exchange_gates if item.exchange == "aster")
    assert aster.automation_enabled is False
    assert aster.allow_risk_increase is False


def test_persisted_enabled_state_only_resumes_after_full_reconciliation_and_stream():
    syncing = recover_startup((state("hyperliquid", reconciled=False, enabled=True),))
    ready = recover_startup((state("hyperliquid", reconciled=True, enabled=True),))
    assert syncing.status == "SYNCING"
    assert syncing.exchange_gates[0].automation_enabled is False
    assert ready.status == "READY"
    assert ready.exchange_gates[0].automation_enabled is True


def test_unknown_enabled_state_never_turns_on_automation():
    result = recover_startup((state("mexc", enabled=None),))
    assert result.status == "READY"
    assert result.exchange_gates[0].automation_enabled is False


def test_degraded_mode_is_isolated_per_exchange():
    result = recover_startup((
        state("mexc"), state("hyperliquid", read=False), state("aster", stream=False),
    ))
    assert result.status == "DEGRADED"
    gates = {item.exchange: item for item in result.exchange_gates}
    assert gates["mexc"].allow_risk_increase is True
    assert gates["hyperliquid"].allow_risk_increase is False
    assert gates["aster"].allow_risk_increase is False


def test_protective_actions_can_remain_available_while_new_exposure_is_blocked():
    result = recover_startup((state("mexc", reconciled=False, protective=True),))
    gate = result.exchange_gates[0]
    assert gate.allow_risk_increase is False
    assert gate.allow_protective_actions is True


def test_retry_backoff_is_bounded():
    assert [retry_delay_seconds(item) for item in range(6)] == [2, 4, 8, 16, 32, 60]
    assert retry_delay_seconds(100) == 60

