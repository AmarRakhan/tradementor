from pathlib import Path

import pytest

from aster_spot_balance import (
    AsterSpotBalanceError,
    build_signed_account_query,
    normalize_spot_balance,
)


def test_signed_account_query_signs_exact_user_signer_nonce_order():
    seen = []

    def sign(message: str) -> str:
        seen.append(message)
        return "0xsigned"

    query = build_signed_account_query(
        user_address="0x" + "ab" * 20,
        signer_address="0x" + "cd" * 20,
        nonce=123456789,
        sign_message=sign,
    )
    expected = f"user={'0x' + 'ab' * 20}&signer={'0x' + 'cd' * 20}&nonce=123456789"
    assert seen == [expected]
    assert query == expected + "&signature=0xsigned"


def test_usdc_balance_is_free_plus_locked_without_float_rounding():
    result = normalize_spot_balance({
        "balances": [
            {"asset": "BTC", "free": "1", "locked": "2"},
            {"asset": "USDC", "free": "12.34000000", "locked": "0.66000000"},
        ]
    })
    assert result == {
        "asset": "USDC",
        "free": "12.34",
        "locked": "0.66",
        "total": "13",
        "source": "ASTER_SPOT_V3",
        "readOnly": True,
    }


def test_missing_usdc_is_a_valid_zero_balance():
    result = normalize_spot_balance({"balances": [{"asset": "BTC", "free": "1", "locked": "0"}]})
    assert result["free"] == "0"
    assert result["locked"] == "0"
    assert result["total"] == "0"


def test_negative_or_malformed_balance_fails_closed():
    with pytest.raises(AsterSpotBalanceError):
        normalize_spot_balance({"balances": [{"asset": "USDC", "free": "-1", "locked": "0"}]})
    with pytest.raises(AsterSpotBalanceError):
        normalize_spot_balance({"balances": "not-a-list"})


def test_production_extension_is_read_only_and_registered():
    root = Path(__file__).resolve().parent
    extension = (root / "aster_spot_balance_extension.py").read_text()
    entrypoint = (root / "withdraw_app.py").read_text()

    assert '@main.app.get("/v1/me/aster/spot-balance")' in extension
    assert 'client.get(f"/api/v3/account?{query}"' in extension
    assert "client.post(" not in extension
    assert "client.put(" not in extension
    assert "client.delete(" not in extension
    assert "client.request(" not in extension
    assert "import aster_spot_balance_extension" in entrypoint
