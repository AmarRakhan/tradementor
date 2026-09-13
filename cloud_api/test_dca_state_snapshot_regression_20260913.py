from __future__ import annotations

import aster_multi_bb
import aster_multi_bb_core as core


class RecordingRef:
    def __init__(self):
        self.calls = []

    def set(self, payload, merge=True):
        self.calls.append((dict(payload), merge))


def test_zero_dca_ignores_stale_prior_cycle_fill_anchor():
    state = {
        "dcaCount": 0,
        "lastBotFillPrice": 0.08465,
        "lastDcaFillPrice": 0.08307,
        "lastManualFillPrice": 0.08250,
        "dcaCatchupTargetCount": 4,
    }
    cleaned = core._normalize_zero_dca_state(state)
    assert cleaned["lastBotFillPrice"] == 0.08465
    assert "lastDcaFillPrice" not in cleaned
    assert "lastManualFillPrice" not in cleaned
    assert "dcaCatchupTargetCount" not in cleaned
    assert core._recovery_anchor(cleaned, entry=0.08470) == 0.08465


def test_zero_dca_without_bot_anchor_falls_back_to_current_cycle_entry():
    state = {"dcaCount": 0, "lastDcaFillPrice": 90.0}
    cleaned = core._normalize_zero_dca_state(state)
    assert core._recovery_anchor(cleaned, entry=100.0) == 100.0


def test_multibb_position_snapshot_uses_exact_top_level_field_merge():
    ref = RecordingRef()
    wrapped = aster_multi_bb._ExactStateMapRef(ref)
    wrapped.set({"multiBbPositions": {"BTCUSDT|LONG": {"dcaCount": 0}}, "phase": "RUNNING"}, merge=True)
    payload, merge = ref.calls[-1]
    assert payload["multiBbPositions"] == {"BTCUSDT|LONG": {"dcaCount": 0}}
    assert set(merge) == {"multiBbPositions", "phase"}
