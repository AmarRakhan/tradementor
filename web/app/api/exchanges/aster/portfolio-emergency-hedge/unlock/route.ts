const disabledState = {
  enabled: false,
  armed: false,
  status: "OFF",
  featureAvailable: false,
  disabledReason: "Portfolio Noodhedge is per direct uitgeschakeld",
  lastError: "",
};

export async function POST() {
  return Response.json(disabledState, {
    status: 200,
    headers: { "Cache-Control": "no-store, max-age=0" },
  });
}
