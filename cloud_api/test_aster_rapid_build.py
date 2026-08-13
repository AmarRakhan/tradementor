from aster_rapid_build import run_confirmed_batch


def test_rapid_batch_runs_at_most_ten_confirmed_orders():
    calls = 0

    def tick():
        nonlocal calls
        calls += 1
        return {"status": "ok", "ordersSent": 1}

    result = run_confirmed_batch(tick, maximum_orders=50)
    assert calls == 10
    assert result == {
        "ordersSent": 10,
        "ticks": 10,
        "last": {"status": "ok", "ordersSent": 1},
        "stopped": False,
    }


def test_rapid_batch_stops_immediately_on_unknown_or_hold():
    outcomes = iter([
        {"status": "ok", "ordersSent": 1},
        {"status": "data-hold", "ordersSent": 0, "reason": "orderstatus onbekend"},
        {"status": "ok", "ordersSent": 1},
    ])
    result = run_confirmed_batch(lambda: next(outcomes), maximum_orders=10)
    assert result["ordersSent"] == 1
    assert result["ticks"] == 2
    assert result["stopped"] is True
    assert result["last"]["reason"] == "orderstatus onbekend"


def test_rapid_batch_never_runs_zero_ticks():
    calls = 0

    def tick():
        nonlocal calls
        calls += 1
        return {"status": "blocked", "ordersSent": 0}

    result = run_confirmed_batch(tick, maximum_orders=0)
    assert calls == 1
    assert result["stopped"] is True


def test_rapid_batch_continues_after_definite_dca_skip_and_opens_other_slots_500_times():
    """Regression for production Aster -5018 during rapid Strategy-3 build.

    A proven contract rejection sends no order and is represented as an OK
    DCA_SKIPPED tick.  The batch must then continue with other eligible pairs;
    it may never turn this safe skip into a failed cloud command.
    """
    for _ in range(500):
        outcomes = iter([
            {"status": "ok", "action": "DCA_SKIPPED", "ordersSent": 0},
            *({"status": "ok", "action": "OPEN_BASE", "ordersSent": 1} for _ in range(9)),
        ])
        result = run_confirmed_batch(lambda: next(outcomes), maximum_orders=10)
        assert result["stopped"] is False
        assert result["ticks"] == 10
        assert result["ordersSent"] == 9
        assert result["last"]["action"] == "OPEN_BASE"
