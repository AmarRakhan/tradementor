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

REFERENCE_DATA_URI = f"data:image/webp;base64,{encoded}"

FRAME_DIR.mkdir(parents=True, exist_ok=True)
for old in FRAME_DIR.glob("frame-*.svg"):
    old.unlink()

# The approved Portfolio Impact composition is presented edge-to-edge in a
# 900x363 viewport. The original artwork is allowed to crop naturally into that
# viewport; no extra canvas or opaque masking blocks may be added around it.
W, H = 900, 363

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
  <linearGradient id="footerVeil" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#020705" stop-opacity="0"/><stop offset=".46" stop-color="#020705" stop-opacity=".12"/><stop offset="1" stop-color="#020705" stop-opacity=".44"/></linearGradient>
  <radialGradient id="centerVeil"><stop stop-color="#030806" stop-opacity=".48"/><stop offset=".56" stop-color="#030806" stop-opacity=".18"/><stop offset="1" stop-color="#030806" stop-opacity="0"/></radialGradient>
  <radialGradient id="centerMaskFade"><stop offset="0" stop-color="#fff" stop-opacity="1"/><stop offset=".56" stop-color="#fff" stop-opacity=".98"/><stop offset=".79" stop-color="#fff" stop-opacity=".50"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
  <linearGradient id="footerMaskFade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".26" stop-color="#fff" stop-opacity=".55"/><stop offset=".48" stop-color="#fff" stop-opacity=".96"/><stop offset="1" stop-color="#fff" stop-opacity="1"/></linearGradient>
  <filter id="uiBlur" x="-25%" y="-25%" width="150%" height="150%"><feGaussianBlur stdDeviation="12.5"/></filter>
  <filter id="spark" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="1.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <clipPath id="leftUi"><rect x="8" y="34" width="174" height="220" rx="22"/></clipPath>
  <clipPath id="rightUi"><rect x="718" y="34" width="174" height="220" rx="22"/></clipPath>
  <mask id="centerMask" maskUnits="userSpaceOnUse" x="210" y="0" width="480" height="132" style="mask-type:alpha"><ellipse cx="450" cy="47" rx="224" ry="80" fill="url(#centerMaskFade)"/></mask>
  <mask id="footerMask" maskUnits="userSpaceOnUse" x="0" y="244" width="900" height="119" style="mask-type:alpha"><rect x="0" y="244" width="900" height="119" fill="url(#footerMaskFade)"/></mask>
</defs>
<rect width="900" height="363" fill="#020705"/>
<image id="art" href="{REFERENCE_DATA_URI}" x="0" y="0" width="900" height="363" preserveAspectRatio="xMidYMid slice"/>
<!-- Dynamic value zones are repainted from a blurred copy of the SAME artwork.
     Center/footer masks are feathered so there are no rectangular patch edges. -->
<use href="#art" filter="url(#uiBlur)" clip-path="url(#leftUi)"/>
<use href="#art" filter="url(#uiBlur)" clip-path="url(#rightUi)"/>
<use href="#art" filter="url(#uiBlur)" mask="url(#centerMask)"/>
<use href="#art" filter="url(#uiBlur)" mask="url(#footerMask)"/>
<ellipse cx="150" cy="190" rx="255" ry="205" fill="url(#g)" opacity="{green:.3f}"/>
<ellipse cx="750" cy="190" rx="255" ry="205" fill="url(#r)" opacity="{red:.3f}"/>
<rect x="0" y="0" width="320" height="363" fill="url(#fadeL)"/>
<rect x="580" y="0" width="320" height="363" fill="url(#fadeR)"/>
<ellipse cx="450" cy="45" rx="205" ry="66" fill="url(#centerVeil)"/>
<rect x="0" y="260" width="900" height="103" fill="url(#footerVeil)"/>
<g transform="translate({impact_x} 191)" filter="url(#spark)" opacity=".34"><circle r="2.1" fill="#fff5c4"/><circle r="7.4" fill="none" stroke="#ffc65f" stroke-opacity=".30"/></g>
</svg>'''
    (FRAME_DIR / f"frame-{index:03d}.svg").write_text(svg, encoding="utf-8")

print(f"Premium Portfolio Impact reference: {REFERENCE.stat().st_size} bytes")
print("Generated 201 seamless full-bleed Bulls frames with feathered dynamic zones")
