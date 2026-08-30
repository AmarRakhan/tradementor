from pathlib import Path

p = Path('tools/update_focus_portfolio_v7_contract_tests.py')
text = p.read_text(encoding='utf-8')
wrong = "    'def test_v6_release_is_blocked_when_price_ready_but_short_net_red(monkeypatch):',\n"
right = "    'def test_v6_simple_dca_ratchets_in_both_hedged_and_long_only_states():',\n"
if wrong in text:
    text = text.replace(wrong, right, 1)
start = text.find('# The next old runtime test explicitly asserted a red short blocked release.')
end = text.find('# Reserve is deliberately NOT a release gate in v7.', start)
if start >= 0 and end > start:
    text = text[:start] + text[end:]
p.write_text(text, encoding='utf-8')
print('Focus portfolio v7 contract migration markers fixed')
