"""Aster V3 EIP-712 signing boundary.

Private keys enter only through this small module and are excluded from repr.
Callers store them in per-user Secret Manager secrets, never Firestore or logs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Callable


ASTER_EIP712_DOMAIN = {
    "name": "AsterSignTransaction",
    "version": "1",
    "chainId": 1666,
    "verifyingContract": "0x0000000000000000000000000000000000000000",
}


@dataclass(frozen=True)
class AsterSecret:
    signer_address: str
    private_key: str = field(repr=False)

    @classmethod
    def create(cls, signer_address: str, private_key: str) -> "AsterSecret":
        clean_key = private_key.removeprefix("0x").strip()
        clean_address = signer_address.strip().lower()
        if not re.fullmatch(r"[0-9a-fA-F]{64}", clean_key):
            raise ValueError("Ongeldige Aster API-walletsleutel")
        if not re.fullmatch(r"0x[0-9a-f]{40}", clean_address):
            raise ValueError("Ongeldig Aster signer-adres")
        return cls(clean_address, clean_key)

    def public_metadata(self) -> dict[str, str]:
        return {"signerAddressSuffix": self.signer_address[-6:]}


def typed_message(encoded_parameters: str) -> dict[str, Any]:
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Message": [{"name": "msg", "type": "string"}],
        },
        "primaryType": "Message",
        "domain": dict(ASTER_EIP712_DOMAIN),
        "message": {"msg": encoded_parameters},
    }


def local_eip712_signer(secret: AsterSecret) -> Callable[[str], str]:
    """Create signer lazily so pure tests never need credential libraries."""
    def sign(encoded_parameters: str) -> str:
        from eth_account import Account
        try:
            from eth_account.messages import encode_typed_data
            message = encode_typed_data(full_message=typed_message(encoded_parameters))
        except ImportError:  # compatibility with older eth-account deployments
            from eth_account.messages import encode_structured_data
            message = encode_structured_data(typed_message(encoded_parameters))
        signed = Account.sign_message(message, private_key=secret.private_key)
        return signed.signature.hex()
    return sign

