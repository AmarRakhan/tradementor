from __future__ import annotations

import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
ART = WEB / "public" / "portfolio-impact-bulls.webp"
OUT = WEB / "public" / "portfolio-impact-states"

if not ART.exists():
    raise SystemExit("Missing portfolio-impact-bulls.webp")

encoded = base64.b64encode(ART.read_bytes()).decode("ascii")
OUT.mkdir(parents=True, exist_ok=True)
for old in OUT.glob("state-*.svg"):
    old.unlink()

rocks = '''
<path d="M0 270 L48 254 L104 267 L164 250 L222 268 L286 251 L351 270 L419 251 L486 268 L551 250 L617 267 L681 252 L720 264 L720 303 L0 303 Z" fill="#111813" opacity=".74"/>
<path d="M0 286 L64 270 L116 281 L180 264 L244 284 L308 267 L372 283 L440 265 L506 282 L570 266 L636 282 L700 268 L720 274" fill="none" stroke="#596058" stroke-width="2" opacity=".31"/>
<path d="M34 278 l18 -8 17 9 -15 10z M132 272 l19 -9 21 11 -18 11z M242 278 l20 -10 18 11 -15 10z M354 274 l20 -10 23 12 -20 11z M474 278 l18 -9 22 11 -18 10z M594 274 l20 -9 19 11 -16 10z" fill="#343d35" opacity=".42"/>
'''.strip()

for index in range(17):
    bias = (index - 8) / 8.0
    dx = round(82 * bias)
    strength = abs(bias)
    green_alpha = 0.18 + (0.18 * max(0.0, bias)) - (0.05 * max(0.0, -bias))
    red_alpha = 0.18 + (0.18 * max(0.0, -bias)) - (0.05 * max(0.0, bias))
    shade_alpha = 0.07 + 0.19 * strength
    impact_x = round(360 + dx)
    if bias > 0:
        shade = f'<rect x="405" width="315" height="303" fill="url(#shadeRight)" opacity="{shade_alpha:.3f}"/>'
    elif bias < 0:
        shade = f'<rect width="315" height="303" fill="url(#shadeLeft)" opacity="{shade_alpha:.3f}"/>'
    else:
        shade = ''
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="606" viewBox="0 0 720 303" preserveAspectRatio="xMidYMid slice">
<defs>
  <linearGradient id="bg" x1="0" x2="1"><stop stop-color="#00160d"/><stop offset=".47" stop-color="#07110c"/><stop offset=".53" stop-color="#110907"/><stop offset="1" stop-color="#1a0007"/></linearGradient>
  <radialGradient id="green"><stop stop-color="#29f19a" stop-opacity=".50"/><stop offset="1" stop-color="#29f19a" stop-opacity="0"/></radialGradient>
  <radialGradient id="red"><stop stop-color="#ff4968" stop-opacity=".50"/><stop offset="1" stop-color="#ff4968" stop-opacity="0"/></radialGradient>
  <linearGradient id="shadeRight" x1="0" x2="1"><stop stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".90"/></linearGradient>
  <linearGradient id="shadeLeft" x1="1" x2="0"><stop stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".90"/></linearGradient>
  <filter id="sparkGlow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>
<rect width="720" height="303" fill="url(#bg)"/>
<ellipse cx="128" cy="150" rx="250" ry="196" fill="url(#green)" opacity="{green_alpha:.3f}"/>
<ellipse cx="592" cy="150" rx="250" ry="196" fill="url(#red)" opacity="{red_alpha:.3f}"/>
<image x="{dx}" y="0" width="720" height="303" href="data:image/webp;base64,{encoded}"/>
{shade}
<g opacity=".22"><path d="M0 55 H720 M0 112 H720 M0 169 H720 M0 226 H720" stroke="#d7b65c" stroke-width=".45"/><path d="M90 0 V303 M180 0 V303 M270 0 V303 M360 0 V303 M450 0 V303 M540 0 V303 M630 0 V303" stroke="#d7b65c" stroke-width=".35"/></g>
{rocks}
<g transform="translate({impact_x} 150)" filter="url(#sparkGlow)" opacity=".94">
  <circle r="3.4" fill="#fff4bd"/><circle r="8.5" fill="none" stroke="#f8b84e" stroke-opacity=".60"/>
  <path d="M-3 -5 L-18 -25 M4 -4 L22 -23 M-5 2 L-26 11 M5 3 L27 15 M0 6 L3 29" stroke="#ffd36e" stroke-width="1.4" stroke-linecap="round"/>
</g>
<rect x=".5" y=".5" width="719" height="302" rx="22" fill="none" stroke="#d9ac4c" stroke-opacity=".24"/>
</svg>'''
    (OUT / f"state-{index:02d}.svg").write_text(svg, encoding="utf-8")

print("Generated 17 seam-free single-scene Bulls push states")
