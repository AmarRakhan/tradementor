from __future__ import annotations

import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
PUBLIC = WEB / "public"
FRAME_DIR = PUBLIC / "portfolio-impact-frames"
REFERENCE = PUBLIC / "portfolio-impact-premium-reference.webp"
PARTS = sorted((ROOT / "tools" / "assets").glob("premium-bulls-webp.b64.*"))

if len(PARTS) < 4:
    raise SystemExit(f"Expected premium reference asset chunks, found {len(PARTS)}")
encoded = "".join(part.read_text(encoding="utf-8").strip() for part in PARTS)
reference_bytes = base64.b64decode(encoded)
REFERENCE.write_bytes(reference_bytes)
if REFERENCE.stat().st_size < 40_000:
    raise SystemExit("Premium reference WebP is unexpectedly small")

# SVGs loaded through an <img> are isolated from external resources by browsers,
# so the approved reference is embedded directly in every frame.
REFERENCE_DATA_URI = f"data:image/webp;base64,{encoded}"

FRAME_DIR.mkdir(parents=True, exist_ok=True)
for old in FRAME_DIR.glob("frame-*.svg"):
    old.unlink()

# The approved Portfolio Impact artwork is 900x363. That ratio is binding: the
# artwork itself is the card. Never add a taller canvas around it or mask it into
# a smaller rectangle; that is what caused the former pasted-photo appearance.
W, H = 900, 363

# 201 frames = 0.5 percentage-point increments from LONG 0.0% to 100.0%.
# The composition never moves/crops between states. Market pressure is shown by
# restrained integrated light so timeframe transitions stay seamless.
for index in range(201):
    long_share = index / 2.0
    bias = (long_share - 50.0) / 50.0
    impact_x = 450 + round(bias * 24)
    green = 0.045 + max(0.0, bias) * 0.12
    red = 0.045 + max(0.0, -bias) * 0.12
    lose_left = max(0.0, -bias) * 0.18
    lose_right = max(0.0, bias) * 0.18

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="726" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice">
<defs>
  <radialGradient id="g"><stop stop-color="#20f29a" stop-opacity=".58"/><stop offset="1" stop-color="#20f29a" stop-opacity="0"/></radialGradient>
  <radialGradient id="r"><stop stop-color="#ff405f" stop-opacity=".58"/><stop offset="1" stop-color="#ff405f" stop-opacity="0"/></radialGradient>
  <linearGradient id="fadeL"><stop stop-color="#000" stop-opacity="{lose_left:.3f}"/><stop offset=".82" stop-color="#000" stop-opacity="0"/></linearGradient>
  <linearGradient id="fadeR" x1="1" x2="0"><stop stop-color="#000" stop-opacity="{lose_right:.3f}"/><stop offset=".82" stop-color="#000" stop-opacity="0"/></linearGradient>
  <linearGradient id="footerVeil" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#020705" stop-opacity="0"/><stop offset=".46" stop-color="#020705" stop-opacity=".14"/><stop offset="1" stop-color="#020705" stop-opacity=".48"/></linearGradient>
  <radialGradient id="centerVeil"><stop stop-color="#030806" stop-opacity=".54"/><stop offset=".58" stop-color="#030806" stop-opacity=".22"/><stop offset="1" stop-color="#030806" stop-opacity="0"/></radialGradient>
  <filter id="uiBlur" x="-22%" y="-22%" width="144%" height="144%"><feGaussianBlur stdDeviation="12.5"/></filter>
  <filter id="spark" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="1.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <clipPath id="leftUi"><rect x="10" y="36" width="170" height="216" rx="22"/></clipPath>
  <clipPath id="rightUi"><rect x="720" y="36" width="170" height="216" rx="22"/></clipPath>
  <clipPath id="centerUi"><rect x="246" y="0" width="408" height="112" rx="36"/></clipPath>
  <clipPath id="footerUi"><rect x="0" y="270" width="900" height="93"/></clipPath>
</defs>
<rect width="900" height="363" fill="#020705"/>
<image id="art" href="{REFERENCE_DATA_URI}" x="0" y="0" width="900" height="363" preserveAspectRatio="xMidYMid slice"/>
<!-- Blur only source text/value zones using the artwork itself. No opaque green,
     red or grey blocks are allowed: the scene and lighting must remain continuous. -->
<use href="#art" filter="url(#uiBlur)" clip-path="url(#leftUi)"/>
<use href="#art" filter="url(#uiBlur)" clip-path="url(#rightUi)"/>
<use href="#art" filter="url(#uiBlur)" clip-path="url(#centerUi)"/>
<use href="#art" filter="url(#uiBlur)" clip-path="url(#footerUi)"/>
<ellipse cx="150" cy="190" rx="255" ry="205" fill="url(#g)" opacity="{green:.3f}"/>
<ellipse cx="750" cy="190" rx="255" ry="205" fill="url(#r)" opacity="{red:.3f}"/>
<rect x="0" y="0" width="320" height="363" fill="url(#fadeL)"/>
<rect x="580" y="0" width="320" height="363" fill="url(#fadeR)"/>
<ellipse cx="450" cy="45" rx="205" ry="66" fill="url(#centerVeil)"/>
<rect x="0" y="264" width="900" height="99" fill="url(#footerVeil)"/>
<g transform="translate({impact_x} 191)" filter="url(#spark)" opacity=".38"><circle r="2.1" fill="#fff5c4"/><circle r="7.4" fill="none" stroke="#ffc65f" stroke-opacity=".34"/></g>
</svg>'''
    (FRAME_DIR / f"frame-{index:03d}.svg").write_text(svg, encoding="utf-8")

print(f"Premium Portfolio Impact reference: {REFERENCE.stat().st_size} bytes")
print("Generated 201 seamless full-bleed Bulls frames at the approved 900x363 composition")
