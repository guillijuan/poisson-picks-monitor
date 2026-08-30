# refresh_participants.py
"""Refresca participants.json (mapa id->nombre de equipo) una vez al mes.
Los equipos cambian por ascensos/descensos entre temporadas; sin este
refresco, equipos nuevos apareceran como "id12345" en vez del nombre.
"""

import json
import os

import requests

API_KEY = os.environ["ODDSPAPI_KEY"]
BASE_URL = "https://api.oddspapi.io"
SPORT_ID = 10  # soccer
OUT_PATH = "participants.json"


def main():
    r = requests.get(f"{BASE_URL}/v4/participants", params={"sportId": SPORT_ID, "apiKey": API_KEY}, timeout=30)
    r.raise_for_status()
    data = r.json()

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    print(f"Guardados {len(data)} equipos en {OUT_PATH}")


if __name__ == "__main__":
    main()
