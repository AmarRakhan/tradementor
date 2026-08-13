import getpass
import os

import uvicorn

from server import configure
from credential_store import load as load_credentials, save as save_credentials


def main() -> None:
    print("TradeMentor lokale handelsserver")
    print("De API-sleutel wordt alleen in het werkgeheugen gehouden.")
    stored = load_credentials()
    if stored:
        master, key = stored
        print("Walletadres en API-wallet veilig geladen via Windows-beveiliging.")
    else:
        master = input("MetaMask/Hyperliquid hoofdwalletadres: ").strip()
        key = getpass.getpass("Private sleutel van de Hyperliquid API-wallet: ").strip()
        save_credentials(master, key)
        print("API-wallet versleuteld opgeslagen voor toekomstige serverstarts.")
    preset_live = os.getenv("TRADEMENTOR_ALLOW_LIVE", "").lower() == "true"
    mode = "LIVE" if preset_live else input("Typ TEST voor één order of LIVE voor appgestuurde handel (anders Enter): ").strip().upper()
    test_mode = mode == "TEST"
    live_mode = mode == "LIVE"
    if test_mode:
        os.environ["TRADEMENTOR_ALLOW_ONE_TEST_ORDER"] = "true"
    if live_mode:
        os.environ["TRADEMENTOR_ALLOW_LIVE"] = "true"
    token = configure(master, key)
    print(f"\nVerbinding voorbereid. Handelsmodus: {'LIVE' if live_mode else 'EENMALIGE TEST' if test_mode else 'UIT'}.")
    if (test_mode or live_mode) and not os.getenv("TRADEMENTOR_SESSION_TOKEN", "").strip():
        print(f"Lokale servercode voor TradeMentor Wallet: {token}")
    elif test_mode or live_mode:
        print("Bestaande TradeMentor-servercode veilig hergebruikt.")
    uvicorn.run("server:app", host="0.0.0.0", port=8787, reload=False)


if __name__ == "__main__":
    main()
