import pytest

from aster_signing import ASTER_EIP712_DOMAIN, AsterSecret, typed_message


KEY = "11" * 32


def test_secret_repr_and_public_metadata_never_expose_private_key():
    secret = AsterSecret.create("0x" + "ab" * 20, KEY)
    assert KEY not in repr(secret)
    assert secret.public_metadata() == {"signerAddressSuffix": "ababab"}
    assert "private" not in str(secret.public_metadata()).lower()


def test_invalid_key_or_signer_address_is_rejected_before_storage():
    with pytest.raises(ValueError):
        AsterSecret.create("0x" + "ab" * 20, "short")
    with pytest.raises(ValueError):
        AsterSecret.create("wrong", KEY)


def test_typed_message_matches_official_aster_v3_domain_and_exact_payload():
    payload = "symbol=BTCUSDT&side=BUY&nonce=1&signer=0xabc"
    value = typed_message(payload)
    assert value["domain"] == ASTER_EIP712_DOMAIN
    assert value["primaryType"] == "Message"
    assert value["message"]["msg"] == payload

