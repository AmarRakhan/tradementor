"""Regression contract: invalid legacy strategy settings cannot short-circuit account truth.

These tests are intentionally source-level; an authenticated end-to-end status
response test must also pass before production rollout.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS_SOURCE = ROOT / "cloud_api" / "main.py"


def test_status_handler_parses_and_isolates_invalid_multi_bb_configuration():
    source = STATUS_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "aster_status"
    )
    segment = ast.get_source_segment(source, handler)
    assert "except (ValueError, TypeError):" in segment
    assert "status_configuration_invalid=True" in segment
    assert 'settingsErrorCode"]="INVALID_PERSISTED_CONFIGURATION"' in segment
    assert 'public_response["accountTruth"] = build_aster_account_truth(' in segment


def test_status_handler_does_not_bypass_trading_configuration_validation():
    source = STATUS_SOURCE.read_text(encoding="utf-8")
    handler = source[source.index('def aster_status('):]
    assert "multi_status_settings=MultiBbConfig()" in handler
    assert "MultiBbConfig.from_mapping(multi_status_raw)" in handler
    assert "strategy2_public_error[\"settingsUnverified\"]=True" in handler
