from pathlib import Path

root = Path(__file__).resolve().parents[1]
page = root / "web/app/page.tsx"
text = page.read_text()

anchor = 'import { deriveAsterAccountDisplay, type AsterAccountDisplay } from "@/lib/aster-account-display";'
portfolio_import = 'import { PortfolioImpactBattle } from "@/components/portfolio-impact-battle";'
if portfolio_import not in text:
    assert anchor in text, "page import anchor changed"
    text = text.replace(anchor, anchor + "\n" + portfolio_import, 1)

old = '''      {!positionsOnly && <section className="direction-balance" aria-label="Long en short balans">
        <DirectionBalanceCell label="LONG" count={view.accountDataAvailable ? longPositions.length : null} value={view.accountDataAvailable ? longPnl : null} />
        <DirectionBalanceCell label="NETTO OPEN PNL" value={view.accountDataAvailable ? netOpenPnl : null} center />
        <DirectionBalanceCell label="SHORT" count={view.accountDataAvailable ? shortPositions.length : null} value={view.accountDataAvailable ? shortPnl : null} />
      </section>}'''
new = '''      {!positionsOnly && (destination === "aster" ? <PortfolioImpactBattle
        positions={view.positions}
        equity={view.equityNumber}
        dataAvailable={view.accountDataAvailable}
        updatedAt={snapshot.updatedAt}
      /> : <section className="direction-balance" aria-label="Long en short balans">
        <DirectionBalanceCell label="LONG" count={view.accountDataAvailable ? longPositions.length : null} value={view.accountDataAvailable ? longPnl : null} />
        <DirectionBalanceCell label="NETTO OPEN PNL" value={view.accountDataAvailable ? netOpenPnl : null} center />
        <DirectionBalanceCell label="SHORT" count={view.accountDataAvailable ? shortPositions.length : null} value={view.accountDataAvailable ? shortPnl : null} />
      </section>)}'''
if old in text:
    text = text.replace(old, new, 1)
elif '<PortfolioImpactBattle' not in text:
    raise AssertionError("direction balance block changed; refusing an unsafe approximate patch")

page.write_text(text)
print("Portfolio Impact Bulls integration applied safely")
