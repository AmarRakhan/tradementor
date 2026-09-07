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

# Fixed-camera composition. The original artwork/world never translates.
# Only duplicated, masked bull foregrounds react to market pressure.
W, H = 720, 303

for index in range(201):
    long_share = index / 2.0
    bias = (long_share - 50.0) / 50.0

    # Pressure movement stays deliberately small: this must read as two heavy
    # animals pushing each other, never as a photograph sliding sideways.
    left_dx = bias * 6.0
    right_dx = bias * 3.0
    left_rot = -bias * 0.55
    right_rot = -bias * 0.20
    left_scale = 1.0 + max(0.0, bias) * 0.008
    right_scale = 1.0 + max(0.0, -bias) * 0.008
    green = 0.055 + max(0.0, bias) * 0.13
    red = 0.055 + max(0.0, -bias) * 0.13
    debris = 0.18 + abs(bias) * 0.32
    impact_x = 360 + round(bias * 4)

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="606" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">
<defs>
  <filter id="bullMaskBlur" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="3.2"/></filter>
  <filter id="uiBlur" x="-25%" y="-25%" width="150%" height="150%"><feGaussianBlur stdDeviation="9.5"/></filter>
  <filter id="maskFeather" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="7"/></filter>
  <filter id="dustBlur" x="-200%" y="-200%" width="400%" height="400%"><feGaussianBlur stdDeviation="2.1"/></filter>
  <filter id="spark" x="-150%" y="-150%" width="400%" height="400%"><feGaussianBlur stdDeviation="1.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <radialGradient id="g"><stop stop-color="#20f29a" stop-opacity=".64"/><stop offset="1" stop-color="#20f29a" stop-opacity="0"/></radialGradient>
  <radialGradient id="r"><stop stop-color="#ff405f" stop-opacity=".64"/><stop offset="1" stop-color="#ff405f" stop-opacity="0"/></radialGradient>

  <!-- Feathered cleanup masks: these never paint grey/black rectangles. They
       only blur the existing artwork in the old static-value zones so the live
       DOM text can sit directly on the original green/red scene. -->
  <mask id="leftUi" maskUnits="userSpaceOnUse" x="-20" y="-20" width="175" height="250" style="mask-type:alpha">
    <rect x="8" y="17" width="118" height="188" rx="18" fill="white" filter="url(#maskFeather)"/>
  </mask>
  <mask id="rightUi" maskUnits="userSpaceOnUse" x="565" y="-20" width="175" height="250" style="mask-type:alpha">
    <rect x="594" y="17" width="119" height="188" rx="18" fill="white" filter="url(#maskFeather)"/>
  </mask>
  <mask id="centerUi" maskUnits="userSpaceOnUse" x="210" y="-35" width="300" height="145" style="mask-type:alpha">
    <ellipse cx="360" cy="41" rx="115" ry="52" fill="white" filter="url(#maskFeather)"/>
  </mask>
  <mask id="statusUi" maskUnits="userSpaceOnUse" x="170" y="190" width="380" height="72" style="mask-type:alpha">
    <rect x="205" y="220" width="310" height="25" rx="12" fill="white" filter="url(#maskFeather)"/>
  </mask>
  <mask id="captionUi" maskUnits="userSpaceOnUse" x="0" y="262" width="720" height="55" style="mask-type:alpha">
    <rect x="40" y="282" width="640" height="20" rx="9" fill="white" filter="url(#maskFeather)"/>
  </mask>

  <mask id="leftBullMask" maskUnits="userSpaceOnUse" x="75" y="20" width="300" height="220" style="mask-type:alpha">
    <polygon points="105,62 142,45 190,32 245,42 305,73 347,112 344,155 320,190 278,220 215,216 160,192 123,160 110,110" fill="white" filter="url(#bullMaskBlur)"/>
  </mask>
  <mask id="rightBullMask" maskUnits="userSpaceOnUse" x="345" y="20" width="300" height="220" style="mask-type:alpha">
    <polygon points="352,78 395,54 445,37 506,40 565,61 620,94 640,135 620,173 585,205 527,220 470,215 414,190 382,160 365,118" fill="white" filter="url(#bullMaskBlur)"/>
  </mask>
</defs>

<!-- CAMERA / WORLD: absolutely fixed -->
<rect width="720" height="303" fill="#020403"/>
<image id="art" href="{REFERENCE_DATA_URI}" x="0" y="0" width="720" height="303" preserveAspectRatio="xMidYMid slice"/>

<!-- Remove old baked-in values by blurring the SAME pixels. There are no solid
     center/left/right HUD covers anywhere in these frames. -->
<use href="#art" filter="url(#uiBlur)" mask="url(#leftUi)"/>
<use href="#art" filter="url(#uiBlur)" mask="url(#rightUi)"/>
<use href="#art" filter="url(#uiBlur)" mask="url(#centerUi)"/>
<use href="#art" filter="url(#uiBlur)" mask="url(#statusUi)"/>
<use href="#art" filter="url(#uiBlur)" mask="url(#captionUi)"/>

<!-- Quiet the source bull silhouettes just enough for the sharp moving duplicate
     to read as foreground motion without creating a ghost or moving the world. -->
<rect width="720" height="303" fill="#020403" opacity=".13" mask="url(#leftBullMask)"/>
<rect width="720" height="303" fill="#020403" opacity=".13" mask="url(#rightBullMask)"/>

<!-- FOREGROUND BULLS ONLY -->
<g mask="url(#leftBullMask)" transform="translate({left_dx:.2f} 0) rotate({left_rot:.3f} 230 137) scale({left_scale:.5f})">
  <use href="#art"/>
</g>
<g mask="url(#rightBullMask)" transform="translate({right_dx:.2f} 0) rotate({right_rot:.3f} 495 137) scale({right_scale:.5f})">
  <use href="#art"/>
</g>

<!-- Pressure light stays anchored to the fixed world. -->
<ellipse cx="145" cy="168" rx="215" ry="174" fill="url(#g)" opacity="{green:.3f}"/>
<ellipse cx="575" cy="168" rx="215" ry="174" fill="url(#r)" opacity="{red:.3f}"/>

<!-- Contact spark, dust and stones: independent foreground detail. -->
<g transform="translate({impact_x} 146)" filter="url(#spark)"><circle r="2.1" fill="#fff7cf" opacity=".72"><animate attributeName="opacity" values=".30;.90;.38" dur="1.7s" repeatCount="indefinite"/></circle><circle r="7.5" fill="none" stroke="#ffc65f" stroke-opacity=".32"/></g>
<g opacity="{debris:.3f}">
  <circle cx="355" cy="220" r="2.2" fill="#c89452"><animateTransform attributeName="transform" type="translate" values="0 0;11 -10;17 -5" dur="3.2s" begin="-.7s" repeatCount="indefinite"/><animate attributeName="opacity" values="0;0;.95;0;0" keyTimes="0;.52;.66;.82;1" dur="3.2s" begin="-.7s" repeatCount="indefinite"/></circle>
  <circle cx="366" cy="224" r="1.6" fill="#8f6a3b"><animateTransform attributeName="transform" type="translate" values="0 0;8 -14;14 -7" dur="4.1s" begin="-2.1s" repeatCount="indefinite"/><animate attributeName="opacity" values="0;0;.82;0;0" keyTimes="0;.60;.69;.82;1" dur="4.1s" begin="-2.1s" repeatCount="indefinite"/></circle>
  <path d="M348 226 l5 -1 l-2 4 z" fill="#765333"><animateTransform attributeName="transform" type="translate" values="0 0;13 -7;20 1" dur="5s" begin="-3.3s" repeatCount="indefinite"/><animate attributeName="opacity" values="0;0;.72;0;0" keyTimes="0;.64;.72;.84;1" dur="5s" begin="-3.3s" repeatCount="indefinite"/></path>
  <ellipse cx="360" cy="221" rx="14" ry="5" fill="#c98947" opacity=".16" filter="url(#dustBlur)"><animate attributeName="opacity" values=".04;.22;.07" dur="2.8s" repeatCount="indefinite"/><animateTransform attributeName="transform" type="scale" values=".75 1;1.22 1.18;.82 1" dur="2.8s" repeatCount="indefinite"/></ellipse>
</g>
</svg>'''
    (FRAME_DIR / f"frame-{index:03d}.svg").write_text(svg, encoding="utf-8")

print(f"Premium Portfolio Impact reference: {REFERENCE.stat().st_size} bytes")
print("Generated 201 fixed-camera Bulls frames with transparent, feathered HUD cleanup")
