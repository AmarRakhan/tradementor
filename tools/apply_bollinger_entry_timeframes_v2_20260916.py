from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "tools" / "apply_bollinger_entry_timeframes_20260916.py"
spec = importlib.util.spec_from_file_location("bb_tf_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load base patcher")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def patch_core() -> None:
    rel = "cloud_api/aster_multi_bb_core.py"
    text = base.read(rel)
    text = base.replace_once(
        text,
        "from aster_bollinger_entry_filter import BollingerEntryRejected, require_bollinger_entry",
        "from aster_bollinger_entry_filter import BollingerEntryRejected, DEFAULT_TIMEFRAME, normalize_bollinger_timeframe, require_bollinger_entry",
        "core import",
    )
    text = base.replace_once(
        text,
        "    bollinger_entry_filter_15m_enabled: bool = False\n    entry_margin_usd: float = 5.0",
        "    bollinger_entry_filter_15m_enabled: bool = False\n    bollinger_entry_filter_timeframe: str = DEFAULT_TIMEFRAME\n    entry_margin_usd: float = 5.0",
        "core dataclass timeframe",
    )
    text = base.replace_once(
        text,
        "            bollinger_entry_filter_15m_enabled=bool(raw.get(\"bollingerEntryFilter15mEnabled\", raw.get(\"bollinger_entry_filter_15m_enabled\", False))),\n            entry_margin_usd=entry_margin_usd,",
        "            bollinger_entry_filter_15m_enabled=bool(raw.get(\"bollingerEntryFilter15mEnabled\", raw.get(\"bollinger_entry_filter_15m_enabled\", False))),\n            bollinger_entry_filter_timeframe=normalize_bollinger_timeframe(raw.get(\"bollingerEntryFilterTimeframe\", raw.get(\"bollinger_entry_filter_timeframe\", DEFAULT_TIMEFRAME))),\n            entry_margin_usd=entry_margin_usd,",
        "core mapping timeframe",
    )
    text = base.replace_once(
        text,
        "            \"bollingerEntryFilter15mEnabled\": self.bollinger_entry_filter_15m_enabled,\n            \"entryMarginUsd\": self.entry_margin_usd,",
        "            \"bollingerEntryFilter15mEnabled\": self.bollinger_entry_filter_15m_enabled,\n            \"bollingerEntryFilterTimeframe\": self.bollinger_entry_filter_timeframe,\n            \"entryMarginUsd\": self.entry_margin_usd,",
        "core public timeframe",
    )
    text = base.replace_once(
        text,
        "require_bollinger_entry(client, symbol=symbol, side=candidate_side, enabled=True, live_price=prices[symbol],\n                                        force_refresh=False, stage=\"candidate\", now_ms=timestamp_ms)",
        "require_bollinger_entry(client, symbol=symbol, side=candidate_side, enabled=True, timeframe=settings.bollinger_entry_filter_timeframe,\n                                        live_price=prices[symbol], force_refresh=False, stage=\"candidate\", now_ms=timestamp_ms)",
        "candidate selected timeframe",
    )
    text = base.replace_once(
        text,
        "require_bollinger_entry(client, symbol=symbol, side=side, enabled=settings.bollinger_entry_filter_15m_enabled,\n                                        live_price=None, force_refresh=True, stage=\"pre_order\")",
        "require_bollinger_entry(client, symbol=symbol, side=side, enabled=settings.bollinger_entry_filter_15m_enabled,\n                                        timeframe=settings.bollinger_entry_filter_timeframe, live_price=None, force_refresh=True, stage=\"pre_order\")",
        "preorder selected timeframe",
    )
    text = base.replace_once(
        text,
        '        entry_status = "WAITING_BOLLINGER_ENTRY"; entry_reason = "Geen kandidaat voldoet nu aan het optionele 15m Bollinger-instapfilter; vrije stoel blijft leeg en wordt opnieuw gescand"',
        '        entry_status = "WAITING_BOLLINGER_ENTRY"; entry_reason = f"Geen kandidaat voldoet nu aan het optionele {settings.bollinger_entry_filter_timeframe} Bollinger-instapfilter; vrije stoel blijft leeg en wordt opnieuw gescand"',
        "dynamic waiting message",
    )
    text = base.replace_once(
        text,
        '              "bollingerEntryFilter15mEnabled": settings.bollinger_entry_filter_15m_enabled,\n              "asymmetricHedgeModeEnabled": settings.asymmetric_hedge_enabled,',
        '              "bollingerEntryFilter15mEnabled": settings.bollinger_entry_filter_15m_enabled, "bollingerEntryFilterTimeframe": settings.bollinger_entry_filter_timeframe,\n              "asymmetricHedgeModeEnabled": settings.asymmetric_hedge_enabled,',
        "report selected timeframe",
    )
    base.write(rel, text)


def main() -> None:
    base.patch_backend()
    patch_core()
    base.patch_card()
    base.patch_bridge()
    base.patch_tests()
    print("Applied selectable Bollinger entry timeframes v2: 1m,5m,15m,1h,4h,1d")


if __name__ == "__main__":
    main()
