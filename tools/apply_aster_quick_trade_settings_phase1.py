from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_navigation() -> None:
    path = ROOT / "web/components/markets-navigation-bridge.tsx"
    text = path.read_text(encoding="utf-8")
    old = '''function syncNavigation(active: boolean) {
  syncContext(active);
  for (const nav of document.querySelectorAll<HTMLElement>(".rail-nav, .bottom-nav")) {
    let button = nav.querySelector<HTMLButtonElement>('[data-destination="markets"]');
    const aster = nav.querySelector<HTMLElement>('[data-destination="aster"]');
    if (!button && aster) {
      button = marketsButton();
      nav.insertBefore(button, aster);
    }
    if (nav.classList.contains("bottom-nav")) {
      const count = nav.querySelectorAll(":scope > .nav-button").length;
      nav.style.setProperty("--mobile-nav-count", String(count));
    }
    if (active) {
      for (const item of nav.querySelectorAll<HTMLElement>(".nav-button")) {
        const selected = item.dataset.destination === "markets";
        item.classList.toggle("active", selected);
        item.setAttribute("aria-pressed", String(selected));
      }
    } else if (button) {
      button.classList.remove("active");
      button.setAttribute("aria-pressed", "false");
    }
  }
}
'''
    new = '''const USER_MAIN_DESTINATIONS = ["markets", "aster", "journey", "wallet"] as const;
const HIDDEN_MAIN_DESTINATIONS = new Set(["positions", "risk", "hyperliquid", "admin"]);

function syncNavigation(active: boolean) {
  syncContext(active);
  for (const nav of document.querySelectorAll<HTMLElement>(".rail-nav, .bottom-nav")) {
    for (const item of nav.querySelectorAll<HTMLElement>(".nav-button[data-destination]")) {
      const destination = item.dataset.destination || "";
      if (HIDDEN_MAIN_DESTINATIONS.has(destination)) item.remove();
    }
    let button = nav.querySelector<HTMLButtonElement>('[data-destination="markets"]');
    const aster = nav.querySelector<HTMLElement>('[data-destination="aster"]');
    if (!button && aster) {
      button = marketsButton();
      nav.insertBefore(button, aster);
    }
    const byDestination = new Map(
      Array.from(nav.querySelectorAll<HTMLElement>(".nav-button[data-destination]")).map((item) => [item.dataset.destination || "", item]),
    );
    for (const destination of USER_MAIN_DESTINATIONS) {
      const item = byDestination.get(destination);
      if (item) nav.appendChild(item);
    }
    if (nav.classList.contains("bottom-nav")) nav.style.setProperty("--mobile-nav-count", "4");
    if (active) {
      for (const item of nav.querySelectorAll<HTMLElement>(".nav-button")) {
        const selected = item.dataset.destination === "markets";
        item.classList.toggle("active", selected);
        item.setAttribute("aria-pressed", String(selected));
      }
    } else if (button) {
      button.classList.remove("active");
      button.setAttribute("aria-pressed", "false");
    }
  }
}
'''
    if old not in text:
        raise SystemExit("navigation anchor not found")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_multi_bb_config() -> None:
    path = ROOT / "cloud_api/aster_multi_bb.py"
    replace_once(path, "from dataclasses import dataclass\n", "from dataclasses import dataclass, field\n")
    replace_once(
        path,
        '''    manual_symbol_selection_enabled: bool = False
    manual_symbols: tuple[tuple[str, str], ...] = ()
''',
        '''    manual_symbol_selection_enabled: bool = False
    manual_symbols: tuple[tuple[str, str], ...] = ()
    standard_long: dict[str, Any] = field(default_factory=dict)
    standard_short: dict[str, Any] = field(default_factory=dict)
    pair_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
''',
    )
    replace_once(
        path,
        '''        cfg = cls(
''',
        '''        def normalized_profile(value: Any) -> dict[str, Any]:
            if not isinstance(value, dict):
                return {}
            allowed = {"entryMarginUsd", "entryNotionalUsd", "entrySizingMode", "minimumLeverage", "dcaDistance", "dcaMarginUsd", "maxDca", "unlimitedDca", "takeProfit", "autoRestart"}
            return {str(k): v for k, v in value.items() if str(k) in allowed}
        standard_long = normalized_profile(raw.get("standardLong"))
        standard_short = normalized_profile(raw.get("standardShort"))
        override_rows = raw.get("pairOverrides") if isinstance(raw.get("pairOverrides"), dict) else {}
        pair_overrides: dict[str, dict[str, Any]] = {}
        for raw_symbol, raw_override in override_rows.items():
            symbol = str(raw_symbol).upper().strip()
            if symbol and symbol.endswith("USDT"):
                normalized = normalized_profile(raw_override)
                if normalized:
                    pair_overrides[symbol] = normalized
        cfg = cls(
''',
    )
    replace_once(
        path,
        '''            manual_symbol_selection_enabled=manual_enabled,
            manual_symbols=tuple(manual_symbols),
        )
''',
        '''            manual_symbol_selection_enabled=manual_enabled,
            manual_symbols=tuple(manual_symbols),
            standard_long=standard_long,
            standard_short=standard_short,
            pair_overrides=pair_overrides,
        )
''',
    )
    replace_once(
        path,
        '''        if len(self.manual_symbols) > 200: raise ValueError("Maximaal 200 handmatig gekozen munten")
        return self
''',
        '''        if len(self.manual_symbols) > 200: raise ValueError("Maximaal 200 handmatig gekozen munten")
        for label, profile in (("STANDARD LONG", self.standard_long), ("STANDARD SHORT", self.standard_short)):
            if "minimumLeverage" in profile and not 1 <= _i(profile.get("minimumLeverage")) <= 300: raise ValueError(f"{label}: leverage moet tussen 1x en 300x liggen")
            if "maxDca" in profile and _i(profile.get("maxDca")) < 0: raise ValueError(f"{label}: Max DCA mag niet negatief zijn")
            if "dcaDistance" in profile and not .0001 <= _f(profile.get("dcaDistance")) <= .50: raise ValueError(f"{label}: DCA-afstand is ongeldig")
            if "takeProfit" in profile and not .001 <= _f(profile.get("takeProfit")) <= .20: raise ValueError(f"{label}: Take Profit moet tussen 0,1% en 20% liggen")
        if len(self.pair_overrides) > 200: raise ValueError("Maximaal 200 pair-overrides")
        return self
''',
    )
    replace_once(
        path,
        '''            "manualSymbolSelectionEnabled": self.manual_symbol_selection_enabled,
            "manualSymbols": [{"symbol": symbol, "side": side} for symbol, side in self.manual_symbols],
        }
''',
        '''            "manualSymbolSelectionEnabled": self.manual_symbol_selection_enabled,
            "manualSymbols": [{"symbol": symbol, "side": side} for symbol, side in self.manual_symbols],
            "standardLong": dict(self.standard_long),
            "standardShort": dict(self.standard_short),
            "pairOverrides": {symbol: dict(value) for symbol, value in self.pair_overrides.items()},
        }

    def effective_profile(self, symbol: str, side: str) -> dict[str, Any]:
        profile = dict(self.standard_long if str(side).upper() == "LONG" else self.standard_short)
        profile.update(self.pair_overrides.get(str(symbol).upper().strip(), {}))
        return {
            "minimumLeverage": _i(profile.get("minimumLeverage"), self.minimum_leverage),
            "entryMarginUsd": _f(profile.get("entryMarginUsd"), self.entry_margin_usd),
            "entryNotionalUsd": _f(profile.get("entryNotionalUsd"), self.entry_notional_usd),
            "entrySizingMode": str(profile.get("entrySizingMode", self.entry_sizing_mode)).lower().strip(),
            "dcaDistance": _f(profile.get("dcaDistance"), self.dca_distance),
            "dcaMarginUsd": _f(profile.get("dcaMarginUsd"), self.dca_margin_usd),
            "maxDca": _i(profile.get("maxDca"), self.max_dca),
            "unlimitedDca": bool(profile.get("unlimitedDca", self.unlimited_dca)),
            "takeProfit": _f(profile.get("takeProfit"), self.take_profit),
            "autoRestart": bool(profile.get("autoRestart", True)),
        }
''',
    )
    replace_once(
        path,
        '''    tp_price = entry * (1 + settings.take_profit if side == "LONG" else 1 - settings.take_profit)
''',
        '''    effective = settings.effective_profile(str(row.get("symbol", "")), side)
    take_profit = _f(effective.get("takeProfit"), settings.take_profit)
    tp_price = entry * (1 + take_profit if side == "LONG" else 1 - take_profit)
''',
    )
    replace_once(
        path,
        '''    dca_allowed = settings.unlimited_dca or dca_count < settings.max_dca
    next_dca_price = anchor * (1 - settings.dca_distance if side == "LONG" else 1 + settings.dca_distance) if dca_allowed and anchor > 0 else None
''',
        '''    effective_max_dca = _i(effective.get("maxDca"), settings.max_dca)
    effective_unlimited = bool(effective.get("unlimitedDca", settings.unlimited_dca))
    effective_distance = _f(effective.get("dcaDistance"), settings.dca_distance)
    dca_allowed = effective_unlimited or dca_count < effective_max_dca
    next_dca_price = anchor * (1 - effective_distance if side == "LONG" else 1 + effective_distance) if dca_allowed and anchor > 0 else None
''',
    )
    replace_once(path, '        "takeProfitPct": settings.take_profit * 100,\n', '        "takeProfitPct": take_profit * 100,\n')
    replace_once(path, '        "unlimitedDca": settings.unlimited_dca,\n', '        "unlimitedDca": effective_unlimited,\n        "maxDca": effective_max_dca,\n        "customSettings": bool(settings.pair_overrides.get(str(row.get("symbol", "")).upper().strip())),\n')
    replace_once(
        path,
        '''        tp_price = entry * (1 + settings.take_profit if side == "LONG" else 1 - settings.take_profit)
''',
        '''        effective = settings.effective_profile(symbol, side)
        take_profit = _f(effective.get("takeProfit"), settings.take_profit)
        tp_price = entry * (1 + take_profit if side == "LONG" else 1 - take_profit)
''',
    )
    replace_once(
        path,
        '''        dca_count = _i(st0.get("dcaCount")); anchor = _f(st0.get("lastBotFillPrice"), entry)
        if (not settings.unlimited_dca and dca_count >= settings.max_dca) or anchor <= 0: continue
        trigger = anchor * (1 - settings.dca_distance if side == "LONG" else 1 + settings.dca_distance)
''',
        '''        dca_count = _i(st0.get("dcaCount")); anchor = _f(st0.get("lastBotFillPrice"), entry)
        effective_max_dca = _i(effective.get("maxDca"), settings.max_dca)
        effective_unlimited = bool(effective.get("unlimitedDca", settings.unlimited_dca))
        effective_distance = _f(effective.get("dcaDistance"), settings.dca_distance)
        if (not effective_unlimited and dca_count >= effective_max_dca) or anchor <= 0: continue
        trigger = anchor * (1 - effective_distance if side == "LONG" else 1 + effective_distance)
''',
    )
    replace_once(
        path,
        '''        try: plan, tier = _plan_add(client, row_info, mark, settings.dca_margin_usd, leverage, qty * mark, settings.minimum_leverage)
''',
        '''        try: plan, tier = _plan_add(client, row_info, mark, _f(effective.get("dcaMarginUsd"), settings.dca_margin_usd), leverage, qty * mark, _i(effective.get("minimumLeverage"), settings.minimum_leverage))
''',
    )
    replace_once(
        path,
        '''        try: plan, tier = _plan_new(client, info_map[symbol], prices[symbol], entry_margin_usd=settings.entry_margin_usd, entry_notional_usd=settings.entry_notional_usd, entry_sizing_mode=settings.entry_sizing_mode, minimum_leverage=settings.minimum_leverage)
''',
        '''        effective = settings.effective_profile(symbol, side)
        try: plan, tier = _plan_new(client, info_map[symbol], prices[symbol], entry_margin_usd=_f(effective.get("entryMarginUsd"), settings.entry_margin_usd), entry_notional_usd=_f(effective.get("entryNotionalUsd"), settings.entry_notional_usd), entry_sizing_mode=str(effective.get("entrySizingMode", settings.entry_sizing_mode)), minimum_leverage=_i(effective.get("minimumLeverage"), settings.minimum_leverage))
''',
    )


def add_tests() -> None:
    path = ROOT / "cloud_api/test_aster_quick_trade_profiles.py"
    path.write_text('''from aster_multi_bb import MultiBbConfig, position_action_preview\n\n\ndef test_profiles_and_pair_overrides_round_trip():\n    cfg = MultiBbConfig.from_mapping({\n        "engine": "multi_bb_v1", "maximumPositions": 2, "longSlots": 1, "shortSlots": 1,\n        "standardLong": {"minimumLeverage": 100, "maxDca": 3, "takeProfit": .015},\n        "standardShort": {"minimumLeverage": 50, "maxDca": 2, "takeProfit": .01},\n        "pairOverrides": {"btcusdt": {"maxDca": 5}},\n    })\n    saved = cfg.public_dict()\n    assert saved["standardLong"]["minimumLeverage"] == 100\n    assert saved["standardShort"]["maxDca"] == 2\n    assert saved["pairOverrides"]["BTCUSDT"]["maxDca"] == 5\n    assert cfg.effective_profile("BTCUSDT", "LONG")["maxDca"] == 5\n    assert cfg.effective_profile("ETHUSDT", "LONG")["maxDca"] == 3\n\n\ndef test_pair_override_extends_existing_dca_without_reset():\n    cfg = MultiBbConfig.from_mapping({\n        "engine": "multi_bb_v1", "maximumPositions": 2, "longSlots": 1, "shortSlots": 1,\n        "maxDca": 3, "pairOverrides": {"BTCUSDT": {"maxDca": 5}},\n    })\n    row = {"symbol": "BTCUSDT", "positionSide": "LONG", "entryPrice": 100, "markPrice": 100, "positionAmt": 1}\n    preview = position_action_preview(row=row, state={"dcaCount": 3, "lastBotFillPrice": 100}, settings=cfg, account_equity=1000)\n    assert preview["maxDca"] == 5\n    assert preview["nextDcaNumber"] == 4\n    assert preview["customSettings"] is True\n''', encoding="utf-8")


def main() -> None:
    patch_navigation()
    patch_multi_bb_config()
    add_tests()


if __name__ == "__main__":
    main()
