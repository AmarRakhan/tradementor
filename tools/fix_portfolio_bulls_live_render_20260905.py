from pathlib import Path

root = Path(__file__).resolve().parents[1]
css = root / "web/components/portfolio-impact-battle.module.css"
text = css.read_text()
text = text.replace("background-image:url('/portfolio-impact-bulls.webp')", "background-image:url('/portfolio-impact-bulls.svg?v=2')")
text = text.replace("animation:sparkSpin 8s linear infinite", "animation:none")
text = text.replace("@keyframes sparkSpin{to{transform:rotate(360deg)}}", "")
css.write_text(text)
print("Portfolio Impact live render fixed: verified SVG asset active; endless spark rotation removed")
