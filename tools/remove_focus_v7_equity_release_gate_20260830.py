from pathlib import Path

source = Path('cloud_api/aster_strategy2_focus_trailing.py').read_text(encoding='utf-8')
assert 'if price_release_ready and net_green_ready:' in source
assert 'equity_release_ready' not in source

replacements = {
    'cloud_api/test_aster_strategy2_focus_trailing.py': [
        ('test_v7_short_release_requires_price_plus_net_green_plus_equity',
         'test_v7_short_release_requires_price_plus_net_green_only'),
        ("if price_release_ready and net_green_ready and equity_release_ready:",
         "if price_release_ready and net_green_ready:"),
        ("assert 'equity_release_ready' in section",
         "assert 'equity_release_ready' not in section"),
    ],
    'cloud_api/test_focus_portfolio_cycle_v7.py': [
        ('test_simple_flow_release_requires_price_net_green_and_equity_and_keeps_rehedge_priority_exit',
         'test_simple_flow_release_requires_price_net_green_and_keeps_rehedge_priority_exit'),
        ("assert 'price_release_ready and net_green_ready and equity_release_ready' in section",
         "assert 'price_release_ready and net_green_ready:' in section"),
        ("assert 'equity_release_ready' in release",
         "assert 'equity_release_ready' not in release"),
        ("assert 'price_release_ready and net_green_ready and equity_release_ready' in release",
         "assert 'price_release_ready and net_green_ready:' in release"),
        ("src.split('# v7 equity protection:', 1)[1]",
         "src.split('# v7 equity protection may repair missing protection below the cycle baseline, but', 1)[1]"),
    ],
    'cloud_api/test_focus_v7_emergency_equity_lock.py': [
        ('src.index("# v7 equity protection:")',
         'src.index("# v7 equity protection may repair missing protection below the cycle baseline, but")'),
        ('test_equity_protection_does_not_freeze_normal_dca_and_release_stays_guarded',
         'test_equity_protection_does_not_freeze_normal_dca_and_release_stays_net_green_guarded'),
        ('assert "equity_release_ready" in release',
         'assert "equity_release_ready" not in release'),
        ('assert "price_release_ready and net_green_ready and equity_release_ready" in release',
         'assert "price_release_ready and net_green_ready:" in release'),
    ],
    'cloud_api/test_focus_v7_net_green_release.py': [
        ('test_release_requires_price_net_green_and_equity',
         'test_release_requires_price_and_net_green'),
        ('"price_release_ready and net_green_ready and equity_release_ready"',
         '"price_release_ready and net_green_ready:"'),
        ('"if price_release_ready and net_green_ready and equity_release_ready:"',
         '"if price_release_ready and net_green_ready:"'),
    ],
}

for filename, changes in replacements.items():
    path = Path(filename)
    text = path.read_text(encoding='utf-8')
    for old, new in changes:
        if old in text:
            text = text.replace(old, new)
    path.write_text(text, encoding='utf-8')

print('Migrated stale regression tests to the approved price + net-green release contract; strategy source unchanged.')
