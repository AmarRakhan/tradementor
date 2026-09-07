from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
OUT = WEB / "public" / "portfolio-impact-states"
SCENE = "/portfolio-impact-premium-scene.svg"

OUT.mkdir(parents=True, exist_ok=True)
for old in OUT.glob("state-*.svg"):
    old.unlink()

for index in range(17):
    bias = (index - 8) / 8.0
    strength = abs(bias)
    impact_x = 360 + round(bias * 18)
    green = 0.10 + max(0.0, bias) * 0.24
    red = 0.10 + max(0.0, -bias) * 0.24
    lose_left = max(0.0, -bias) * 0.44
    lose_right = max(0.0, bias) * 0.44
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="606" viewBox="0 0 720 303" preserveAspectRatio="xMidYMid slice">
<defs>
  <radialGradient id="g"><stop stop-color="#24f3a0" stop-opacity=".72"/><stop offset="1" stop-color="#24f3a0" stop-opacity="0"/></radialGradient>
  <radialGradient id="r"><stop stop-color="#ff516e" stop-opacity=".72"/><stop offset="1" stop-color="#ff516e" stop-opacity="0"/></radialGradient>
  <linearGradient id="fadeL"><stop stop-color="#000" stop-opacity="{lose_left:.3f}"/><stop offset=".7" stop-color="#000" stop-opacity="0"/></linearGradient>
  <linearGradient id="fadeR" x1="1" x2="0"><stop stop-color="#000" stop-opacity="{lose_right:.3f}"/><stop offset=".7" stop-color="#000" stop-opacity="0"/></linearGradient>
  <filter id="spark" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>
<image href="{SCENE}" x="0" y="0" width="720" height="303"/>
<ellipse cx="155" cy="145" rx="215" ry="190" fill="url(#g)" opacity="{green:.3f}"/>
<ellipse cx="565" cy="145" rx="215" ry="190" fill="url(#r)" opacity="{red:.3f}"/>
<rect x="0" y="0" width="235" height="303" fill="url(#fadeL)"/>
<rect x="485" y="0" width="235" height="303" fill="url(#fadeR)"/>
<g transform="translate({impact_x} 143)" filter="url(#spark)" opacity=".96"><circle r="3.2" fill="#fff3b5"/><circle r="10" fill="none" stroke="#ffc35d" stroke-opacity=".58"/><path d="M-4 -6L-22 -28M5 -5L25 -25M-6 2L-29 14M6 3L31 17M0 7L3 31" stroke="#ffd36b" stroke-width="1.5" stroke-linecap="round"/></g>
</svg>'''
    (OUT / f"state-{index:02d}.svg").write_text(svg, encoding="utf-8")

print("Premium Portfolio Impact Bulls states generated")
