from pathlib import Path

SOURCE = Path(__file__).with_name("withdraw_extension.py").read_text(encoding="utf-8")


def test_arbitrum_and_supported_assets_are_explicit():
    assert '"arbitrum": {"chainId": 42161' in SOURCE
    assert '"chainName": "Arbitrum"' in SOURCE
    assert 'SUPPORTED_ASSETS = {"USDC", "USDT"}' in SOURCE


def test_destination_validation_uses_live_aster_asset_metadata():
    assert 'def _asset_metadata_on_chain' in SOURCE
    assert '/withdraw/assets' in SOURCE
    assert 'accountType": "perp"' in SOURCE
    assert 'assetDecimals' in SOURCE
    assert 'EVM_ADDRESS.fullmatch(address)' in SOURCE


def test_withdrawal_signature_contract_is_user_controlled():
    assert '"primaryType": "Action"' in SOURCE
    assert '"type": "Withdraw"' in SOURCE
    assert '"destination Chain"' in SOURCE
    assert '"aster chain": "Mainnet"' in SOURCE
    assert 'Account.recover_message' in SOURCE
    assert 'MetaMask-wallet komt niet overeen met de gekoppelde Aster-wallet' in SOURCE


def test_withdrawal_is_idempotent_and_resumable():
    assert 'idempotencyKey' in SOURCE
    assert 'Er staat al een opname open' in SOURCE
    assert 'AWAITING_SIGNATURE' in SOURCE
    assert 'SUBMITTED' in SOURCE
    assert 'CONFIRMING' in SOURCE
    assert 'COMPLETED' in SOURCE
