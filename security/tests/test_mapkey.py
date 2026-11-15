
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

def test_nasa_mapkey_status():
    key = os.getenv("NASA_MAP_KEY")
    assert key, "NASA_MAP_KEY is missing"

    url = (
        "https://firms.modaps.eosdis.nasa.gov/"
        "mapserver/mapkey_status/"
    )

    response = requests.get(
        url,
        params={"MAP_KEY": key},
        timeout=15
    )

    assert response.status_code == 200
    data = response.json()

    assert "transaction_limit" in data
    assert "current_transactions" in data

    print("\nNASA MAP_KEY status response: OK")
    print("Transaction limit:", data["transaction_limit"])
    print("Transactions used:", data["current_transactions"])
