from pathlib import Path
p=Path('cloud_api/main.py')
s=p.read_text()
old='if not management_only and not ownership_isolated and not protection_selected and not take_profit_selected and pending_reopens and pending_reopen_attempt_ready and enabled:'
new='if not ownership_isolated and not protection_selected and not take_profit_selected and pending_reopens and pending_reopen_attempt_ready and enabled and not management_only:'
if s.count(old)!=1:
    raise SystemExit(f'expected one pending-reopen realtime condition, found {s.count(old)}')
p.write_text(s.replace(old,new,1))
