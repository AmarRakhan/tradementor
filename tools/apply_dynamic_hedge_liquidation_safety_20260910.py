from pathlib import Path

MAIN = Path("cloud_api/main.py")


def replace_once(text: str, old: str, new: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"Expected main.py marker not found: {old[:160]!r}")
    return text.replace(old, new, 1)


text = MAIN.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from aster_hedge_recovery_api import install_aster_hedge_recovery_routes, load_hedge_settings, profit_preview_with_settings\n",
    "from aster_hedge_recovery_api import install_aster_hedge_recovery_routes, load_hedge_settings, profit_preview_with_settings\n"
    "from aster_dynamic_hedge_api import install_aster_dynamic_hedge_routes\n",
)

marker = "# DYNAMIC_HEDGE_LIQUIDATION_SAFETY_ROUTES_20260910"
if marker not in text:
    text += f'''\n\n{marker}\ndef _dynamic_hedge_aster_client(user: dict[str, Any], live: bool = False) -> AsterV3Client:\n    secret = load_aster_secret(user)\n    return AsterV3Client(\n        signer_address=secret.signer_address,\n        sign_message=local_eip712_signer(secret),\n        live_authorized=bool(live),\n    )\n\n\ninstall_aster_dynamic_hedge_routes(\n    app,\n    authenticated_user=authenticated_user,\n    user_reference=user_reference,\n    client_factory=_dynamic_hedge_aster_client,\n)\n'''

MAIN.write_text(text, encoding="utf-8")
print("Dynamic Hedge liquidation-safety routes installed in cloud_api/main.py")
