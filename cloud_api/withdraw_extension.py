from __future__ import annotations

import hashlib
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

import httpx
from eth_account import Account
try:
    from eth_account.messages import encode_typed_data
except ImportError:  # pragma: no cover
    encode_typed_data = None
from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

import main
from aster_signing import local_eip712_signer

EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
SUPPORTED_NETWORKS = {
    "arbitrum": {"chainId": 42161, "chainName": "Arbitrum", "label": "Arbitrum One"},
    "ethereum": {"chainId": 1, "chainName": "ETH", "label": "Ethereum"},
    "bsc": {"chainId": 56, "chainName": "BSC", "label": "BNB Smart Chain"},
}
SUPPORTED_ASSETS = {"USDC", "USDT"}
PENDING = {"CREATED", "VALIDATED", "AWAITING_SIGNATURE", "SIGNED", "SUBMITTED", "CONFIRMING"}
FINAL = {"COMPLETED", "FAILED", "CANCELLED"}


class ContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    avatar: str = Field(default="", max_length=500_000)
    description: str = Field(default="", max_length=240)


class DestinationCreate(BaseModel):
    contactId: str = Field(min_length=8, max_length=120)
    label: str = Field(min_length=1, max_length=100)
    destinationType: str = Field(default="wallet", pattern="^(wallet|exchange|cold_wallet)$")
    asset: str = Field(min_length=2, max_length=12)
    network: str = Field(min_length=2, max_length=30)
    address: str = Field(min_length=42, max_length=42)


class IntentCreate(BaseModel):
    destinationId: str = Field(min_length=8, max_length=120)
    amount: str = Field(min_length=1, max_length=40)
    idempotencyKey: str = Field(min_length=16, max_length=120)


class SignatureSubmit(BaseModel):
    signature: str = Field(min_length=130, max_length=132)
    walletAddress: str = Field(min_length=42, max_length=42)


def _uid(user: dict[str, Any]) -> str:
    return str(user["uid"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value) if value else None


def _clean_doc(snapshot: Any) -> dict[str, Any]:
    value = snapshot.to_dict() or {}
    for key, item in tuple(value.items()):
        if isinstance(item, datetime):
            value[key] = _iso(item)
    return {"id": snapshot.id, **value}


def _contact_root(user: dict[str, Any]):
    return main.user_reference(user).collection("transferContacts")


def _destination_root(user: dict[str, Any]):
    return main.user_reference(user).collection("transferDestinations")


def _intent_root(user: dict[str, Any]):
    return main.user_reference(user).collection("withdrawalIntents")


def _signing_session_root():
    return main.db.collection("withdrawalSigningSessions")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _audit(user: dict[str, Any], action: str, intent_id: str = "", **extra: Any) -> None:
    main.user_reference(user).collection("withdrawalAudit").document().set({
        "action": action, "intentId": intent_id, "at": _now(), **extra,
    })


def _network(value: str) -> tuple[str, dict[str, Any]]:
    normalized = value.strip().lower().replace(" one", "").replace("bnb smart chain", "bsc")
    aliases = {"arb": "arbitrum", "arbitrum one": "arbitrum", "eth": "ethereum", "bnb": "bsc"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in SUPPORTED_NETWORKS:
        raise HTTPException(422, "Dit netwerk wordt nog niet ondersteund voor overboeken")
    return normalized, SUPPORTED_NETWORKS[normalized]


def _amount(value: str, max_decimals: int = 8) -> Decimal:
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise HTTPException(422, "Ongeldig bedrag") from exc
    if not number.is_finite() or number <= 0:
        raise HTTPException(422, "Bedrag moet groter dan nul zijn")
    if number.as_tuple().exponent < -max(0, int(max_decimals)):
        raise HTTPException(422, f"Bedrag mag maximaal {max_decimals} decimalen hebben")
    return number


def _plain(value: Decimal | str | float) -> str:
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    return format(number.normalize(), "f")


def _profile_wallet(user: dict[str, Any]) -> str:
    control = main.user_reference(user).collection("executionControls").document("aster").get().to_dict() or {}
    master = str(control.get("masterAddress", "")).strip().lower()
    if EVM_ADDRESS.fullmatch(master):
        return master
    profile = main.user_reference(user).get().to_dict() or {}
    address = str(profile.get("asterWalletAddress", "")).strip().lower()
    if EVM_ADDRESS.fullmatch(address):
        return address
    raise HTTPException(409, "Koppel eerst je MetaMask-wallet aan je Aster-account")


def _asset_metadata_on_chain(chain_id: int, asset: str) -> dict[str, Any]:
    try:
        response = httpx.get(
            "https://www.asterdex.com/bapi/futures/v1/public/future/aster/withdraw/assets",
            params={"chainIds": str(chain_id), "networks": "EVM", "accountType": "perp"},
            timeout=12.0,
        )
        payload = response.json()
        response.raise_for_status()
        rows = payload.get("data") if isinstance(payload, dict) else None
        match = next((row for row in rows or [] if isinstance(row, dict) and str(row.get("name", "")).upper() == asset), None)
        if not match:
            raise HTTPException(422, "Deze asset/netwerkcombinatie wordt door Aster niet ondersteund voor opnemen")
        return match
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Aster-netwerkondersteuning kon niet betrouwbaar worden gecontroleerd") from exc


def _v3_request(user: dict[str, Any], method: str, path: str, params: dict[str, Any]) -> Any:
    secret = main.load_aster_secret(user)
    values = dict(params)
    values["nonce"] = str(time.time_ns() // 1000)
    values["user"] = _profile_wallet(user)
    values["signer"] = secret.signer_address
    encoded = urlencode([(key, str(value)) for key, value in values.items()])
    signature = local_eip712_signer(secret)(encoded)
    signed = f"{encoded}&signature={signature}"
    try:
        with httpx.Client(base_url="https://fapi.asterdex.com", timeout=15.0) as client:
            response = client.request(method.upper(), f"{path}?{signed}", headers={"Content-Type": "application/json"})
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Aster-opnameservice is tijdelijk niet bereikbaar") from exc
    if response.status_code >= 400 or (isinstance(payload, dict) and payload.get("code") not in (None, 0, "0")):
        message = payload.get("msg", payload.get("message", "Aster heeft de opname afgewezen")) if isinstance(payload, dict) else "Aster heeft de opname afgewezen"
        raise HTTPException(409, str(message))
    return payload


def _withdraw_info(user: dict[str, Any]) -> dict[str, Any]:
    value = _v3_request(user, "POST", "/fapi/v3/aster/user-withdraw-info", {})
    if not isinstance(value, dict):
        raise HTTPException(502, "Aster gaf geen bruikbare opnamegegevens")
    return value


def _fee(chain_id: int, asset: str) -> Decimal:
    try:
        response = httpx.get(
            "https://www.asterdex.com/bapi/futures/v1/public/future/aster/estimate-withdraw-fee",
            params={"chainId": chain_id, "network": "EVM", "currency": asset, "accountType": "perp"},
            timeout=12.0,
        )
        payload = response.json()
        response.raise_for_status()
        value = (payload.get("data") or {}).get("gasCost") if isinstance(payload, dict) else None
        fee = Decimal(str(value))
        if fee < 0 or not fee.is_finite():
            raise ValueError
        return fee
    except Exception as exc:
        raise HTTPException(502, "Actuele Aster-withdrawal fee kon niet worden opgehaald") from exc


def _withdraw_typed_data(chain_id: int, chain_name: str, destination: str, asset: str,
                         amount: str, fee: str, nonce: int) -> dict[str, Any]:
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Action": [
                {"name": "type", "type": "string"},
                {"name": "destination", "type": "address"},
                {"name": "destination Chain", "type": "string"},
                {"name": "token", "type": "string"},
                {"name": "amount", "type": "string"},
                {"name": "fee", "type": "string"},
                {"name": "nonce", "type": "uint256"},
                {"name": "aster chain", "type": "string"},
            ],
        },
        "primaryType": "Action",
        "domain": {"name": "Aster", "version": "1", "chainId": chain_id,
                   "verifyingContract": "0x0000000000000000000000000000000000000000"},
        "message": {"type": "Withdraw", "destination": destination,
                    "destination Chain": chain_name, "token": asset, "amount": amount,
                    "fee": fee, "nonce": nonce, "aster chain": "Mainnet"},
    }


def _recover(typed_data: dict[str, Any], signature: str) -> str:
    try:
        if encode_typed_data is None:
            from eth_account.messages import encode_structured_data
            message = encode_structured_data(typed_data)
        else:
            message = encode_typed_data(full_message=typed_data)
        return Account.recover_message(message, signature=signature).lower()
    except Exception as exc:
        raise HTTPException(422, "MetaMask-handtekening is ongeldig") from exc


def _destination(user: dict[str, Any], destination_id: str) -> dict[str, Any]:
    snap = _destination_root(user).document(destination_id).get()
    value = snap.to_dict() or {}
    if not value or str(value.get("userId")) != _uid(user):
        raise HTTPException(404, "Bestemming niet gevonden")
    return {"id": snap.id, **value}


def _public_intent(value: dict[str, Any], intent_id: str) -> dict[str, Any]:
    allowed = ("destinationId", "destinationLabel", "asset", "network", "chainId", "address",
               "requestedAmount", "fee", "expectedNetAmount", "status", "walletAddress",
               "withdrawId", "txHash", "errorCode", "errorMessage", "createdAt", "signedAt",
               "submittedAt", "completedAt", "updatedAt")
    result = {"id": intent_id}
    for key in allowed:
        if key in value:
            result[key] = _iso(value[key]) if isinstance(value[key], datetime) else value[key]
    return result


@main.app.get("/v1/me/transfers/contacts")
def transfer_contacts(user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    contacts = [_clean_doc(row) for row in _contact_root(user).order_by("createdAt").stream()]
    destinations = [_clean_doc(row) for row in _destination_root(user).stream()]
    for contact in contacts:
        contact["destinations"] = [item for item in destinations if item.get("contactId") == contact["id"]]
    return {"contacts": contacts}


@main.app.post("/v1/me/transfers/contacts")
def create_transfer_contact(request: ContactCreate, user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    ref = _contact_root(user).document()
    value = {"userId": _uid(user), "name": request.name.strip(), "avatar": request.avatar,
             "description": request.description.strip(), "createdAt": _now(), "updatedAt": _now()}
    ref.set(value)
    return {"contact": _clean_doc(ref.get())}


@main.app.post("/v1/me/transfers/destinations")
def create_transfer_destination(request: DestinationCreate, user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    contact = _contact_root(user).document(request.contactId).get().to_dict() or {}
    if str(contact.get("userId")) != _uid(user):
        raise HTTPException(404, "Contact niet gevonden")
    asset = request.asset.strip().upper()
    if asset not in SUPPORTED_ASSETS:
        raise HTTPException(422, "Alleen USDC en USDT zijn in deze eerste versie toegestaan")
    network_key, network = _network(request.network)
    address = request.address.strip()
    if not EVM_ADDRESS.fullmatch(address):
        raise HTTPException(422, "Dit is geen geldig EVM-adres")
    asset_meta = _asset_metadata_on_chain(int(network["chainId"]), asset)
    asset_decimals = int(asset_meta.get("decimals", 8) or 8)
    ref = _destination_root(user).document()
    value = {"userId": _uid(user), "contactId": request.contactId, "label": request.label.strip(),
             "destinationType": request.destinationType, "asset": asset, "network": network_key,
             "networkLabel": network["label"], "chainId": network["chainId"], "address": address,
             "assetDecimals": asset_decimals, "validationStatus": "VALIDATED", "createdAt": _now(), "updatedAt": _now()}
    ref.set(value)
    _audit(user, "DESTINATION_CREATED", destinationId=ref.id, chainId=network["chainId"], asset=asset)
    return {"destination": _clean_doc(ref.get())}


@main.app.get("/v1/me/transfers/quote")
def transfer_quote(destinationId: str = Query(min_length=8, max_length=120),
                   user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    destination = _destination(user, destinationId)
    fee = _fee(int(destination["chainId"]), str(destination["asset"]))
    info = _withdraw_info(user)
    asset_info = (info.get("balances") or {}).get(str(destination["asset"]), {})
    chain_info = (asset_info.get("chainBalances") or {}).get(str(destination["chainId"]), {})
    maximum = Decimal(str(chain_info.get("perpMaxWithdrawAmount", asset_info.get("perpTotalWithdrawAmount", "0")) or "0"))
    exchange_fee = Decimal(str(chain_info.get("withdrawFee", fee) or fee))
    return {"asset": destination["asset"], "network": destination["networkLabel"],
            "chainId": destination["chainId"], "withdrawableAmount": _plain(maximum),
            "fee": _plain(exchange_fee), "destination": {"id": destinationId, "label": destination["label"],
            "address": destination["address"]}}


@main.app.post("/v1/me/transfers/intents")
def create_withdrawal_intent(request: IntentCreate, user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    duplicate = list(_intent_root(user).where("idempotencyKey", "==", request.idempotencyKey).limit(1).stream())
    if duplicate:
        value = duplicate[0].to_dict() or {}
        return {"intent": _public_intent(value, duplicate[0].id), "typedData": value.get("typedData")}
    destination = _destination(user, request.destinationId)
    amount = _amount(request.amount, int(destination.get("assetDecimals", 8) or 8))
    quote = transfer_quote(request.destinationId, user)
    maximum, fee = Decimal(str(quote["withdrawableAmount"])), Decimal(str(quote["fee"]))
    if amount > maximum:
        raise HTTPException(422, "Bedrag is hoger dan het actuele opneembare Aster-saldo")
    if amount <= fee:
        raise HTTPException(422, "Bedrag moet hoger zijn dan de netwerkfee")
    pending = [row for row in _intent_root(user).where("status", "in", list(PENDING)).limit(3).stream()]
    if pending:
        raise HTTPException(409, "Er staat al een opname open. Rond die eerst af.")
    nonce = time.time_ns() // 1000
    typed_data = _withdraw_typed_data(int(destination["chainId"]), SUPPORTED_NETWORKS[str(destination["network"])]["chainName"],
                                     str(destination["address"]), str(destination["asset"]), _plain(amount), _plain(fee), nonce)
    ref = _intent_root(user).document()
    now = _now()
    value = {"userId": _uid(user), "destinationId": request.destinationId, "destinationLabel": destination["label"],
             "asset": destination["asset"], "network": destination["networkLabel"], "networkKey": destination["network"],
             "chainId": destination["chainId"], "address": destination["address"], "requestedAmount": _plain(amount),
             "fee": _plain(fee), "expectedNetAmount": _plain(amount - fee), "status": "AWAITING_SIGNATURE",
             "nonce": nonce, "typedData": typed_data, "idempotencyKey": request.idempotencyKey,
             "createdAt": now, "updatedAt": now}
    ref.set(value)
    _audit(user, "WITHDRAWAL_INTENT_CREATED", ref.id, destinationId=request.destinationId, amount=_plain(amount))
    return {"intent": _public_intent(value, ref.id), "typedData": typed_data}


def _submit_withdrawal_signature_for_user(intent_id: str, request: SignatureSubmit, user: dict[str, Any]) -> dict[str, Any]:
    ref = _intent_root(user).document(intent_id)
    value = ref.get().to_dict() or {}
    if str(value.get("userId")) != _uid(user):
        raise HTTPException(404, "Opname niet gevonden")
    if value.get("status") in {"SUBMITTED", "CONFIRMING", "COMPLETED"}:
        return {"intent": _public_intent(value, intent_id), "duplicate": True}
    if value.get("status") != "AWAITING_SIGNATURE":
        raise HTTPException(409, "Deze opname wacht niet meer op een handtekening")
    wallet = request.walletAddress.strip().lower()
    if not EVM_ADDRESS.fullmatch(wallet):
        raise HTTPException(422, "Ongeldig walletadres")
    recovered = _recover(dict(value["typedData"]), request.signature)
    if recovered != wallet:
        raise HTTPException(422, "Handtekening hoort niet bij de gekozen MetaMask-wallet")
    expected = _profile_wallet(user)
    if recovered != expected:
        raise HTTPException(409, "MetaMask-wallet komt niet overeen met de gekoppelde Aster-wallet")
    ref.set({"status": "SIGNED", "walletAddress": recovered, "signedAt": _now(), "updatedAt": _now()}, merge=True)
    params = {"chainId": int(value["chainId"]), "asset": value["asset"], "amount": value["requestedAmount"],
              "fee": value["fee"], "receiver": value["address"], "userNonce": str(value["nonce"]),
              "userSignature": request.signature}
    try:
        payload = _v3_request(user, "POST", "/fapi/v3/aster/user-withdraw", params)
    except HTTPException as exc:
        ref.set({"status": "FAILED", "errorCode": "ASTER_REJECTED", "errorMessage": str(exc.detail), "updatedAt": _now()}, merge=True)
        _audit(user, "WITHDRAWAL_FAILED", intent_id, reason=str(exc.detail))
        raise
    if not isinstance(payload, dict) or not payload.get("withdrawId"):
        ref.set({"status": "FAILED", "errorCode": "INVALID_RESPONSE", "errorMessage": "Aster gaf geen withdrawal-id", "updatedAt": _now()}, merge=True)
        raise HTTPException(502, "Aster gaf geen betrouwbare bevestiging")
    ref.set({"status": "SUBMITTED", "withdrawId": str(payload.get("withdrawId")), "txHash": str(payload.get("hash", "")),
             "submittedAt": _now(), "updatedAt": _now()}, merge=True)
    _audit(user, "WITHDRAWAL_SUBMITTED", intent_id, withdrawId=str(payload.get("withdrawId")))
    return {"intent": _public_intent(ref.get().to_dict() or {}, intent_id)}


@main.app.post("/v1/me/transfers/intents/{intent_id}/signature")
def submit_withdrawal_signature(intent_id: str, request: SignatureSubmit,
                                user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    return _submit_withdrawal_signature_for_user(intent_id, request, user)


@main.app.post("/v1/me/transfers/intents/{intent_id}/signing-session")
def create_withdrawal_signing_session(intent_id: str,
                                      user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    value = _intent_root(user).document(intent_id).get().to_dict() or {}
    if str(value.get("userId")) != _uid(user):
        raise HTTPException(404, "Opname niet gevonden")
    if value.get("status") != "AWAITING_SIGNATURE":
        raise HTTPException(409, "Deze opname wacht niet meer op een MetaMask-handtekening")
    token = secrets.token_urlsafe(48)
    expires = _now() + timedelta(minutes=5)
    _signing_session_root().document(_token_hash(token)).set({
        "uid": _uid(user), "intentId": intent_id, "expiresAt": expires, "used": False, "createdAt": _now(),
    })
    _audit(user, "WITHDRAWAL_SIGNING_SESSION_CREATED", intent_id)
    return {"token": token, "intentId": intent_id, "expiresAt": _iso(expires)}


def _signing_session(token: str) -> tuple[dict[str, Any], dict[str, Any], Any]:
    if len(token) < 40 or len(token) > 160:
        raise HTTPException(404, "Ondertekensessie niet gevonden")
    session_ref = _signing_session_root().document(_token_hash(token))
    session = session_ref.get().to_dict() or {}
    expires = session.get("expiresAt")
    if not session or session.get("used") or not isinstance(expires, datetime) or expires <= _now():
        raise HTTPException(410, "Deze MetaMask-ondertekensessie is verlopen")
    uid = str(session.get("uid", ""))
    intent_id = str(session.get("intentId", ""))
    if not uid or not intent_id:
        raise HTTPException(410, "Deze MetaMask-ondertekensessie is ongeldig")
    user = {"uid": uid}
    value = _intent_root(user).document(intent_id).get().to_dict() or {}
    if str(value.get("userId")) != uid or value.get("status") != "AWAITING_SIGNATURE":
        raise HTTPException(409, "Deze opname wacht niet meer op een MetaMask-handtekening")
    return session, {"id": intent_id, **value}, session_ref


@main.app.get("/v1/transfers/signing/{token}")
def public_withdrawal_signing_session(token: str) -> dict[str, Any]:
    session, value, _ = _signing_session(token)
    user = {"uid": str(session["uid"])}
    expected = _profile_wallet(user)
    return {
        "intent": _public_intent(value, str(value["id"])),
        "typedData": value.get("typedData"),
        "walletAddress": expected,
        "expiresAt": _iso(session.get("expiresAt")),
    }


@main.app.post("/v1/transfers/signing/{token}")
def public_submit_withdrawal_signature(token: str, request: SignatureSubmit) -> dict[str, Any]:
    session, value, session_ref = _signing_session(token)
    user = {"uid": str(session["uid"])}
    result = _submit_withdrawal_signature_for_user(str(value["id"]), request, user)
    session_ref.set({"used": True, "usedAt": _now()}, merge=True)
    return result


@main.app.get("/v1/me/transfers/intents/{intent_id}")
def withdrawal_intent_status(intent_id: str, user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    ref = _intent_root(user).document(intent_id)
    value = ref.get().to_dict() or {}
    if str(value.get("userId")) != _uid(user):
        raise HTTPException(404, "Opname niet gevonden")
    if value.get("status") in {"SUBMITTED", "CONFIRMING"}:
        try:
            history = _v3_request(user, "POST", "/fapi/v3/aster/deposit-withdraw-history", {})
            record = next((row for row in history if isinstance(row, dict) and str(row.get("id")) == str(value.get("withdrawId"))), None) if isinstance(history, list) else None
            if record:
                state = str(record.get("state", "")).upper()
                update: dict[str, Any] = {"updatedAt": _now()}
                if record.get("txHash"): update["txHash"] = str(record["txHash"])
                if state == "SUCCESS": update.update({"status": "COMPLETED", "completedAt": _now()})
                elif state == "FAILED": update.update({"status": "FAILED", "errorCode": "ASTER_FAILED", "errorMessage": "Aster heeft de opname als mislukt gemarkeerd"})
                else: update["status"] = "CONFIRMING"
                ref.set(update, merge=True)
                value.update(update)
        except Exception:
            pass
    response: dict[str, Any] = {"intent": _public_intent(value, intent_id)}
    if value.get("status") == "AWAITING_SIGNATURE":
        response["typedData"] = value.get("typedData")
    return response


@main.app.post("/v1/me/transfers/intents/{intent_id}/cancel")
def cancel_withdrawal_intent(intent_id: str, user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    ref = _intent_root(user).document(intent_id)
    value = ref.get().to_dict() or {}
    if str(value.get("userId")) != _uid(user):
        raise HTTPException(404, "Opname niet gevonden")
    if value.get("status") not in {"CREATED", "VALIDATED", "AWAITING_SIGNATURE"}:
        raise HTTPException(409, "Deze opname kan niet meer veilig worden geannuleerd")
    ref.set({"status": "CANCELLED", "updatedAt": _now()}, merge=True)
    _audit(user, "WITHDRAWAL_CANCELLED", intent_id)
    return {"intent": _public_intent(ref.get().to_dict() or {}, intent_id)}


@main.app.get("/v1/me/transfers/recent")
def recent_transfers(user: dict[str, Any] = Depends(main.authenticated_user)) -> dict[str, Any]:
    rows = list(_intent_root(user).order_by("createdAt", direction="DESCENDING").limit(50).stream())
    return {"transfers": [_public_intent(row.to_dict() or {}, row.id) for row in rows]}
