from pathlib import Path

root = Path(__file__).resolve().parents[1]
css = root / "web/components/portfolio-impact-battle.module.css"
text = css.read_text()

# Use the verified raster artwork directly. The SVG wrapper caused the broken grey/pixel render in live Android builds.
text = text.replace("background-image:url('/portfolio-impact-bulls.svg?v=2')", "background-image:url('/portfolio-impact-bulls.webp?v=4')")
text = text.replace("background-image:url('/portfolio-impact-bulls.webp')", "background-image:url('/portfolio-impact-bulls.webp?v=4')")

# Full-body cinematic composition: zoom out, expose the legs/rocky base and reduce panel dominance.
text = text.replace("inset:17% -1% 18%;background-image:url('/portfolio-impact-bulls.webp?v=4');background-position:center 58%;background-repeat:no-repeat;background-size:100% auto", "inset:14% 1% 17%;background-image:url('/portfolio-impact-bulls.webp?v=4');background-position:center 61%;background-repeat:no-repeat;background-size:94% auto")
text = text.replace("top:15px;width:22.5%;min-width:104px;max-width:180px;padding:10px 11px 9px", "top:15px;width:20.5%;min-width:100px;max-width:166px;padding:9px 10px 8px")
text = text.replace("rgba(1,27,17,.50),rgba(2,15,10,.28)", "rgba(1,27,17,.42),rgba(2,15,10,.22)")
text = text.replace("rgba(41,4,11,.52),rgba(18,3,6,.29)", "rgba(41,4,11,.44),rgba(18,3,6,.23)")

# Refine the center clash: smaller, warm and compact; no radial spokes / spinner effect.
text = text.replace("top:49%;width:86px;height:86px", "top:49%;width:62px;height:62px")
text = text.replace("inset:13px;border-radius:50%;background:radial-gradient(circle,#fffde7 0 8%,#fff0ac 15%,#ffcf59 25%,rgba(249,149,34,.88) 38%,transparent 70%);box-shadow:0 0 22px rgba(255,196,75,.8),0 0 45px rgba(255,113,37,.35)", "inset:12px;border-radius:50%;background:radial-gradient(circle,#fffde7 0 9%,#fff0ac 17%,#ffcf59 28%,rgba(249,149,34,.76) 40%,transparent 69%);box-shadow:0 0 16px rgba(255,196,75,.76),0 0 31px rgba(255,113,37,.26)")
text = text.replace(".impact:after{content:\"\";position:absolute;inset:-18px;background:repeating-conic-gradient(from 8deg,transparent 0 10deg,rgba(255,225,145,.92) 11deg 12deg,transparent 13deg 27deg);mask:radial-gradient(circle,transparent 0 31%,#000 34% 62%,transparent 65%);-webkit-mask:radial-gradient(circle,transparent 0 31%,#000 34% 62%,transparent 65%);opacity:calc(.42 + var(--battle-intensity) * .35);filter:drop-shadow(0 0 5px rgba(255,179,63,.8));animation:none}", ".impact:after{content:\"\";position:absolute;inset:-7px;border-radius:50%;background:radial-gradient(circle,transparent 0 42%,rgba(255,214,115,.22) 48%,transparent 70%);filter:blur(2px);opacity:calc(.32 + var(--battle-intensity) * .28)}")
text = text.replace("@keyframes sparkSpin{to{transform:rotate(360deg)}}", "")
text = text.replace("animation:sparkSpin 8s linear infinite", "animation:none")

# Mobile composition: further zoom out and make the hero calmer/more reference-like.
text = text.replace(".card{aspect-ratio:1.55/1", ".card{aspect-ratio:1.62/1")
text = text.replace("top:10px;width:23.5%;min-width:0;padding:7px 7px 6px", "top:10px;width:21%;min-width:0;padding:6px 6px 6px")
text = text.replace("inset:18% -1% 19%;background-position:center 59%;background-size:100% auto", "inset:15% 1% 18%;background-position:center 62%;background-size:93% auto")
text = text.replace("top:49%;width:60px;height:60px", "top:49%;width:44px;height:44px")
text = text.replace(".card{aspect-ratio:1.50/1", ".card{aspect-ratio:1.57/1")
text = text.replace("width:24.5%;padding-inline:6px", "width:22%;padding-inline:5px")
text = text.replace("inset:19% -1% 19%;background-size:100% auto", "inset:16% 1% 18%;background-size:92% auto")

css.write_text(text)
print("Portfolio Impact parity repair applied: verified WebP, full-body crop, slimmer panels, compact non-spinner clash")
