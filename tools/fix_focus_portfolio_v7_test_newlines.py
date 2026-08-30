from pathlib import Path

p = Path('cloud_api/test_focus_portfolio_cycle_v7.py')
text = p.read_text(encoding='utf-8')
if '\\n' in text:
    p.write_text(text.replace('\\n', '\n'), encoding='utf-8')
print('Focus portfolio v7 generated test newlines normalized')
