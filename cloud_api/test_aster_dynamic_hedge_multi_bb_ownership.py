from __future__ import annotations

import aster_multi_bb as multi


def test_blocked_hedge_side_cannot_get_new_slots(monkeypatch):
    settings = multi.MultiBbConfig()
    proxy = multi._PairAwareSettings(settings, "SHORT", 7)
    assert proxy.short_slots == 7
    assert proxy.long_slots == settings.long_slots


def test_blocked_hedge_side_disables_its_tp_and_dca(monkeypatch):
    settings = multi.MultiBbConfig()
    monkeypatch.setattr(multi, "_execution_context_from_stack", lambda: ("BTCUSDT", "SHORT"))
    proxy = multi._PairAwareSettings(settings, "SHORT", 7)
    assert proxy.take_profit_enabled is False
    assert proxy.max_dca == -1


def test_dominant_side_keeps_normal_per_trade_settings(monkeypatch):
    settings = multi.MultiBbConfig()
    monkeypatch.setattr(multi, "_execution_context_from_stack", lambda: ("BTCUSDT", "LONG"))
    proxy = multi._PairAwareSettings(settings, "SHORT", 7)
    assert proxy.take_profit_enabled is settings.take_profit_enabled
    assert proxy.max_dca == settings.max_dca_long
