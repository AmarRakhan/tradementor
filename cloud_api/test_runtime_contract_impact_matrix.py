from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "runtime_contract_impact.py"
SPEC = importlib.util.spec_from_file_location("runtime_contract_impact", MODULE_PATH)
assert SPEC and SPEC.loader
impact = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(impact)


def suites(*paths: str) -> set[str]:
    return set(impact.classify_files(paths)["suites"])


def test_shared_multi_bb_core_selects_both_strategies_and_cross_cutting_contracts():
    selected = suites("cloud_api/aster_multi_bb_core.py")
    assert {"zone_warriors", "classic_dca", "portfolio_tp", "execution", "settings"} <= selected


def test_zone_only_module_selects_zone_warriors_without_classic_dca():
    selected = suites("cloud_api/aster_zone_soldiers.py")
    assert "zone_warriors" in selected
    assert "classic_dca" not in selected


def test_dynamic_hedge_change_selects_hedge_contracts():
    selected = suites("cloud_api/aster_dynamic_hedge_execution.py")
    assert selected == {"hedge"}


def test_main_is_treated_as_maximum_blast_radius_runtime_asset():
    selected = suites("cloud_api/main.py")
    assert {"zone_warriors", "classic_dca", "hedge", "portfolio_tp", "execution", "scheduler"} <= selected


def test_botconfigurator_change_selects_settings_and_both_strategy_contracts():
    selected = suites("web/components/aster-bot-configurator-v3.tsx")
    assert {"settings", "zone_warriors", "classic_dca", "portfolio_tp"} <= selected


def test_portfolio_zone_advisor_change_selects_zone_contract_and_web_tests():
    result = impact.classify_files(["web/lib/portfolio-zone-advisor.mjs"])
    assert result["suites"] == ["zone_warriors"]
    assert "web/tests/portfolio-zone-advisor.test.mjs" in result["webTests"]


def test_unknown_backend_python_file_fails_safe_to_all_backend_suites():
    result = impact.classify_files(["cloud_api/new_future_trading_engine.py"])
    assert result["conservativeFallback"] is True
    assert result["unknownCloudFiles"] == ["cloud_api/new_future_trading_engine.py"]
    assert set(impact.SUITE_TESTS) <= set(result["suites"])


def test_ui_only_non_trading_file_does_not_invent_runtime_impact():
    result = impact.classify_files(["web/components/news-view.tsx"])
    assert result["suites"] == []
    assert result["backendTests"] == []
    assert result["webTests"] == []


def test_release_workflow_changes_always_select_release_safety_contract():
    selected = suites(".github/workflows/deploy-cloud-production.yml")
    assert selected == {"release_safety"}


def test_selected_test_lists_are_deduplicated_and_deterministic():
    result = impact.classify_files([
        "cloud_api/aster_multi_bb_core.py",
        "cloud_api/aster_multi_bb.py",
        "cloud_api/aster_multi_bb_core.py",
    ])
    assert result["backendTests"] == sorted(set(result["backendTests"]))
    assert result["webTests"] == sorted(set(result["webTests"]))
