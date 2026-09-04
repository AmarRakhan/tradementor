from pathlib import Path

root = Path(__file__).resolve().parents[1]

page = root / "web/app/page.tsx"
text = page.read_text()
old = '  let connected = Boolean(snapshot.data) && !snapshot.error;\n  let accountDataAvailable = connected;'
new = '  const hasTrustedSnapshot = Boolean(snapshot.data) && (snapshot.serverConfirmed || !snapshot.error);\n  let connected = hasTrustedSnapshot;\n  let accountDataAvailable = connected;'
assert old in text
text = text.replace(old, new, 1)
old = '  const statusText = snapshot.loading && !snapshot.data ? "Gegevens laden" : snapshot.error ? "Controle nodig" : readOnlyRecognized ? "Wallet herkend · alleen-lezen" : connected ? "Exchange verbonden" : "Niet gekoppeld";\n  const metricDetail = snapshot.error || (snapshot.loading ? (snapshot.source === "cache" ? "Laatste bekende waarde · actuele data wordt opgehaald" : "Exchange wordt vernieuwd") : snapshot.source === "cache" ? "Laatste bekende waarde · actuele data wordt opgehaald" : readOnlyRecognized ? "Trading en automatische orders staan uit" : connected ? "Actuele exchange-snapshot" : "Nog niet gekoppeld");'
new = '  const statusText = snapshot.loading && !snapshot.data ? "Gegevens laden" : snapshot.error && hasTrustedSnapshot ? "Laatste bevestigde gegevens" : snapshot.error ? "Controle nodig" : readOnlyRecognized ? "Wallet herkend · alleen-lezen" : connected ? "Exchange verbonden" : "Niet gekoppeld";\n  const metricDetail = snapshot.error && hasTrustedSnapshot ? "Laatste bevestigde exchange-snapshot · nieuwe controle loopt" : snapshot.error || (snapshot.loading ? (snapshot.source === "cache" ? "Laatste bekende waarde · actuele data wordt opgehaald" : "Exchange wordt vernieuwd") : snapshot.source === "cache" ? "Laatste bekende waarde · actuele data wordt opgehaald" : readOnlyRecognized ? "Trading en automatische orders staan uit" : connected ? "Actuele exchange-snapshot" : "Nog niet gekoppeld");'
assert old in text
text = text.replace(old, new, 1)
page.write_text(text)

trades = root / "web/components/aster-recent-trades.tsx"
text = trades.read_text()
old = '  const liveState = snapshot.error ? "Offline" : snapshot.loading ? "Reconnecting" : snapshot.updatedAt && Date.now() - snapshot.updatedAt < 90_000 ? "Live" : "Delayed";'
new = '  const hasTrustedTradeSnapshot = Boolean(snapshot.data) && snapshot.serverConfirmed;\n  const liveState = snapshot.error && !hasTrustedTradeSnapshot ? "Offline" : snapshot.loading ? "Reconnecting" : snapshot.error ? "Delayed" : snapshot.updatedAt && Date.now() - snapshot.updatedAt < 90_000 ? "Live" : "Delayed";'
assert old in text
text = text.replace(old, new, 1)
trades.write_text(text)

css = root / "web/components/aster-trade-center.module.css"
text = css.read_text()
old = '@media(max-width:700px){.header{padding:14px 12px 10px}.title h2{font-size:17px}.filters{padding:0 12px 12px}.filter{min-height:32px;padding-inline:10px}'
new = '@media(max-width:700px){.header{padding:14px 12px 10px}.title h2{font-size:17px}.filters{padding:0 12px 12px;scroll-padding-inline:12px;overscroll-behavior-x:none}.filters:before,.filters:after{content:"";flex:0 0 1px}.filter{min-height:32px;padding-inline:10px}'
assert old in text
text = text.replace(old, new, 1)
css.write_text(text)

# Targeted regression test
p = root / "web/tests/aster-live-snapshot-ui-repair.test.mjs"
p.write_text('''import test from "node:test";\nimport assert from "node:assert/strict";\nimport { readFile } from "node:fs/promises";\n\nconst page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");\nconst trades = await readFile(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");\nconst css = await readFile(new URL("../components/aster-trade-center.module.css", import.meta.url), "utf8");\n\ntest("trusted confirmed Aster values remain visible after a transient refresh failure", () => {\n  assert.match(page, /hasTrustedSnapshot = Boolean\\(snapshot\\.data\\) && \\(snapshot\\.serverConfirmed \\|\\| !snapshot\\.error\\)/);\n  assert.match(page, /snapshot\\.error && hasTrustedSnapshot \\? "Laatste bevestigde gegevens"/);\n  assert.match(page, /accountDataAvailable = connected/);\n});\n\ntest("Tradecentrum does not claim Offline while confirmed trade data is still present", () => {\n  assert.match(trades, /hasTrustedTradeSnapshot = Boolean\\(snapshot\\.data\\) && snapshot\\.serverConfirmed/);\n  assert.match(trades, /snapshot\\.error && !hasTrustedTradeSnapshot \\? "Offline"/);\n  assert.match(trades, /snapshot\\.error \\? "Delayed"/);\n});\n\ntest("mobile Tradecentrum filters keep edge padding while horizontally scrolling", () => {\n  assert.match(css, /scroll-padding-inline:12px/);\n  assert.match(css, /\\.filters:before,\\.filters:after/);\n});\n''')
print("Aster live snapshot UI repair applied")
