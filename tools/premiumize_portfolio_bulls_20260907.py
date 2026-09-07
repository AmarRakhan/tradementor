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
    shift = round(bias * 48)
    impact_x = 360 + shift
    green = 0.10 + max(0.0, bias) * 0.26
    red = 0.10 + max(0.0, -bias) * 0.26
    lose_left = max(0.0, -bias) * 0.48
    lose_right = max(0.0, bias) * 0.48
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="888" viewBox="0 0 720 444" preserveAspectRatio="xMidYMid slice">
<defs>
  <linearGradient id="bg" x1="0" x2="1"><stop stop-color="#00130b"/><stop offset=".47" stop-color="#070e0a"/><stop offset=".53" stop-color="#100706"/><stop offset="1" stop-color="#180006"/></linearGradient>
  <radialGradient id="g"><stop stop-color="#24f3a0" stop-opacity=".78"/><stop offset="1" stop-color="#24f3a0" stop-opacity="0"/></radialGradient>
  <radialGradient id="r"><stop stop-color="#ff516e" stop-opacity=".78"/><stop offset="1" stop-color="#ff516e" stop-opacity="0"/></radialGradient>
  <linearGradient id="fadeL"><stop stop-color="#000" stop-opacity="{lose_left:.3f}"/><stop offset=".8" stop-color="#000" stop-opacity="0"/></linearGradient>
  <linearGradient id="fadeR" x1="1" x2="0"><stop stop-color="#000" stop-opacity="{lose_right:.3f}"/><stop offset=".8" stop-color="#000" stop-opacity="0"/></linearGradient>
  <linearGradient id="top" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#010604" stop-opacity=".94"/><stop offset="1" stop-color="#010604" stop-opacity="0"/></linearGradient>
  <linearGradient id="bottom" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#010604" stop-opacity="0"/><stop offset="1" stop-color="#010604" stop-opacity=".98"/></linearGradient>
  <filter id="spark" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>
<rect width="720" height="444" fill="url(#bg)"/>
<ellipse cx="145" cy="220" rx="260" ry="205" fill="url(#g)" opacity="{green:.3f}"/>
<ellipse cx="575" cy="220" rx="260" ry="205" fill="url(#r)" opacity="{red:.3f}"/>
<image href="{SCENE}" x="{shift}" y="58" width="720" height="303" preserveAspectRatio="xMidYMid meet"/>
<rect x="0" y="58" width="245" height="303" fill="url(#fadeL)"/>
<rect x="475" y="58" width="245" height="303" fill="url(#fadeR)"/>
<rect x="0" y="0" width="720" height="88" fill="url(#top)"/>
<rect x="0" y="326" width="720" height="118" fill="url(#bottom)"/>
<g transform="translate({impact_x} 202)" filter="url(#spark)" opacity=".98"><circle r="3.6" fill="#fff4bd"/><circle r="11" fill="none" stroke="#ffc55f" stroke-opacity=".62"/><path d="M-4 -7L-24 -31M5 -6L27 -28M-7 2L-32 16M7 3L33 18M0 8L3 35" stroke="#ffd56f" stroke-width="1.6" stroke-linecap="round"/></g>
</svg>'''
    (OUT / f"state-{index:02d}.svg").write_text(svg, encoding="utf-8")

print("Premium Portfolio Impact Bulls states generated")
