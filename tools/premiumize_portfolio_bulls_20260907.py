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

# The approved source artwork is 720x303. Keep the world/camera locked to that
# exact composition. Pressure is shown by moving only feathered bull foreground
# layers plus tiny dust/stone particles. The mountains, ground and lighting never
# pan or slide with LONG/SHORT pressure.
W, H = 720, 303

for index in range(201):
    long_share = index / 2.0
    bias = (long_share - 50.0) / 50.0
    strength = abs(bias)

    # Advancing bull moves slightly more than the retreating bull. At 40/60 or
    # 60/40 this is only about 1 px; at an extreme it is still just 6 px.
    if bias >= 0:
        left_dx = 6.0 * bias
        right_dx = 3.0 * bias
    else:
        left_dx = 3.0 * bias
        right_dx = 6.0 * bias

    left_scale = 1.0 + max(0.0, bias) * 0.008
    right_scale = 1.0 + max(0.0, -bias) * 0.008
    left_tilt = -0.55 * max(0.0, bias) + 0.20 * max(0.0, -bias)
    right_tilt = 0.55 * max(0.0, -bias) - 0.20 * max(0.0, bias)
    impact_x = 360 + round(bias * 14)
    particle_dir = 1 if bias >= 0 else -1
    particle_opacity = 0.18 + strength * 0.62
    green_glow = 0.06 + max(0.0, bias) * 0.18
    red_glow = 0.06 + max(0.0, -bias) * 0.18

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="606" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">
<defs>
  <filter id="bullMaskBlur" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="3.2"/></filter>
  <filter id="dustBlur" x="-200%" y="-200%" width="400%" height="400%"><feGaussianBlur stdDeviation="2.1"/></filter>
  <filter id="spark" x="-150%" y="-150%" width="400%" height="400%"><feGaussianBlur stdDeviation="1.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <radialGradient id="centerHide"><stop offset="0" stop-color="#030403" stop-opacity=".96"/><stop offset=".48" stop-color="#030403" stop-opacity=".78"/><stop offset=".72" stop-color="#030403" stop-opacity=".34"/><stop offset="1" stop-color="#030403" stop-opacity="0"/></radialGradient>
  <linearGradient id="footerHide" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#020403" stop-opacity="0"/><stop offset=".38" stop-color="#020403" stop-opacity=".36"/><stop offset="1" stop-color="#020403" stop-opacity=".82"/></linearGradient>
  <radialGradient id="g"><stop stop-color="#20f29a" stop-opacity=".64"/><stop offset="1" stop-color="#20f29a" stop-opacity="0"/></radialGradient>
  <radialGradient id="r"><stop stop-color="#ff405f" stop-opacity=".64"/><stop offset="1" stop-color="#ff405f" stop-opacity="0"/></radialGradient>
  <mask id="leftBullMask" maskUnits="userSpaceOnUse" x="75" y="20" width="300" height="220" style="mask-type:alpha">
    <polygon points="105,62 142,45 190,32 245,42 305,73 347,112 344,155 320,190 278,220 215,216 160,192 123,160 110,110" fill="white" filter="url(#bullMaskBlur)"/>
  </mask>
  <mask id="rightBullMask" maskUnits="userSpaceOnUse" x="345" y="20" width="300" height="220" style="mask-type:alpha">
    <polygon points="352,78 395,54 445,37 506,40 565,61 620,94 640,135 620,173 585,205 527,220 470,215 414,190 382,160 365,118" fill="white" filter="url(#bullMaskBlur)"/>
  </mask>
</defs>

<!-- CAMERA / WORLD: never moves -->
<rect width="720" height="303" fill="#020403"/>
<image id="art" href="{REFERENCE_DATA_URI}" x="0" y="0" width="720" height="303" preserveAspectRatio="xMidYMid meet"/>

<!-- Hide only the old source values. These are feathered/tinted into the scene,
     never rectangular grey repaint blocks. The original coloured side glass stays. -->
<ellipse cx="360" cy="40" rx="122" ry="56" fill="url(#centerHide)"/>
<rect x="0" y="220" width="720" height="83" fill="url(#footerHide)"/>
<rect x="7" y="17" width="118" height="188" rx="18" fill="#001b10" opacity=".53"/>
<rect x="594" y="17" width="119" height="188" rx="18" fill="#26030a" opacity=".53"/>

<!-- Mute the original sharp bull silhouettes very slightly. The sharp duplicated
     foreground layers below then carry the visible pressure movement without the
     background, mountains or ground shifting with them. -->
<rect width="720" height="303" fill="#020403" opacity=".19" mask="url(#leftBullMask)"/>
<rect width="720" height="303" fill="#020403" opacity=".19" mask="url(#rightBullMask)"/>

<!-- FOREGROUND BULLS ONLY -->
<g mask="url(#leftBullMask)" transform="translate({left_dx:.2f} 0) rotate({left_tilt:.3f} 230 137) translate({230*(1-left_scale):.3f} {137*(1-left_scale):.3f}) scale({left_scale:.5f})">
  <use href="#art"/>
</g>
<g mask="url(#rightBullMask)" transform="translate({right_dx:.2f} 0) rotate({right_tilt:.3f} 495 137) translate({495*(1-right_scale):.3f} {137*(1-right_scale):.3f}) scale({right_scale:.5f})">
  <use href="#art"/>
</g>

<!-- Pressure lighting stays anchored to the fixed world. -->
<ellipse cx="145" cy="168" rx="215" ry="174" fill="url(#g)" opacity="{green_glow:.3f}"/>
<ellipse cx="575" cy="168" rx="215" ry="174" fill="url(#r)" opacity="{red_glow:.3f}"/>

<!-- Contact spark and occasional stones/dust. These move independently of the
     camera so the scene feels like two animals physically pushing, not a sliding photo. -->
<g transform="translate({impact_x} 146)" filter="url(#spark)"><circle r="2.1" fill="#fff7cf" opacity=".72"><animate attributeName="opacity" values=".30;.90;.38" dur="1.7s" repeatCount="indefinite"/></circle><circle r="7.5" fill="none" stroke="#ffc65f" stroke-opacity=".32"/></g>
<g opacity="{particle_opacity:.3f}">
  <circle cx="355" cy="220" r="2.2" fill="#c89452"><animateTransform attributeName="transform" type="translate" values="0 0;{particle_dir*11} -10;{particle_dir*17} -5" dur="3.2s" begin="-.7s" repeatCount="indefinite"/><animate attributeName="opacity" values="0;0;.95;0;0" keyTimes="0;.52;.66;.82;1" dur="3.2s" begin="-.7s" repeatCount="indefinite"/></circle>
  <circle cx="366" cy="224" r="1.6" fill="#8f6a3b"><animateTransform attributeName="transform" type="translate" values="0 0;{particle_dir*8} -14;{particle_dir*14} -7" dur="4.1s" begin="-2.1s" repeatCount="indefinite"/><animate attributeName="opacity" values="0;0;.82;0;0" keyTimes="0;.60;.69;.82;1" dur="4.1s" begin="-2.1s" repeatCount="indefinite"/></circle>
  <path d="M348 226 l5 -1 l-2 4 z" fill="#765333"><animateTransform attributeName="transform" type="translate" values="0 0;{particle_dir*13} -7;{particle_dir*20} 1" dur="5s" begin="-3.3s" repeatCount="indefinite"/><animate attributeName="opacity" values="0;0;.72;0;0" keyTimes="0;.64;.72;.84;1" dur="5s" begin="-3.3s" repeatCount="indefinite"/></path>
  <ellipse cx="360" cy="221" rx="14" ry="5" fill="#c98947" opacity=".16" filter="url(#dustBlur)"><animate attributeName="opacity" values=".04;.22;.07" dur="2.8s" repeatCount="indefinite"/><animateTransform attributeName="transform" type="scale" values=".75 1;1.22 1.18;.82 1" dur="2.8s" repeatCount="indefinite"/></ellipse>
</g>
</svg>'''
    (FRAME_DIR / f"frame-{index:03d}.svg").write_text(svg, encoding="utf-8")

print(f"Premium Portfolio Impact reference: {REFERENCE.stat().st_size} bytes")
print("Generated 201 fixed-camera Bulls frames with foreground-only bull motion and particles")
