from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected source block not found in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    multi = ROOT / "cloud_api/aster_multi_bb.py"
    text = multi.read_text(encoding="utf-8")
    if "entry_notional_long_usd: float" not in text:
        replace_once(
            "cloud_api/aster_multi_bb.py",
            '    entry_margin_long_usd: float = 5.0\n    entry_margin_short_usd: float = 5.0\n',
            '    entry_margin_long_usd: float = 5.0\n    entry_margin_short_usd: float = 5.0\n'
            '    entry_notional_long_usd: float = 250.0\n    entry_notional_short_usd: float = 250.0\n',
        )
        replace_once(
            "cloud_api/aster_multi_bb.py",
            '            "entry_margin_long_usd": _positive_ratio(source,("entryMarginLongUsd","entryMarginLong"),legacy_entry),\n'
            '            "entry_margin_short_usd": _positive_ratio(source,("entryMarginShortUsd","entryMarginShort"),legacy_entry),\n',
            '            "entry_margin_long_usd": _positive_ratio(source,("entryMarginLongUsd","entryMarginLong"),legacy_entry),\n'
            '            "entry_margin_short_usd": _positive_ratio(source,("entryMarginShortUsd","entryMarginShort"),legacy_entry),\n'
            '            "entry_notional_long_usd": _positive_ratio(source,("entryNotionalLongUsd","entryNotionalLong","entryNotionalUsd"),base.entry_notional_usd),\n'
            '            "entry_notional_short_usd": _positive_ratio(source,("entryNotionalShortUsd","entryNotionalShort"),base.entry_notional_usd),\n',
        )
        replace_once(
            "cloud_api/aster_multi_bb.py",
            '        if any(not math.isfinite(x) or x <= 0 for x in (self.entry_margin_long_usd,self.entry_margin_short_usd)): raise ValueError("Instap LONG/SHORT moet positief zijn")\n',
            '        if any(not math.isfinite(x) or x <= 0 for x in (self.entry_margin_long_usd,self.entry_margin_short_usd)): raise ValueError("Instapmargin LONG/SHORT moet positief zijn")\n'
            '        if any(not math.isfinite(x) or x <= 0 for x in (self.entry_notional_long_usd,self.entry_notional_short_usd)): raise ValueError("Positieomvang LONG/SHORT moet positief zijn")\n',
        )
        replace_once(
            "cloud_api/aster_multi_bb.py",
            '            "entryMarginUsd":self.entry_margin_long_usd,\n'
            '            "entryMarginLongUsd":self.entry_margin_long_usd, "entryMarginShortUsd":self.entry_margin_short_usd,\n'
            '            "entryMarginLong":self.entry_margin_long_usd, "entryMarginShort":self.entry_margin_short_usd,\n',
            '            "entryMarginUsd":self.entry_margin_long_usd,\n'
            '            "entryMarginLongUsd":self.entry_margin_long_usd, "entryMarginShortUsd":self.entry_margin_short_usd,\n'
            '            "entryMarginLong":self.entry_margin_long_usd, "entryMarginShort":self.entry_margin_short_usd,\n'
            '            "entryNotionalUsd":self.entry_notional_long_usd,\n'
            '            "entryNotionalLongUsd":self.entry_notional_long_usd, "entryNotionalShortUsd":self.entry_notional_short_usd,\n'
            '            "entryNotionalLong":self.entry_notional_long_usd, "entryNotionalShort":self.entry_notional_short_usd,\n',
        )
        replace_once(
            "cloud_api/aster_multi_bb.py",
            '_SHARED_ATTR_TO_KEY = {"minimum_leverage":"minimumLeverage",\n'
            '                       "entry_notional_usd":"entryNotionalUsd","unlimited_dca":"unlimitedDca",\n',
            '_SHARED_ATTR_TO_KEY = {"minimum_leverage":"minimumLeverage",\n'
            '                       "unlimited_dca":"unlimitedDca",\n',
        )
        replace_once(
            "cloud_api/aster_multi_bb.py",
            'def _side_value(base: MultiBbConfig, override: dict[str,Any], side: str, kind: str) -> Any:\n'
            '    is_short=side=="SHORT"\n'
            '    if kind=="entry_margin_usd": return override.get("entryMarginUsd",base.entry_margin_short_usd if is_short else base.entry_margin_long_usd)\n',
            'def _side_value(base: MultiBbConfig, override: dict[str,Any], side: str, kind: str) -> Any:\n'
            '    is_short=side=="SHORT"\n'
            '    if kind=="entry_margin_usd": return override.get("entryMarginUsd",base.entry_margin_short_usd if is_short else base.entry_margin_long_usd)\n'
            '    if kind=="entry_notional_usd":\n'
            '        side_key="entryNotionalShortUsd" if is_short else "entryNotionalLongUsd"\n'
            '        legacy_key="entryNotionalShort" if is_short else "entryNotionalLong"\n'
            '        fallback=base.entry_notional_short_usd if is_short else base.entry_notional_long_usd\n'
            '        return override.get(side_key,override.get(legacy_key,override.get("entryNotionalUsd",fallback)))\n',
        )
        replace_once(
            "cloud_api/aster_multi_bb.py",
            '        if name in {"entry_margin_usd","dca_distance","dca_margin_usd","max_dca","take_profit"}:\n'
            '            legacy_key={"entry_margin_usd":"entryMarginUsd","dca_distance":"dcaDistance","dca_margin_usd":"dcaMarginUsd","max_dca":"maxDca","take_profit":"takeProfit"}[name]\n',
            '        if name in {"entry_margin_usd","entry_notional_usd","dca_distance","dca_margin_usd","max_dca","take_profit"}:\n'
            '            legacy_key={"entry_margin_usd":"entryMarginUsd","entry_notional_usd":"entryNotionalUsd","dca_distance":"dcaDistance","dca_margin_usd":"dcaMarginUsd","max_dca":"maxDca","take_profit":"takeProfit"}[name]\n',
        )
        replace_once(
            "cloud_api/aster_multi_bb.py",
            '            if name=="entry_margin_usd": return base.entry_margin_long_usd\n',
            '            if name=="entry_margin_usd": return base.entry_margin_long_usd\n'
            '            if name=="entry_notional_usd": return base.entry_notional_long_usd\n',
        )
        replace_once(
            "cloud_api/aster_multi_bb.py",
            '        "entryMarginLongUsd":_side_value(settings,override,"LONG","entry_margin_usd"),\n'
            '        "entryMarginShortUsd":_side_value(settings,override,"SHORT","entry_margin_usd"),\n',
            '        "entryMarginLongUsd":_side_value(settings,override,"LONG","entry_margin_usd"),\n'
            '        "entryMarginShortUsd":_side_value(settings,override,"SHORT","entry_margin_usd"),\n'
            '        "entryNotionalLongUsd":_side_value(settings,override,"LONG","entry_notional_usd"),\n'
            '        "entryNotionalShortUsd":_side_value(settings,override,"SHORT","entry_notional_usd"),\n',
        )
        replace_once(
            "cloud_api/aster_multi_bb.py",
            '            updated["smartRescue"]=build_smart_rescue_position_state(\n'
            '                initial_entry_price=entry,start_margin_usd=settings.entry_margin_long_usd,\n',
            '            leverage=max(1,_integer(row.get("leverage"),settings.minimum_leverage))\n'
            '            start_margin=(settings.entry_notional_long_usd/leverage\n'
            '                if settings.entry_sizing_mode=="notional" else settings.entry_margin_long_usd)\n'
            '            updated["smartRescue"]=build_smart_rescue_position_state(\n'
            '                initial_entry_price=entry,start_margin_usd=start_margin,\n',
        )

    main = ROOT / "cloud_api/main.py"
    text = main.read_text(encoding="utf-8")
    if "entryNotionalUsd: float | None = Query" not in text:
        replace_once(
            "cloud_api/main.py",
            '    entryMarginUsd: float | None = Query(default=None, gt=0, le=100000),\n'
            '    dcaMarginUsd: float | None = Query(default=None, gt=0, le=100000),\n',
            '    entryMarginUsd: float | None = Query(default=None, gt=0, le=100000),\n'
            '    entryNotionalUsd: float | None = Query(default=None, gt=0, le=1000000),\n'
            '    entrySizingMode: str | None = Query(default=None, pattern="^(margin|notional)$"),\n'
            '    dcaMarginUsd: float | None = Query(default=None, gt=0, le=100000),\n',
        )
        replace_once(
            "cloud_api/main.py",
            '    if entryMarginUsd is not None:\n'
            '        overrides["entryMarginUsd"] = float(entryMarginUsd); overrides["entrySizingMode"] = "margin"\n'
            '    if dcaMarginUsd is not None: overrides["dcaMarginUsd"] = float(dcaMarginUsd)\n',
            '    if entrySizingMode is not None: overrides["entrySizingMode"] = str(entrySizingMode)\n'
            '    if entryNotionalUsd is not None:\n'
            '        overrides["entryNotionalUsd"] = float(entryNotionalUsd)\n'
            '        if entrySizingMode is None: overrides["entrySizingMode"] = "notional"\n'
            '    if entryMarginUsd is not None:\n'
            '        overrides["entryMarginUsd"] = float(entryMarginUsd)\n'
            '        if entrySizingMode is None and entryNotionalUsd is None: overrides["entrySizingMode"] = "margin"\n'
            '    if dcaMarginUsd is not None: overrides["dcaMarginUsd"] = float(dcaMarginUsd)\n',
        )

    text = main.read_text(encoding="utf-8")
    marker = '"maximumLeverage":settings.maximum_leverage,"entryNotionalUsd":settings.entry_notional_usd,\n            "dcaDistance"'
    if marker in text:
        text = text.replace(
            marker,
            '"maximumLeverage":settings.maximum_leverage,"entrySizingMode":settings.entry_sizing_mode,\n'
            '            "entryMarginLongUsd":settings.entry_margin_long_usd,"entryMarginShortUsd":settings.entry_margin_short_usd,\n'
            '            "entryNotionalUsd":settings.entry_notional_usd,"entryNotionalLongUsd":settings.entry_notional_long_usd,\n'
            '            "entryNotionalShortUsd":settings.entry_notional_short_usd,\n'
            '            "dcaDistance"',
            1,
        )
        old = '        "simulationChecks":{"maximumLeverage":{"pairMaximumLeverage":example_pair_max,"effectiveLeverage":example_effective,\n'
        new = (
            '        "simulationChecks":{"positionSizing":{"mode":settings.entry_sizing_mode,\n'
            '                "exampleNotionalUsd":6.0,"marginAt20x":0.30,"marginAt50x":0.12,"marginAt100x":0.06,\n'
            '                "notionalConstantWhenEnabled":settings.entry_sizing_mode=="notional"},\n'
            '            "maximumLeverage":{"pairMaximumLeverage":example_pair_max,"effectiveLeverage":example_effective,\n'
        )
        if old not in text:
            raise SystemExit("simulate block not found")
        text = text.replace(old, new, 1)
        text = text.replace(
            '"message":"Nieuwe Multi DCA-configuratie gevalideerd; leverage-cap en Stoploss zijn veilig gesimuleerd; er zijn 0 orders verzonden."}',
            '"message":"Multi DCA veilig gesimuleerd: sizing-mode, leverage-cap en Stoploss gevalideerd; 0 orders verzonden."}',
            1,
        )
        main.write_text(text, encoding="utf-8")

    test_path = ROOT / "cloud_api/test_fixed_position_size.py"
    test_path.write_text(
        """from pathlib import Path

import pytest

from aster_leverage_tiers import resolve_entry
from aster_multi_bb import MultiBbConfig, effective_pair_settings


def payload(maximum: int):
    return [{"symbol": "TESTUSDT", "brackets": [{"notionalFloor": "0", "notionalCap": "1000000",
        "initialLeverage": maximum, "maintMarginRatio": "0.004"}]}]


def resolved(maximum: int, mode: str, margin: float = .30, notional: float = 6.0):
    return resolve_entry(payload(maximum), "TESTUSDT", configured_minimum=1, configured_maximum=maximum,
        entry_margin_usd=margin, entry_notional_usd=notional, entry_sizing_mode=mode)


def test_fixed_position_size_keeps_six_usdt_notional_across_leverage():
    at20 = resolved(20, "notional"); at50 = resolved(50, "notional"); at100 = resolved(100, "notional")
    assert at20["orderNotional"] == pytest.approx(6.0)
    assert at50["orderNotional"] == pytest.approx(6.0)
    assert at100["orderNotional"] == pytest.approx(6.0)
    assert at20["orderNotional"] / at20["leverage"] == pytest.approx(.30)
    assert at50["orderNotional"] / at50["leverage"] == pytest.approx(.12)
    assert at100["orderNotional"] / at100["leverage"] == pytest.approx(.06)


def test_margin_mode_retains_existing_variable_notional_behavior():
    assert resolved(20, "margin")["orderNotional"] == pytest.approx(6.0)
    assert resolved(50, "margin")["orderNotional"] == pytest.approx(15.0)


def test_side_specific_notional_roundtrips_without_collapsing_long_and_short():
    cfg = MultiBbConfig.from_mapping({"engine": "multi_bb_v1", "universeTopN": 50, "maximumPositions": 20,
        "longSlots": 10, "shortSlots": 10, "minimumLeverage": 20, "maximumLeverage": 50,
        "entrySizingMode": "notional", "entryMarginUsd": .30, "entryMarginLongUsd": .30,
        "entryMarginShortUsd": .30, "entryNotionalUsd": 6, "entryNotionalLongUsd": 6,
        "entryNotionalShortUsd": 9, "dcaMarginUsd": 2, "takeProfit": .015})
    public = cfg.public_dict(); effective = effective_pair_settings(cfg, "TESTUSDT")
    assert public["entrySizingMode"] == "notional"
    assert public["entryNotionalLongUsd"] == pytest.approx(6)
    assert public["entryNotionalShortUsd"] == pytest.approx(9)
    assert effective["entryNotionalLongUsd"] == pytest.approx(6)
    assert effective["entryNotionalShortUsd"] == pytest.approx(9)
    assert public["maximumLeverage"] == 50


def test_smart_rescue_notional_mode_derives_start_margin_from_actual_leverage():
    source = Path(__file__).with_name("aster_multi_bb.py").read_text(encoding="utf-8")
    assert "settings.entry_notional_long_usd/leverage" in source
    assert 'if settings.entry_sizing_mode=="notional" else settings.entry_margin_long_usd' in source
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
