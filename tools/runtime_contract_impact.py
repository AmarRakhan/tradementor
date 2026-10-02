from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
from typing import Iterable


SUITE_TESTS: dict[str, tuple[str, ...]] = {
    "zone_warriors": (
        "cloud_api/test_runtime_contract_release_safety_v1.py",
        "cloud_api/test_aster_runtime_truth.py",
        "cloud_api/test_aster_zone_soldiers.py",
        "cloud_api/test_aster_zone_soldiers_integration.py",
        "cloud_api/test_aster_bollinger_entry_filter_timeframes.py",
        "cloud_api/test_aster_portfolio_chart.py",
    ),
    "classic_dca": (
        "cloud_api/test_runtime_contract_release_safety_v1.py",
        "cloud_api/test_aster_runtime_truth.py",
        "cloud_api/test_aster_multi_bb.py",
        "cloud_api/test_aster_pair_overrides.py",
        "cloud_api/test_aster_side_settings_persistence.py",
    ),
    "hedge": (
        "cloud_api/test_aster_dynamic_hedge_sequence.py",
        "cloud_api/test_aster_dynamic_hedge_execution.py",
        "cloud_api/test_aster_position_loss_auto_hedge.py",
        "cloud_api/test_aster_position_loss_auto_hedge_lifecycle_contract.py",
        "cloud_api/test_aster_position_loss_auto_hedge_lock.py",
    ),
    "portfolio_tp": (
        "cloud_api/test_aster_portfolio_tp_mode.py",
        "cloud_api/test_aster_portfolio_tp_v2.py",
        "cloud_api/test_aster_portfolio_tp_races.py",
        "cloud_api/test_aster_portfolio_tp_seat_reset.py",
    ),
    "execution": (
        "cloud_api/test_aster_execution.py",
        "cloud_api/test_aster_openable_capacity_guard.py",
        "cloud_api/test_order_coordinator.py",
        "cloud_api/test_aster_gateway.py",
    ),
    "scheduler": (
        "cloud_api/test_aster_strategy2_scheduler_deploy.py",
        "cloud_api/test_production_health_monitor.py",
        "cloud_api/test_startup_recovery.py",
    ),
    "settings": (
        "cloud_api/test_botconfigurator_v3_dry_run.py",
        "cloud_api/test_aster_side_settings_persistence.py",
        "cloud_api/test_aster_pair_overrides.py",
    ),
    "release_safety": (
        "cloud_api/test_runtime_contract_impact_matrix.py",
        "cloud_api/test_runtime_contract_post_deploy.py",
        "cloud_api/test_runtime_contract_snapshot.py",
        "cloud_api/test_runtime_contract_release_gate.py",
        "cloud_api/test_production_deploy_safety.py",
        "cloud_api/test_live_canary_deploy_contract.py",
        "cloud_api/test_manual_only_cloud_deployments.py",
    ),
}

WEB_SUITE_TESTS: dict[str, tuple[str, ...]] = {
    "settings": (
        "web/tests/aster-strategy2-side-persistence.test.mjs",
        "web/tests/botconfigurator-v2-beta.test.mjs",
        "web/tests/botconfigurator-v31-quick-edit.test.mjs",
        "web/tests/strategy2-settings-hard-limits.test.mjs",
    ),
    "zone_warriors": (
        "web/tests/portfolio-zone-advisor.test.mjs",
        "web/tests/portfolio-zone-owned-soldiers-ui.test.mjs",
        "web/tests/price-zone-live-sync-build457.test.mjs",
    ),
    "portfolio_tp": (
        "web/tests/portfolio-tp-2.test.mjs",
        "web/tests/portfolio-tp-additive.test.mjs",
        "web/tests/portfolio-tp-seat-reset.test.mjs",
    ),
}

SUITE_PATTERNS: dict[str, tuple[str, ...]] = {
    "zone_warriors": (
        "cloud_api/main.py",
        "cloud_api/aster_multi_bb.py",
        "cloud_api/aster_multi_bb_core.py",
        "cloud_api/aster_bollinger_entry_filter.py",
        "cloud_api/aster_zone_soldiers.py",
        "cloud_api/aster_portfolio_chart.py",
        "cloud_api/aster_runtime_truth.py",
        "web/lib/portfolio-zone-advisor.mjs",
        "web/components/portfolio-koers-chart.tsx",
        "web/components/aster-portfolio-snapshot-enhancer.tsx",
        "web/components/aster-bot-configurator-v2.tsx",
        "web/components/aster-bot-configurator-v3.tsx",
        "web/lib/aster-strategy2-settings-guard.ts",
    ),
    "classic_dca": (
        "cloud_api/main.py",
        "cloud_api/aster_multi_bb.py",
        "cloud_api/aster_multi_bb_core.py",
        "cloud_api/aster_bollinger_entry_filter.py",
        "cloud_api/aster_execution.py",
        "cloud_api/aster_gateway.py",
        "cloud_api/aster_runtime_truth.py",
        "web/components/aster-bot-configurator-v2.tsx",
        "web/components/aster-bot-configurator-v3.tsx",
        "web/lib/aster-strategy2-settings-guard.ts",
    ),
    "hedge": (
        "cloud_api/main.py",
        "cloud_api/aster_dynamic_hedge*.py",
        "cloud_api/aster_position_loss_auto_hedge*.py",
        "cloud_api/aster_hedge_recovery*.py",
        "cloud_api/aster_legacy_hedge_scale*.py",
        "web/components/aster-position-loss-auto-hedge-bridge.tsx",
        "web/components/aster-hedge-manager.tsx",
    ),
    "portfolio_tp": (
        "cloud_api/main.py",
        "cloud_api/aster_multi_bb.py",
        "cloud_api/aster_multi_bb_core.py",
        "cloud_api/aster_multi_bb_portfolio.py",
        "cloud_api/trading_cycle.py",
        "cloud_api/portfolio_growth.py",
        "web/components/portfolio-tp-seat-reset-target.tsx",
        "web/components/aster-bot-configurator-v2.tsx",
        "web/components/aster-bot-configurator-v3.tsx",
    ),
    "execution": (
        "cloud_api/main.py",
        "cloud_api/aster_multi_bb_core.py",
        "cloud_api/aster_execution.py",
        "cloud_api/aster_gateway.py",
        "cloud_api/order_coordinator.py",
        "cloud_api/aster_symbol_ownership.py",
        "cloud_api/close_all.py",
        "cloud_api/position_close.py",
    ),
    "scheduler": (
        "cloud_api/main.py",
        "cloud_api/aster_realtime.py",
        "cloud_api/startup_recovery.py",
        "cloud_api/strategy2_bot_health.py",
        ".github/workflows/ensure-cloudrun-background-cpu.yml",
        ".github/workflows/verify-aster-periodic-worker-live-*.yml",
    ),
    "settings": (
        "cloud_api/aster_multi_bb.py",
        "cloud_api/aster_multi_bb_core.py",
        "web/components/aster-bot-configurator-v2.tsx",
        "web/components/aster-bot-configurator-v3.tsx",
        "web/lib/aster-strategy2-settings-guard.ts",
        "web/app/api/exchanges/aster/strategy2/settings/route.ts",
        "web/components/portfolio-tp-seat-reset-target.tsx",
    ),
    "release_safety": (
        ".github/workflows/runtime-contract-v1.yml",
        ".github/workflows/cloud-backend-ci.yml",
        ".github/workflows/web-cloud-ci.yml",
        ".github/workflows/deploy-cloud-production.yml",
        "tools/runtime_contract_impact.py",
        "tools/runtime_contract_post_deploy.py",
        "tools/runtime_contract_snapshot.py",
        "cloud_api/test_runtime_contract_impact_matrix.py",
        "cloud_api/test_runtime_contract_post_deploy.py",
        "cloud_api/test_runtime_contract_snapshot.py",
        "cloud_api/test_runtime_contract_release_gate.py",
        "cloud_api/test_runtime_contract_release_safety_v1.py",
    ),
}


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def classify_files(files: Iterable[str]) -> dict[str, object]:
    normalized = sorted({str(path).strip().replace("\\", "/") for path in files if str(path).strip()})
    suites = {
        suite
        for suite, patterns in SUITE_PATTERNS.items()
        if any(_matches(path, patterns) for path in normalized)
    }

    cloud_paths = [path for path in normalized if path.startswith("cloud_api/") and path.endswith(".py")]
    explicitly_classified_cloud = [
        path for path in cloud_paths
        if any(_matches(path, patterns) for patterns in SUITE_PATTERNS.values())
    ]
    unknown_cloud = sorted(set(cloud_paths) - set(explicitly_classified_cloud))
    if unknown_cloud:
        suites.update(SUITE_TESTS)

    backend_tests = sorted({
        test
        for suite in suites
        for test in SUITE_TESTS.get(suite, ())
    })
    web_tests = sorted({
        test
        for suite in suites
        for test in WEB_SUITE_TESTS.get(suite, ())
    })

    return {
        "files": normalized,
        "suites": sorted(suites),
        "backendTests": backend_tests,
        "webTests": web_tests,
        "unknownCloudFiles": unknown_cloud,
        "conservativeFallback": bool(unknown_cloud),
    }


def _write_lines(path: str | None, rows: Iterable[str]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(f"{row}\n" for row in rows), encoding="utf-8")


def _append_github_output(path: str | None, result: dict[str, object]) -> None:
    if not path:
        return
    suites = set(result["suites"])
    lines = [
        f"has_backend_tests={'true' if result['backendTests'] else 'false'}",
        f"has_web_tests={'true' if result['webTests'] else 'false'}",
        f"conservative_fallback={'true' if result['conservativeFallback'] else 'false'}",
    ]
    lines.extend(f"suite_{name}={'true' if name in suites else 'false'}" for name in sorted(SUITE_TESTS))
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _append_summary(path: str | None, result: dict[str, object]) -> None:
    if not path:
        return
    suites = ", ".join(str(suite) for suite in result["suites"]) or "none"
    unknown = ", ".join(str(item) for item in result["unknownCloudFiles"]) or "none"
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(
            "## Runtime Contract V1 - impact analysis\n\n"
            f"- Selected suites: {suites}\n"
            f"- Backend contract files: **{len(result['backendTests'])}**\n"
            f"- Web contract files: **{len(result['webTests'])}**\n"
            f"- Conservative fallback: **{'YES' if result['conservativeFallback'] else 'NO'}**\n"
            f"- Unclassified backend files: {unknown}\n"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Select Amar Crypto Bot runtime contracts from changed files.")
    parser.add_argument("--files-file", required=True)
    parser.add_argument("--backend-tests-file")
    parser.add_argument("--web-tests-file")
    parser.add_argument("--github-output")
    parser.add_argument("--summary")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    files = Path(args.files_file).read_text(encoding="utf-8").splitlines()
    result = classify_files(files)
    _write_lines(args.backend_tests_file, result["backendTests"])
    _write_lines(args.web_tests_file, result["webTests"])
    _append_github_output(args.github_output, result)
    _append_summary(args.summary, result)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
