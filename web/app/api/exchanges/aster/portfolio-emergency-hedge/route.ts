export const dynamic = "force-dynamic";

const disabledState = {
  enabled: false,
  armed: false,
  status: "OFF",
  featureAvailable: false,
  disabledReason: "Portfolio Noodhedge is per direct uitgeschakeld",
  startPortfolioValue: 0,
  triggerPortfolioValue: 0,
  triggerPercentage: 0,
  maxAllowedLoss: 0,
  currentPortfolioValue: null,
  activatedAt: null,
  triggeredAt: null,
  lockedAt: null,
  lastError: "",
};

const response = () => Response.json(disabledState, {
  status: 200,
  headers: { "Cache-Control": "no-store, max-age=0" },
});

export async function GET() {
  return response();
}

export async function PUT() {
  return response();
}
