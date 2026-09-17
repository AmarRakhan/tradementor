from pathlib import Path

core_path = Path('cloud_api/aster_multi_bb_core.py')
test_path = Path('cloud_api/test_short_requires_long_pairing_20260917.py')

core = core_path.read_text(encoding='utf-8')
old_start = '''    budget = max(0, 15 if order_budget is None else int(order_budget)); sent = 0
    state = dict(raw_state.get("multiBbPositions") or {}); pmap = _position_map(positions)
    selected_keys = {f"{symbol}|{side}" for symbol, side in settings.manual_symbols} if settings.manual_symbol_selection_enabled else set()
'''
new_start = '''    budget = max(0, 15 if order_budget is None else int(order_budget)); sent = 0
    state = dict(raw_state.get("multiBbPositions") or {}); pmap = _position_map(positions)
    # Pairing mode must make every seat/orphan decision from Aster exchange truth,
    # never from a caller/UI/cache snapshot that may be one reconciliation tick old.
    # Refresh before state reconciliation so an actually-open orphan SHORT cannot
    # be mistaken for a closed leg and removed before LONG rescue priority runs.
    position_truth_refresh_error: str | None = None
    if settings.short_requires_long_enabled:
        try:
            pmap = _position_map(client.position_risk())
        except Exception as exc:
            position_truth_refresh_error = str(exc)
    selected_keys = {f"{symbol}|{side}" for symbol, side in settings.manual_symbols} if settings.manual_symbol_selection_enabled else set()
'''
if old_start not in core:
    raise SystemExit('start anchor not found or already changed')
core = core.replace(old_start, new_start, 1)

old_actions = '''    available = _f(account.get("availableBalance", account.get("availableMargin")))
    actions: list[dict[str, Any]] = []

    # P0 recovery: selected manual-mode positions must never exist on Aster
'''
new_actions = '''    available = _f(account.get("availableBalance", account.get("availableMargin")))
    actions: list[dict[str, Any]] = []
    if position_truth_refresh_error:
        actions.append({
            "kind": "ENTRY_SCAN_BLOCKED", "reason": "PAIRING_POSITION_TRUTH_UNAVAILABLE",
            "detail": position_truth_refresh_error,
        })

    # P0 recovery: selected manual-mode positions must never exist on Aster
'''
if old_actions not in core:
    raise SystemExit('actions anchor not found or already changed')
core = core.replace(old_actions, new_actions, 1)

old_active = '''    active = _position_map(client.position_risk()) if sent and not dry_run else pmap
    active_symbols = {k.split("|", 1)[0] for k in active}
'''
new_active = '''    # pmap was already refreshed from Aster at the start whenever pairing mode is
    # enabled. If management submitted an order, refresh once more so seat counts
    # reflect that confirmed change too.
    active = _position_map(client.position_risk()) if sent and not dry_run else pmap
    active_symbols = {k.split("|", 1)[0] for k in active}
'''
if old_active not in core:
    raise SystemExit('active anchor not found or already changed')
core = core.replace(old_active, new_active, 1)

old_capacity = '''        long_need = max(0, settings.long_slots - long_count); short_need = max(0, settings.short_slots - short_count)
        account_remaining_capacity = max(0, settings.maximum_positions - account_position_count)

    orphan_short_symbols: list[str] = []
'''
new_capacity = '''        long_need = max(0, settings.long_slots - long_count); short_need = max(0, settings.short_slots - short_count)
        account_remaining_capacity = max(0, settings.maximum_positions - account_position_count)

    # If exchange truth could not be refreshed while the pairing toggle is on,
    # do not allocate any new seat from a potentially stale snapshot. Existing
    # position management above remains available; the next tick retries truth.
    if settings.short_requires_long_enabled and position_truth_refresh_error:
        account_remaining_capacity = 0

    orphan_short_symbols: list[str] = []
'''
if old_capacity not in core:
    raise SystemExit('capacity anchor not found or already changed')
core = core.replace(old_capacity, new_capacity, 1)
core_path.write_text(core, encoding='utf-8')

tests = test_path.read_text(encoding='utf-8')
marker = 'def test_orphan_priority_uses_exchange_truth_when_caller_snapshot_is_stale():'
if marker not in tests:
    tests += '''\n\n\ndef test_orphan_priority_uses_exchange_truth_when_caller_snapshot_is_stale():
    # Reproduces the live 2026-09-17 failure: Aster has ZEC SHORT, while the
    # caller-provided snapshot is one tick stale and contains no positions.
    short = pos("ZECUSDT", "SHORT")
    client = Client(
        positions=[short],
        tickers=[{"symbol": "AAAUSDT", "quoteVolume": "999999"}],
        prices={"AAAUSDT": 100, "ZECUSDT": 100},
        leverage=100,
    )
    result = run_multi_bb_step(
        client=client, ref=Ref(), raw_state=state_for("ZECUSDT", "SHORT"),
        settings=cfg(maximumPositions=3, longSlots=2, shortSlots=1,
                     shortRequiresLongEnabled=True, universeTopN=2),
        uid="u", account={"availableBalance": "1000"},
        positions=[], open_orders=[], timestamp_ms=int(time.time() * 1000), dry_run=True,
    )
    entries = [row for row in result["actions"] if row.get("kind") == "ENTRY"]
    assert entries, result
    assert entries[0]["symbol"] == "ZECUSDT"
    assert entries[0]["side"] == "LONG"
    assert "ZECUSDT" in result["orphanShortSymbols"]


def test_pairing_truth_refresh_failure_blocks_new_seat_allocation():
    class BrokenTruthClient(Client):
        def position_risk(self, symbol=None):
            raise RuntimeError("exchange position truth unavailable")

    client = BrokenTruthClient(
        tickers=[{"symbol": "AAAUSDT", "quoteVolume": "999999"}],
        prices={"AAAUSDT": 100}, leverage=100,
    )
    result = run_multi_bb_step(
        client=client, ref=Ref(), raw_state={},
        settings=cfg(maximumPositions=2, longSlots=1, shortSlots=1,
                     shortRequiresLongEnabled=True, universeTopN=1),
        uid="u", account={"availableBalance": "1000"},
        positions=[], open_orders=[], timestamp_ms=int(time.time() * 1000), dry_run=True,
    )
    assert not [row for row in result["actions"] if row.get("kind") == "ENTRY"]
    assert any(row.get("kind") == "ENTRY_SCAN_BLOCKED" and
               row.get("reason") == "PAIRING_POSITION_TRUTH_UNAVAILABLE"
               for row in result["actions"])
'''
    test_path.write_text(tests, encoding='utf-8')

print('exchange-truth pairing repair applied')
