from __future__ import annotations

from pathlib import Path
import subprocess

MAIN = Path("cloud_api/main.py")
CURRENT = MAIN.read_text(encoding="utf-8")

if "def _portfolio_growth_client" in CURRENT:
    print("Portfolio Growth helpers already present; nothing to restore")
    raise SystemExit(0)

base = subprocess.check_output(
    ["git", "show", "origin/amar-crypto-bot-2026-cloud:cloud_api/main.py"],
    text=True,
)
start_marker = "def _portfolio_growth_client"
end_marker = '@app.get("/v1/me/aster/portfolio-growth/daily")'
start = base.index(start_marker)
end = base.index(end_marker, start)
helpers = base[start:end]

insert_at = CURRENT.index(end_marker)
restored = CURRENT[:insert_at] + helpers + CURRENT[insert_at:]
MAIN.write_text(restored, encoding="utf-8")
print("Restored exact Portfolio Growth helpers from amar-crypto-bot-2026-cloud")
