"""Build 642 (akkoord Amar 24-10 00:42): Auto Hedge 2 is released for every user (STABLE/LIVE by default)."""
from pathlib import Path

MAIN = (Path(__file__).resolve().parent / "main.py").read_text()


def test_auto_hedge_v2_is_live_and_stable_by_default():
    assert '"auto_hedge_v2": {"status": "LIVE", "beta": True, "stable": True}' in MAIN


def test_legacy_hedge_recovery_stays_beta_only():
    assert '"legacy_hedge_recovery": {"status": "TESTEN", "beta": True, "stable": False}' in MAIN
