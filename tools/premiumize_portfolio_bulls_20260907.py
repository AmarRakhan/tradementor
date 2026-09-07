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
REFERENCE.write_bytes(base64.b64decode(encoded))
if REFERENCE.stat().st_size < 40_000:
    raise SystemExit("Premium reference WebP is unexpectedly small")

FRAME_DIR.mkdir(parents=True, exist_ok=True)
for old in FRAME_DIR.glob("frame-*.svg"):
    old.unlink()

# 201 frames = 0.5 percentage-point increments from LONG 0.0% to 100.0%.
# 50 -> 40 therefore traverses exactly 20 adjacent frames, never a large visual jump.
for index in range(201):
    long_share = index / 2.0
    bias = (long_share - 50.0) / 50.0
    source_shift = round(bias * 92)
    source_x = -90 + source_shift
    impact_x = 360 + round(bias * 38)
    green = 0.10 + max(0.0, bias) * 0.28
    red = 0.10 + max(0.0, -bias) * 0.28
    lose_left = max(0.0, -bias) * 0.55
    lose_right = max(0.0, bias) * 0.55
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="888" viewBox="0 0 720 444" preserveAspectRatio="xMidYMid slice">
<defs>
  <linearGradient id="bg" x1="0" x2="1"><stop stop-color="#00130b"/><stop offset=".48" stop-color="#07100b"/><stop offset=".52" stop-color="#110707"/><stop offset="1" stop-color="#190007"/></linearGradient>
  <radialGradient id="g"><stop stop-color="#25f4a0" stop-opacity=".78"/><stop offset="1" stop-color="#25f4a0" stop-opacity="0"/></radialGradient>
  <radialGradient id="r"><stop stop-color="#ff506e" stop-opacity=".78"/><stop offset="1" stop-color="#ff506e" stop-opacity="0"/></radialGradient>
  <linearGradient id="fadeL"><stop stop-color="#000" stop-opacity="{lose_left:.3f}"/><stop offset=".86" stop-color="#000" stop-opacity="0"/></linearGradient>
  <linearGradient id="fadeR" x1="1" x2="0"><stop stop-color="#000" stop-opacity="{lose_right:.3f}"/><stop offset=".86" stop-color="#000" stop-opacity="0"/></linearGradient>
  <linearGradient id="centerMask" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#020705" stop-opacity=".985"/><stop offset=".72" stop-color="#020705" stop-opacity=".90"/><stop offset="1" stop-color="#020705" stop-opacity="0"/></linearGradient>
  <linearGradient id="footerMask" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#020705" stop-opacity="0"/><stop offset=".34" stop-color="#020705" stop-opacity=".72"/><stop offset="1" stop-color="#020705" stop-opacity=".985"/></linearGradient>
  <filter id="spark" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>
<rect width="720" height="444" fill="url(#bg)"/>
<ellipse cx="145" cy="215" rx="270" ry="215" fill="url(#g)" opacity="{green:.3f}"/>
<ellipse cx="575" cy="215" rx="270" ry="215" fill="url(#r)" opacity="{red:.3f}"/>
<image href="/portfolio-impact-premium-reference.webp" x="{source_x}" y="68" width="900" height="363" preserveAspectRatio="xMidYMid slice"/>
<rect x="0" y="65" width="255" height="190" fill="#03110b" opacity=".74"/>
<rect x="465" y="65" width="255" height="190" fill="#150307" opacity=".74"/>
<rect x="232" y="49" width="256" height="105" fill="url(#centerMask)"/>
<rect x="0" y="65" width="255" height="300" fill="url(#fadeL)"/>
<rect x="465" y="65" width="255" height="300" fill="url(#fadeR)"/>
<rect x="0" y="333" width="720" height="111" fill="url(#footerMask)"/>
<g transform="translate({impact_x} 222)" filter="url(#spark)" opacity=".98"><circle r="3.8" fill="#fff5c4"/><circle r="12" fill="none" stroke="#ffc65f" stroke-opacity=".66"/><path d="M-4 -7L-27 -34M5 -6L29 -31M-7 2L-35 17M7 3L36 20M0 8L3 38" stroke="#ffd670" stroke-width="1.7" stroke-linecap="round"/></g>
<path d="M0 386 C84 365 132 381 205 361 S351 389 426 364 S575 386 720 358 L720 444 L0 444 Z" fill="#090c09" opacity=".58"/>
<path d="M0 400 C88 377 143 399 218 378 S361 404 442 380 S590 402 720 374" fill="none" stroke="#54594f" stroke-width="2" opacity=".28"/>
</svg>'''
    (FRAME_DIR / f"frame-{index:03d}.svg").write_text(svg, encoding="utf-8")

print(f"Premium Portfolio Impact reference: {REFERENCE.stat().st_size} bytes")
print("Generated 201 premium Bulls frames at 0.5 percentage-point granularity")
