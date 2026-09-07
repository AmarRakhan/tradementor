from decimal import Decimal

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from fastapi import HTTPException

import withdraw_extension as withdraw


def test_arbitrum_withdraw_typed_data_matches_aster_contract():
    destination = "0x" + "1" * 40
    typed = withdraw._withdraw_typed_data(42161, "Arbitrum", destination, "USDC", "5", "0.1", 123456)
    assert typed["domain"] == {
        "name": "Aster", "version": "1", "chainId": 42161,
        "verifyingContract": "0x0000000000000000000000000000000000000000",
    }
    assert typed["message"]["type"] == "Withdraw"
    assert typed["message"]["destination"] == destination
    assert typed["message"]["destination Chain"] == "Arbitrum"
    assert typed["message"]["aster chain"] == "Mainnet"


def test_amount_enforces_asset_precision():
    assert withdraw._amount("5.123456", 6) == Decimal("5.123456")
    with pytest.raises(HTTPException):
        withdraw._amount("5.1234567", 6)


def test_signature_recovery_accepts_only_actual_signer():
    account = Account.create()
    typed = withdraw._withdraw_typed_data(
        42161, "Arbitrum", "0x" + "2" * 40, "USDC", "5", "0.1", 999999,
    )
    signed = Account.sign_message(encode_typed_data(full_message=typed), account.key)
    recovered = withdraw._recover(typed, signed.signature.hex())
    assert recovered == account.address.lower()


def test_network_aliases_keep_arbitrum_chain_id_authoritative():
    key, network = withdraw._network("Arbitrum One")
    assert key == "arbitrum"
    assert network["chainId"] == 42161
    assert network["chainName"] == "Arbitrum"
