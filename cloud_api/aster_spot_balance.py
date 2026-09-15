"""Pure helpers for read-only Aster Spot V3 balance queries."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any, Callable
from urllib.parse import urlencode


SUPPORTED_SPOT_ASSETS = frozenset({"USDC", "USDT"})
_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


class AsterSpotBalanceError(ValueError):
    pass


def _address(value: str, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not _EVM_ADDRESS.fullmatch(clean):
        raise AsterSpotBalanceError(f"Ongeldig {label}")
    return clean


def _amount(value: Any, label: str) -> Decimal:
    try:
        number = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError) as exc:
        raise AsterSpotBalanceError(f"Ongeldige Aster Spot {label}") from exc
    if not number.is_finite() or number < 0:
        raise AsterSpotBalanceError(f"Ongeldige Aster Spot {label}")
    return number


def _plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def build_signed_account_query(
    *,
    user_address: str,
    signer_address: str,
    nonce: int,
    sign_message: Callable[[str], str],
) -> str:
    """Build the exact Spot V3 USER_DATA query string that is EIP-712 signed."""
    user = _address(user_address, "Aster-hoofdwalletadres")
    signer = _address(signer_address, "Aster-agentadres")
    if int(nonce) <= 0:
        raise AsterSpotBalanceError("Ongeldige Aster nonce")
    encoded = urlencode((
        ("user", user),
        ("signer", signer),
        ("nonce", str(int(nonce))),
    ))
    signature = str(sign_message(encoded) or "").strip()
    if not signature:
        raise AsterSpotBalanceError("Aster-handtekening ontbreekt")
    return f"{encoded}&signature={signature}"


def normalize_spot_balance(payload: dict[str, Any], asset: str = "USDC") -> dict[str, Any]:
    """Return one non-negative Spot asset balance without floating-point rounding."""
    symbol = str(asset or "").strip().upper()
    if symbol not in SUPPORTED_SPOT_ASSETS:
        raise AsterSpotBalanceError("Alleen USDC en USDT worden ondersteund")
    if not isinstance(payload, dict) or not isinstance(payload.get("balances"), list):
        raise AsterSpotBalanceError("Aster Spot gaf geen geldige accountbalans")

    row = next((item for item in payload["balances"]
                if isinstance(item, dict) and str(item.get("asset", "")).upper() == symbol), None)
    free = _amount((row or {}).get("free", "0"), "vrij saldo")
    locked = _amount((row or {}).get("locked", "0"), "geblokkeerd saldo")
    total = free + locked
    return {
        "asset": symbol,
        "free": _plain(free),
        "locked": _plain(locked),
        "total": _plain(total),
        "source": "ASTER_SPOT_V3",
        "readOnly": True,
    }
