#!/usr/bin/env python3
"""Generate web/app/black-luxe.css — the "Black Luxe" app skin.

Presentation only. The skin is a pure colour transform of the existing CSS:
  * every rule in the base stylesheets that sets a dark green / brown tinted
    colour gets a mirrored rule (same selector, same property) with that colour
    turned into neutral deep black;
  * bright accents (green/red/gold/blue) are made a bit more vivid;
  * all Suriname Heritage rules are mirrored for Black Luxe with the same
    transform, so the gold-on-dark structure stays, without the green haze.

Selectors, sizes, layout and every non-colour declaration are untouched. Base
rules are scoped with :where(...) so their specificity is identical to the
original rule; the generated file is imported last, so it wins on order only.

Run from the repo root:  python3 tools/generate_black_luxe_skin.py
"""
from __future__ import annotations

import colorsys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "web" / "app"
OUT = APP / "black-luxe.css"
MANUAL = ROOT / "tools" / "black_luxe_overrides.css"
SKIN = 'html[data-app-skin="black-luxe"]'
HERITAGE = 'html:is([data-app-skin="suriname-heritage"],[data-app-skin="black-luxe"])'
SKIP_FILES = {"black-luxe.css", "ultra-rivalry.css", "suriname-heritage.css"}

COLOR_PROPS = re.compile(r"^(--.*|background.*|border.*|box-shadow|outline.*|color|fill|stroke|text-shadow|caret-color|accent-color|column-rule.*|text-decoration.*)$")

# ---------------------------------------------------------------- colours

def _clamp(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def transform_rgb(r: float, g: float, b: float, a: float, prop: str) -> tuple[float, float, float, float]:
    mx, mn = max(r, g, b), min(r, g, b)
    sat = (mx - mn) / (mx + 1e-6)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    h = colorsys.rgb_to_hsv(r, g, b)[0] * 360
    is_gold = 30 <= h <= 58 and sat > 0.35
    textish = prop in ("color", "caret-color")

    # 1. dark tinted surfaces -> neutral deep black (keeps relative lightness)
    thr = 0.42 - 0.16 * sat
    if not textish and mx < thr:
        L = lum * 0.55
        return (L, L, _clamp(L * 1.04), a)
    # 2. faint colour washes (low alpha, not bright) -> neutral, except gold
    if not textish and a < 0.35 and mx < 0.62 and not is_gold:
        L = lum * 0.6
        return (L, L, _clamp(L * 1.04), a)
    # 3. accents -> more vivid
    if sat > 0.25:
        k = 1.25
        nr, ng, nb = (_clamp((lum + (c - lum) * k) * 1.06) for c in (r, g, b))
        return (nr, ng, nb, a)
    return (r, g, b, a)


HEX = re.compile(r"#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b")
RGB = re.compile(r"rgba?\(\s*([^)]*)\)", re.I)


def _fmt(r: float, g: float, b: float, a: float) -> str:
    R, G, B = (round(_clamp(c) * 255) for c in (r, g, b))
    if a >= 0.999:
        return f"#{R:02x}{G:02x}{B:02x}"
    return f"rgba({R},{G},{B},{round(a, 3):g})"


def _same_or(original: str, rgba: tuple, prop: str) -> str:
    new = transform_rgb(*rgba, prop)
    if all(abs(x - y) < 0.5 / 255 for x, y in zip(new, rgba)):
        return original
    return _fmt(*new)


def _hex(m: re.Match, prop: str) -> str:
    s = m.group(1)
    if len(s) in (3, 4):
        s = "".join(c * 2 for c in s)
    r, g, b = (int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))
    a = int(s[6:8], 16) / 255 if len(s) == 8 else 1.0
    return _same_or(m.group(0), (r, g, b, a), prop)


def _num(tok: str, scale: float) -> float | None:
    tok = tok.strip()
    try:
        if tok.endswith("%"):
            return float(tok[:-1]) / 100
        return float(tok) / scale
    except ValueError:
        return None


def _rgb(m: re.Match, prop: str) -> str:
    body = m.group(1)
    if "var(" in body or "calc(" in body:
        return m.group(0)
    alpha = 1.0
    if "/" in body:
        body, al = body.split("/", 1)
        av = _num(al, 1)
        if av is None:
            return m.group(0)
        alpha = av
    parts = [p for p in re.split(r"[\s,]+", body.strip()) if p]
    if len(parts) == 4:
        av = _num(parts[3], 1)
        if av is None:
            return m.group(0)
        alpha = av
        parts = parts[:3]
    if len(parts) != 3:
        return m.group(0)
    vals = [_num(p, 255) for p in parts]
    if any(v is None for v in vals):
        return m.group(0)
    return _same_or(m.group(0), (vals[0], vals[1], vals[2], alpha), prop)


def transform_value(prop: str, value: str) -> str:
    # never touch urls (images, the bull/bear media)
    pieces = re.split(r"(url\([^)]*\))", value)
    out = []
    for p in pieces:
        if p.startswith("url("):
            out.append(p)
            continue
        p = HEX.sub(lambda m: _hex(m, prop), p)
        p = RGB.sub(lambda m: _rgb(m, prop), p)
        out.append(p)
    return "".join(out)

# ---------------------------------------------------------------- tiny css parser

def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def parse_blocks(css: str):
    """Yield (prelude, body, is_block) items at one nesting level."""
    i, n = 0, len(css)
    while i < n:
        j = i
        depth_paren = 0
        quote = None
        while j < n:
            c = css[j]
            if quote:
                if c == "\\":
                    j += 2
                    continue
                if c == quote:
                    quote = None
            elif c in "\"'":
                quote = c
            elif c == "(":
                depth_paren += 1
            elif c == ")":
                depth_paren -= 1
            elif depth_paren == 0 and c in "{;":
                break
            j += 1
        if j >= n:
            break
        prelude = css[i:j].strip()
        if css[j] == ";":
            i = j + 1
            continue
        # find matching brace
        depth, k, quote = 1, j + 1, None
        while k < n and depth:
            c = css[k]
            if quote:
                if c == "\\":
                    k += 2
                    continue
                if c == quote:
                    quote = None
            elif c in "\"'":
                quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            k += 1
        yield prelude, css[j + 1:k - 1]
        i = k


def split_decls(body: str):
    decls, cur, depth, quote = [], "", 0, None
    for c in body:
        if quote:
            cur += c
            if c == quote:
                quote = None
            continue
        if c in "\"'":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == ";" and depth == 0:
            decls.append(cur)
            cur = ""
        else:
            cur += c
    if cur.strip():
        decls.append(cur)
    out = []
    for d in decls:
        if ":" not in d:
            continue
        prop, val = d.split(":", 1)
        out.append((prop.strip(), val.strip()))
    return out


def split_selectors(sel: str):
    parts, cur, depth = [], "", 0
    for c in sel:
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        if c == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += c
    if cur.strip():
        parts.append(cur.strip())
    return parts


SCOPE_PREFIX = f":where({SKIN}) "
KEEP_ORDER = True  # mirror unchanged colour declarations too, so later rules keep winning


def scope_base(sel: str) -> str | None:
    if "data-app-skin" in sel:
        return None  # belongs to another skin
    if SCOPE_PREFIX.startswith(":global"):
        return f"{SCOPE_PREFIX}{sel}"
    if sel.startswith(":root"):
        return ':root:where([data-app-skin="black-luxe"])' + sel[5:]
    if re.match(r"^html(?![\w-])", sel):
        return 'html:where([data-app-skin="black-luxe"])' + sel[4:]
    return f"{SCOPE_PREFIX}{sel}"


def emit(css: str, mode: str, indent: str = "") -> list[str]:
    lines: list[str] = []
    for prelude, body in parse_blocks(css):
        low = prelude.lower()
        if low.startswith("@media") or low.startswith("@supports") or low.startswith("@container") or low.startswith("@layer"):
            inner = emit(body, mode, indent + "  ")
            if inner:
                lines.append(f"{indent}{prelude}{{")
                lines += inner
                lines.append(f"{indent}}}")
            continue
        if low.startswith("@"):
            continue  # keyframes, font-face, property...
        sels = split_selectors(prelude)
        if mode == "heritage":
            if not all(HERITAGE in s for s in sels):
                continue
            # Heritage rules already apply to Black Luxe for everything except colour
            # (shared selector in suriname-heritage.css); mirror only the colours here.
            new_sels = [s.replace(HERITAGE, SKIN) for s in sels]
            decls = []
            for prop, val in split_decls(body):
                if COLOR_PROPS.match(prop.lower()):
                    decls.append(f"{prop}:{transform_value(prop.lower(), val)}")
        else:
            new_sels = [x for x in (scope_base(s) for s in sels) if x]
            if not new_sels:
                continue
            decls, changed = [], False
            for prop, val in split_decls(body):
                pl = prop.lower()
                if not COLOR_PROPS.match(pl):
                    continue
                nv = transform_value(pl, val)
                changed |= nv != val
                decls.append(f"{prop}:{nv}")
            if not changed and not KEEP_ORDER:
                decls = []
        if decls:
            lines.append(f"{indent}{','.join(new_sels)}{{{';'.join(decls)}}}")
    return lines


def main() -> None:
    layout = (APP / "layout.tsx").read_text()
    order = re.findall(r'import "\./([\w.-]+\.css)";', layout)
    out = [
        "/* GENERATED by tools/generate_black_luxe_skin.py — do not edit by hand.",
        "   Black Luxe: presentation-only skin. Colours only; no layout, data or trading rules. */",
    ]
    global SCOPE_PREFIX, KEEP_ORDER
    for name in order:
        if name == "suriname-heritage.css":
            out.append("/* from suriname-heritage.css (mirrored, at its own cascade position) */")
            out += emit(strip_comments((APP / name).read_text()), "heritage")
            continue
        if name in SKIP_FILES:
            continue
        lines = emit(strip_comments((APP / name).read_text()), "base")
        if lines:
            out.append(f"/* from {name} */")
            out += lines
    # <style>{`...`}</style> blocks render in <body>, after every stylesheet: mirror them with
    # a real (non-:where) skin prefix so they still win, and only where a colour changes.
    SCOPE_PREFIX, KEEP_ORDER = f"{SKIN} ", False
    for tsx in sorted((ROOT / "web" / "components").glob("*.tsx")):
        for block in re.findall(r"<style>\{`(.*?)`\}</style>", tsx.read_text(), flags=re.S):
            css = re.sub(r"\$\{[^}]*\}", "0", block)
            lines = emit(strip_comments(css), "base")
            if lines:
                out.append(f"/* from {tsx.name} (inline style) */")
                out += lines
    out.append("/* hand-written finishing touches */")
    out.append(MANUAL.read_text().strip())
    OUT.write_text("\n".join(out) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")
    # CSS modules: hashed class names, so the mirrored rules live inside each module file
    KEEP_ORDER = True
    SCOPE_PREFIX = ':global(:where(html[data-app-skin="black-luxe"])) '
    for mod in sorted((ROOT / "web" / "components").glob("*.module.css")):
        if mod.name.startswith("portfolio-impact"):
            continue  # bull/bear video banner stays exactly as it is
        text = mod.read_text()
        text = re.sub(r"\n?/\* BLACK-LUXE:BEGIN.*?BLACK-LUXE:END \*/\n?", "\n", text, flags=re.S).rstrip() + "\n"
        lines = emit(strip_comments(text), "base")
        if lines:
            text += "\n/* BLACK-LUXE:BEGIN — generated by tools/generate_black_luxe_skin.py, colours only */\n" + "\n".join(lines) + "\n/* BLACK-LUXE:END */\n"
        mod.write_text(text)
        print(f"updated {mod.relative_to(ROOT)} (+{len(lines)} rules)")


if __name__ == "__main__":
    main()
