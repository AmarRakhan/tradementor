from pathlib import Path


def test_settings_route_merges_old_side_specific_values():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    start = source.index('@app.put("/v1/me/aster/strategy2/settings")')
    block = source[start: source.index("\n@app.", start + 8)]
    assert "merged_settings = {**old, **request.settings}" in block
    assert "MultiBbConfig.from_mapping(merged_settings)" in block

def test_short_distance_is_separate_public_config():
    source = Path(__file__).with_name("aster_multi_bb.py").read_text(encoding="utf-8")
    assert '"shortDcaDistance":self.short_dca_distance' in source
